"""Content, AEO (answer engine) and GEO (generative engine) readiness rules.

These are deterministic heuristics. They identify *opportunities*; none of them is a documented
ranking factor for any AI system, and the texts say so. AI-assisted content analysis (questions a
page should answer, missing sections, entities) lives in app.ai and is labelled source="ai".
"""

from __future__ import annotations

import re
from collections import Counter
from datetime import UTC, datetime

from app.audit.engine import Finding, SiteContext, rule
from app.crawler.robots import AI_CRAWLERS

STOPWORDS = set(
    "a an and are as at be by for from has have how i in is it its of on or our that the their this to was we what "
    "when where which who why will with you your can do does not more about into than then them they these those "
    "also any all but if so may such get use using new best guide".split()
)
CLAIM_PATTERNS = re.compile(
    r"(\b\d+(?:\.\d+)?\s?%|\b(?:studies|research|experts|scientists|data)\s+(?:show|shows|found|suggest|prove)s?\b|"
    r"\b(?:proven|guaranteed|clinically|#1|number one|the best)\b|\b\d{1,3}(?:,\d{3})+\b|\b\d+\s?(?:million|billion)\b)",
    re.I,
)


def _parse_date(s: str) -> datetime | None:
    s = s.strip()
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%d"):
        try:
            d = datetime.strptime(s.replace("Z", "+0000") if "T" in s else s[:10], fmt)
            return d if d.tzinfo else d.replace(tzinfo=UTC)
        except ValueError:
            continue
    try:
        d = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=UTC)
    except ValueError:
        return None


# --------------------------------------------------------------- content quality
@rule
def thin_content(ctx: SiteContext) -> list[Finding]:
    out = []
    for p in ctx.indexable_pages:
        wc = (p.extracted or {}).get("word_count", 0)
        if wc < 150 and p.url != ctx.start_url:
            out.append(Finding(
                "content.thin", "content", "low", "recommendation", "medium", "Very little main content",
                f"The main content has about {wc} words.",
                "Word count is not a ranking factor, but pages with little content often fail to fully answer the "
                "searcher's question. Some page types (contact, category) are legitimately short.",
                "If this page targets a search topic, expand it with genuinely useful information.",
                {"word_count": wc}, p.url, fix_type="content_recommendations"))
    return out


@rule
def readability_structure(ctx: SiteContext) -> list[Finding]:
    out = []
    for p in ctx.indexable_pages:
        ex = p.extracted or {}
        long_paras = [x["text"][:160] for x in ex.get("paragraphs", []) if x["tag"] == "p" and len(x["text"].split()) > 150]
        if long_paras:
            out.append(Finding(
                "aeo.long_paragraphs", "aeo", "low", "recommendation", "medium", "Very long paragraphs",
                f"{len(long_paras)} paragraph(s) exceed 150 words.",
                "Shorter, self-contained paragraphs are easier for readers to scan and for answer engines to quote.",
                "Split long paragraphs and lead each with its key point.", {"examples": long_paras[:3]}, p.url,
                fix_type="content_recommendations"))
        if ex.get("word_count", 0) >= 600 and len([h for h in ex.get("headings", []) if h["level"] in (2, 3)]) == 0:
            out.append(Finding(
                "aeo.no_subheadings", "aeo", "low", "recommendation", "high", "Long content without subheadings",
                f"{ex.get('word_count')} words with no H2/H3 subheadings.",
                "Descriptive subheadings help readers and machines locate specific answers in long content.",
                "Break the content into sections with descriptive H2/H3 headings.", {"word_count": ex.get("word_count")},
                p.url, fix_type="content_recommendations"))
    return out


# --------------------------------------------------------------- AEO
@rule
def question_answers(ctx: SiteContext) -> list[Finding]:
    out = []
    for p in ctx.indexable_pages:
        ex = p.extracted or {}
        qs = ex.get("question_headings", [])
        for q in qs:
            if q["answer_words"] == 0:
                out.append(Finding(
                    "aeo.question_unanswered", "aeo", "low", "recommendation", "high",
                    "Question heading without a direct answer",
                    f"The heading '{q['question'][:120]}' is not followed by any text before the next heading.",
                    "Answer engines look for a concise answer immediately after a question.",
                    "Add a 1–3 sentence direct answer right below the heading, then elaborate.",
                    {"question": q["question"]}, p.url, fix_type="answer_paragraph", key=q["question"][:80]))
            elif q["answer_words"] > 90:
                out.append(Finding(
                    "aeo.answer_not_concise", "aeo", "low", "recommendation", "medium",
                    "Answer to a question heading is not concise",
                    f"The first paragraph after '{q['question'][:120]}' is {q['answer_words']} words.",
                    "A short direct answer (about 40–60 words) followed by detail is easier to extract and quote.",
                    "Lead with a concise answer sentence, then expand.",
                    {"question": q["question"], "answer_preview": q["answer_preview"][:300],
                     "answer_words": q["answer_words"]}, p.url, fix_type="answer_paragraph", key=q["question"][:80]))
        if not qs and ex.get("word_count", 0) >= 400 and ex.get("is_article_like"):
            out.append(Finding(
                "aeo.no_question_coverage", "aeo", "low", "recommendation", "low",
                "No question-oriented sections",
                "This article has no headings phrased as the questions readers ask.",
                "Question-and-answer structure maps directly to how people query search and AI assistants.",
                "Identify the main questions your audience asks and answer each under its own heading. "
                "Use 'Generate AI suggestions' for question ideas grounded in this page.",
                {"headings": [h["text"] for h in ex.get("headings", [])][:10]}, p.url, fix_type="faq_section"))
        faq_types = {"FAQPage", "QAPage"}
        if len(qs) >= 3 and not faq_types & set(ex.get("schema_types", [])):
            out.append(Finding(
                "aeo.faq_schema_opportunity", "aeo", "info", "recommendation", "medium",
                "Q&A content without FAQ structured data",
                f"The page has {len(qs)} question headings with answers but no FAQPage markup.",
                "FAQPage markup makes Q&A structure machine-readable. Note: since 2023 Google shows FAQ rich "
                "results only for well-known government and health sites, so the benefit is clarity, not a SERP feature.",
                "Optionally add FAQPage JSON-LD mirroring the visible questions and answers exactly.",
                {"questions": [q["question"] for q in qs][:10]}, p.url, fix_type="json_ld"))
    return out


# --------------------------------------------------------------- GEO / trust signals
@rule
def authorship_and_freshness(ctx: SiteContext) -> list[Finding]:
    out = []
    now = datetime.now(UTC)
    for p in ctx.indexable_pages:
        ex = p.extracted or {}
        if not ex.get("is_article_like"):
            continue
        if not ex.get("has_author"):
            out.append(Finding(
                "geo.author_missing", "geo", "low", "recommendation", "medium", "No visible author information",
                "No author byline, author meta tag, rel=author link or schema author was found on this article.",
                "Clear authorship supports trust assessments by readers, search quality raters and AI systems that "
                "weigh source credibility.",
                "Show the author's name (linking to a bio with relevant experience) and add it to Article schema.",
                {"author_signals": ex.get("author")}, p.url, fix_type="content_recommendations"))
        dates = ex.get("dates", {})
        all_dates = [d for d in (_parse_date(x) for x in dates.get("modified", []) + dates.get("published", [])
                                 + dates.get("time_elements", [])) if d]
        if not all_dates:
            out.append(Finding(
                "geo.date_missing", "geo", "low", "recommendation", "medium", "No publication or update date",
                "No datePublished/dateModified, article time meta or <time> element was found.",
                "Dates help readers and AI systems judge whether information is current.",
                "Display the publish/update date and include it in Article schema.", {"dates": dates}, p.url,
                fix_type="content_recommendations"))
        else:
            newest = max(all_dates)
            age_days = (now - newest).days
            if age_days > 730:
                out.append(Finding(
                    "geo.stale_content", "geo", "info", "recommendation", "medium", "Content may be outdated",
                    f"The most recent date found is {newest.date().isoformat()} ({age_days // 365} years ago).",
                    "For time-sensitive topics, outdated information is less likely to satisfy users or be cited.",
                    "Review the content for accuracy; update it and its dateModified if you make substantive changes.",
                    {"newest_date": newest.isoformat(), "dates": dates}, p.url, fix_type="content_recommendations"))
    return out


@rule
def claims_and_citations(ctx: SiteContext) -> list[Finding]:
    out = []
    for p in ctx.indexable_pages:
        ex = p.extracted or {}
        unsupported = []
        for para in ex.get("paragraphs", []):
            if para["has_link"]:
                continue
            for sentence in re.split(r"(?<=[.!?])\s+", para["text"]):
                if CLAIM_PATTERNS.search(sentence) and 6 < len(sentence.split()) < 60:
                    unsupported.append(sentence.strip()[:300])
        if unsupported:
            out.append(Finding(
                "geo.unsupported_claims", "geo", "low", "recommendation", "low",
                "Statistics or strong claims without a cited source",
                f"{len(unsupported)} sentence(s) contain statistics or strong claims with no link in the same paragraph.",
                "Verifiable sources make claims more trustworthy to readers and to AI systems that prefer "
                "well-supported content. This is a pattern match and may include false positives.",
                "Link each statistic or claim to its original source, or soften claims you cannot support.",
                {"sentences": unsupported[:8]}, p.url, fix_type="content_recommendations"))
        if ex.get("is_article_like") and ex.get("word_count", 0) >= 500 and ex.get("external_link_count", 0) == 0:
            out.append(Finding(
                "geo.no_outbound_citations", "geo", "info", "recommendation", "low", "No external sources cited",
                "This article links to no external pages.",
                "Citing primary sources is a credibility signal for readers; it is not a direct ranking factor.",
                "Where you reference facts, research or data, link to the original source.",
                {"word_count": ex.get("word_count")}, p.url, fix_type="content_recommendations"))
    return out


@rule
def entity_signals(ctx: SiteContext) -> list[Finding]:
    out = []
    home = ctx.by_url.get(ctx.start_url)
    if not home or not home.is_html:
        return out
    ex = home.extracted or {}
    orgs = []
    for j in ex.get("json_ld", []):
        data = j.get("data")
        nodes = data.get("@graph", [data]) if isinstance(data, dict) else (data if isinstance(data, list) else [])
        for n in nodes:
            if isinstance(n, dict) and n.get("@type") in ("Organization", "LocalBusiness", "Corporation"):
                orgs.append(n)
    if orgs and not any(o.get("sameAs") for o in orgs):
        out.append(Finding(
            "geo.org_sameas_missing", "geo", "low", "recommendation", "medium", "Organization schema has no sameAs links",
            "Organization markup exists but does not link to your official profiles (sameAs).",
            "sameAs links help search and AI systems disambiguate your brand entity.",
            "Add sameAs URLs for official profiles you control (e.g. LinkedIn, Wikipedia/Wikidata if they exist).",
            {"organization": {k: orgs[0].get(k) for k in ("name", "url", "logo") if k in orgs[0]}}, home.url,
            fix_type="json_ld"))
    all_links = {link["href"].lower() for p in ctx.html_pages for link in (p.extracted or {}).get("links", []) if link["internal"]}
    if not any(re.search(r"/(about|about-us|company|who-we-are|team)\b", u) for u in all_links):
        out.append(Finding(
            "geo.about_page_missing", "geo", "low", "recommendation", "low", "No About page found",
            "No internal link to an About/Company page was found on crawled pages.",
            "An About page explaining who is behind the site is a basic transparency signal.",
            "Publish an About page describing your organization, people and expertise, and link to it site-wide.",
            {"note": "Based on internal links found during this crawl."}))
    if not any(re.search(r"/(contact|contact-us|support)\b", u) for u in all_links):
        out.append(Finding(
            "geo.contact_page_missing", "geo", "low", "recommendation", "low", "No Contact page found",
            "No internal link to a Contact page was found on crawled pages.",
            "Visible contact information is a basic trust signal for users and quality evaluators.",
            "Add a Contact page and link to it site-wide.", {"note": "Based on internal links found during this crawl."}))
    return out


@rule
def ai_crawler_access(ctx: SiteContext) -> list[Finding]:
    out = []
    blocked = {name: owner for name, owner in AI_CRAWLERS.items() if ctx.robots.explicitly_blocks_root(name)}
    if blocked:
        out.append(Finding(
            "geo.ai_crawlers_blocked", "geo", "info", "info", "high", "robots.txt blocks some AI crawlers",
            "robots.txt disallows: " + ", ".join(f"{n} ({o})" for n, o in blocked.items()) + ".",
            "This is a legitimate business choice. Blocking a crawler generally means that provider will not use "
            "fresh crawls of your pages; some tokens (e.g. Google-Extended) control AI training/grounding only and "
            "do not affect regular search indexing.",
            "No action needed if intentional. If you want visibility in a given AI product, review whether its "
            "crawler is allowed.", {"blocked": blocked}))
    if ctx.llms_txt is not None and not ctx.llms_txt.get("present"):
        out.append(Finding(
            "geo.llms_txt_absent", "geo", "info", "info", "high", "No llms.txt file",
            "No /llms.txt file was found.",
            "llms.txt is an emerging community proposal. No major search or AI provider has confirmed using it, so "
            "its absence is not a problem.",
            "Optional. Consider it only as a low-cost experiment.", {"status": ctx.llms_txt.get("status")}))
    return out


# --------------------------------------------------------------- internal link opportunities
def _key_terms(title: str) -> list[str]:
    words = [w for w in re.findall(r"[a-zA-Z][a-zA-Z\-]{2,}", title.lower()) if w not in STOPWORDS]
    return words


@rule
def internal_link_opportunities(ctx: SiteContext) -> list[Finding]:
    """Suggest links from page A to page B when A's text mentions B's core topic phrase but doesn't link to B."""
    out = []
    pages = ctx.indexable_pages[:300]
    topics = {}
    for p in pages:
        ex = p.extracted or {}
        h1 = (ex.get("h1s") or [ex.get("title") or ""])[0]
        terms = _key_terms(h1)
        if 2 <= len(terms) <= 6:
            topics[p.url] = (" ".join(terms[:3]), h1)
    counts: Counter = Counter()
    for a in pages:
        ex = a.extracted or {}
        text = (ex.get("main_text") or "").lower()
        linked = {link["href"] for link in ex.get("links", [])}
        for b_url, (phrase, h1) in topics.items():
            if b_url == a.url or b_url in linked or counts[a.url] >= 3:
                continue
            words = phrase.split()
            if len(words) >= 2 and re.search(r"\b" + r"\W+(?:\w+\W+){0,2}".join(map(re.escape, words[:2])) + r"\b", text):
                counts[a.url] += 1
                out.append(Finding(
                    "content.internal_link_opportunity", "content", "info", "recommendation", "low",
                    "Internal link opportunity",
                    f"This page mentions '{' '.join(words[:2])}', the topic of {b_url}, without linking to it.",
                    "Contextual internal links help users navigate and help search engines understand topic relationships.",
                    f"Consider linking the relevant phrase to {b_url} ('{h1[:80]}').",
                    {"target": b_url, "target_heading": h1, "phrase": " ".join(words[:2])}, a.url,
                    fix_type="internal_link_add", key=b_url))
    return out
