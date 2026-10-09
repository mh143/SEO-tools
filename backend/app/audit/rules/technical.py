"""Technical SEO rules."""

from __future__ import annotations

import re
from collections import defaultdict
from urllib.parse import urlsplit

from app.audit.engine import Finding, SiteContext, rule
from app.crawler.extractor import hamming

TITLE_MAX = 60  # approximate display width; truncation is cosmetic, not a penalty
DESC_MAX = 160
BCP47 = re.compile(r"^(x-default|[a-zA-Z]{2,3}(-[a-zA-Z0-9]{2,8})*)$")


def _norm(s: str | None) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower())


# --------------------------------------------------------------- availability & status codes
@rule
def site_level(ctx: SiteContext) -> list[Finding]:
    out: list[Finding] = []
    if ctx.robots_error and getattr(ctx.robots, "disallow_all", False):
        out.append(Finding(
            "tech.robots_unreachable", "technical", "critical", "error", "high",
            "robots.txt could not be retrieved",
            f"Fetching /robots.txt failed ({ctx.robots_error}). Crawlers that follow RFC 9309 treat a server error "
            "on robots.txt as 'do not crawl anything'.",
            "Search engines may stop crawling the whole site while robots.txt returns server errors.",
            "Make /robots.txt return 200 (or 404 if you have no rules). Check server/CDN errors.",
            {"robots_status": ctx.robots_status, "error": ctx.robots_error}))
    home = ctx.by_url.get(ctx.start_url)
    if home and home.status == 200 and home.robots_blocked:
        out.append(Finding(
            "tech.robots_blocks_home", "technical", "critical", "error", "high",
            "robots.txt blocks the homepage",
            "The robots.txt rules disallow crawling the start URL for generic crawlers.",
            "Search engines cannot crawl blocked pages, so their content cannot be evaluated.",
            "Review the Disallow rules in robots.txt.", {"robots_txt_excerpt": ctx.robots.raw[:1500]}, ctx.start_url))
    if ctx.start_url.startswith("http://"):
        out.append(Finding(
            "tech.no_https", "technical", "high", "warning", "high", "Site is served over HTTP, not HTTPS",
            "The start URL resolved to an http:// address and did not redirect to https://.",
            "Browsers mark HTTP pages as 'Not secure', and HTTPS is a lightweight ranking signal for Google.",
            "Install a TLS certificate and 301-redirect all HTTP URLs to HTTPS.", {"resolved_start_url": ctx.start_url}))
    if ctx.limit_reached:
        out.append(Finding(
            "tech.crawl_limit_reached", "technical", "info", "info", "high", "Crawl stopped at the page limit",
            "More pages were discovered than this audit was allowed to crawl; results cover a sample of the site.",
            "Issues on pages beyond the limit are not reported.",
            "Increase the page limit (plan dependent) to audit the full site.", {"pages_crawled": len(ctx.pages)}))
    return out


@rule
def http_errors(ctx: SiteContext) -> list[Finding]:
    out = []
    for p in ctx.pages:
        if p.robots_blocked:
            continue
        if p.status is not None and p.status >= 400:
            sources = ctx.inlinks.get(p.url, [])[:20]
            server = p.status >= 500
            out.append(Finding(
                "tech.http_error", "technical", "high", "error" if p.confirmed_error or not server else "warning",
                "high" if p.confirmed_error or not server else "medium",
                f"Page returns HTTP {p.status}",
                f"{p.url} returned HTTP {p.status}" + (" on two consecutive requests." if server and p.confirmed_error else "."),
                "Users and crawlers following links to this URL reach an error instead of content.",
                "Restore the page, or 301-redirect it to the most relevant live page and update internal links.",
                {"status": p.status, "linked_from": sources, "in_sitemap": p.in_sitemap,
                 "confirmed_by_retry": p.confirmed_error}, p.url, fix_type="broken_link"))
        elif p.error and p.error_kind in ("timeout", "network") and p.confirmed_error:
            out.append(Finding(
                "tech.fetch_failed", "technical", "medium", "warning", "medium", "Page could not be fetched",
                f"Requests to {p.url} failed twice: {p.error}",
                "Pages that time out or drop connections may not be crawled or indexed reliably.",
                "Check server capacity, firewall/CDN rules and response times for this URL.",
                {"error": p.error, "linked_from": ctx.inlinks.get(p.url, [])[:10]}, p.url))
    return out


@rule
def broken_internal_links(ctx: SiteContext) -> list[Finding]:
    out = []
    for target, sources in ctx.inlinks.items():
        tp = ctx.by_url.get(target)
        if not tp or tp.status is None or tp.status < 400:
            continue
        by_source: dict[str, list[str]] = defaultdict(list)
        for s in sources:
            by_source[s["source"]].append(s["text"])
        for src, texts in list(by_source.items())[:50]:
            out.append(Finding(
                "tech.broken_internal_link", "technical", "high", "error", "high" if tp.confirmed_error else "medium",
                f"Broken internal link to a {tp.status} page",
                f"{src} links to {target}, which returned HTTP {tp.status}.",
                "Broken links waste crawl budget, interrupt users and leak internal link equity.",
                "Update the link to point at a live URL, or restore/redirect the target page.",
                {"source": src, "target": target, "target_status": tp.status, "anchor_texts": texts[:5]},
                src, fix_type="internal_link_update", key=target))
    return out


@rule
def redirects(ctx: SiteContext) -> list[Finding]:
    out = []
    for p in ctx.pages:
        chain = p.redirect_chain or []
        if p.error_kind == "redirect_loop":
            out.append(Finding(
                "tech.redirect_loop", "technical", "high", "error", "high", "Redirect loop",
                f"{p.url} redirects in a loop and never reaches a page.",
                "Browsers and crawlers give up on redirect loops; the URL is effectively unreachable.",
                "Fix the redirect rules so the URL resolves to a single final page.",
                {"chain": chain}, p.url, fix_type="redirect"))
        elif len(chain) >= 2:
            out.append(Finding(
                "tech.redirect_chain", "technical", "medium", "warning", "high",
                f"Redirect chain with {len(chain)} hops",
                f"{p.url} passes through {len(chain)} redirects before reaching {p.final_url}.",
                "Each hop adds latency; long chains may not be followed completely by crawlers.",
                "Redirect directly to the final URL and update internal links to the final URL.",
                {"chain": chain, "final_url": p.final_url}, p.url, fix_type="redirect"))
    # internal links pointing at redirects
    for target, sources in ctx.inlinks.items():
        tp = ctx.by_url.get(target)
        if tp and tp.redirect_chain and tp.status and tp.status < 400 and tp.final_url != target:
            for src in sorted({s["source"] for s in sources})[:20]:
                out.append(Finding(
                    "tech.link_to_redirect", "technical", "low", "recommendation", "high",
                    "Internal link points to a redirecting URL",
                    f"{src} links to {target}, which redirects to {tp.final_url}.",
                    "Linking directly to final URLs avoids an extra request for users and crawlers.",
                    f"Change the link target to {tp.final_url}.",
                    {"source": src, "target": target, "final_url": tp.final_url,
                     "status": tp.redirect_chain[0]["status"]}, src, fix_type="internal_link_update", key=target))
    return out


# --------------------------------------------------------------- titles & descriptions
@rule
def titles(ctx: SiteContext) -> list[Finding]:
    out = []
    groups: dict[str, list[str]] = defaultdict(list)
    for p in ctx.html_pages:
        ex = p.extracted or {}
        tags = ex.get("title_tags", [])
        if not tags or not any(t.strip() for t in tags):
            out.append(Finding(
                "tech.title_missing", "technical", "high", "error", "high", "Missing page title",
                "The page has no <title> element or it is empty.",
                "The title is a primary relevance signal and is usually the clickable headline in search results.",
                "Add a unique, descriptive <title> that summarizes the page.",
                {"title_tags": tags, "h1": (ex.get("h1s") or [None])[0]}, p.url, fix_type="meta_title"))
            continue
        if len(tags) > 1:
            out.append(Finding(
                "tech.title_multiple", "technical", "low", "warning", "high", "Multiple <title> elements",
                f"The page contains {len(tags)} <title> elements.",
                "Search engines use one title; multiple tags are usually a theme/plugin conflict.",
                "Remove the duplicate <title> elements so only one remains.", {"title_tags": tags}, p.url))
        t = tags[0]
        if len(t) > TITLE_MAX:
            out.append(Finding(
                "tech.title_long", "technical", "low", "recommendation", "medium", "Title may be truncated in results",
                f"The title is {len(t)} characters; search results typically show about {TITLE_MAX} characters.",
                "Long titles are not penalized, but the end may be cut off in search results.",
                "Put the most important words first, or shorten the title.", {"title": t, "length": len(t)},
                p.url, fix_type="meta_title"))
        elif len(t) < 15:
            out.append(Finding(
                "tech.title_short", "technical", "low", "recommendation", "medium", "Very short title",
                f"The title '{t}' is only {len(t)} characters.",
                "Short titles often miss descriptive terms that help users choose the result.",
                "Expand the title to describe the page's topic.", {"title": t, "length": len(t)}, p.url,
                fix_type="meta_title"))
        if p.indexable:
            groups[_norm(t)].append(p.url)
    for t, urls in groups.items():
        if len(urls) > 1 and t:
            for u in urls:
                out.append(Finding(
                    "tech.title_duplicate", "technical", "medium", "warning", "high", "Duplicate title",
                    f"{len(urls)} indexable pages share the title '{t[:80]}'.",
                    "Identical titles make it harder for search engines and users to tell pages apart.",
                    "Write a unique title for each page.", {"title": t, "pages": urls[:20]}, u, fix_type="meta_title"))
    return out


@rule
def meta_descriptions(ctx: SiteContext) -> list[Finding]:
    out = []
    groups: dict[str, list[str]] = defaultdict(list)
    for p in ctx.indexable_pages:
        ex = p.extracted or {}
        descs = ex.get("meta_descriptions", [])
        if not descs or not descs[0]:
            out.append(Finding(
                "tech.meta_description_missing", "technical", "low", "warning", "high", "Missing meta description",
                "The page has no meta description.",
                "Meta descriptions are not a ranking factor, but search engines often use them as the result snippet.",
                "Add a concise description (roughly 120–160 characters) of what the page offers.",
                {"title": ex.get("title")}, p.url, fix_type="meta_description"))
            continue
        if len(descs) > 1:
            out.append(Finding(
                "tech.meta_description_multiple", "technical", "low", "warning", "high", "Multiple meta descriptions",
                f"The page has {len(descs)} meta description tags.",
                "Conflicting descriptions are usually a plugin conflict; search engines pick one unpredictably.",
                "Keep a single meta description tag.", {"descriptions": descs}, p.url))
        d = descs[0]
        if len(d) > DESC_MAX + 40:
            out.append(Finding(
                "tech.meta_description_long", "technical", "info", "recommendation", "medium",
                "Meta description may be truncated",
                f"The description is {len(d)} characters; snippets are typically cut at about {DESC_MAX}.",
                "Truncation is cosmetic; front-load the key message.", "Shorten or front-load the description.",
                {"description": d, "length": len(d)}, p.url, fix_type="meta_description"))
        groups[_norm(d)].append(p.url)
    for d, urls in groups.items():
        if len(urls) > 1 and d:
            for u in urls:
                out.append(Finding(
                    "tech.meta_description_duplicate", "technical", "low", "warning", "high", "Duplicate meta description",
                    f"{len(urls)} pages share the same meta description.",
                    "Duplicate descriptions are less useful as snippets and are often replaced by search engines.",
                    "Write a unique description per page.", {"description": d[:300], "pages": urls[:20]}, u,
                    fix_type="meta_description"))
    return out


# --------------------------------------------------------------- canonicals & indexability
@rule
def canonicals(ctx: SiteContext) -> list[Finding]:
    out = []
    for p in ctx.html_pages:
        ex = p.extracted or {}
        tags = ex.get("canonical_tags", [])
        raw = ex.get("canonical_raw", [])
        if len(set(tags)) > 1:
            out.append(Finding(
                "tech.canonical_multiple", "technical", "medium", "error", "high", "Conflicting canonical tags",
                f"The page declares {len(set(tags))} different canonical URLs.",
                "When canonical tags conflict, Google ignores all of them.",
                "Keep exactly one rel=canonical tag.", {"canonicals": tags}, p.url, fix_type="canonical"))
            continue
        if not tags:
            if p.indexable:
                out.append(Finding(
                    "tech.canonical_missing", "technical", "low", "recommendation", "medium", "No canonical tag",
                    "The page has no rel=canonical tag.",
                    "A self-referencing canonical helps consolidate URL variants (parameters, trailing slashes).",
                    f"Add <link rel=\"canonical\" href=\"{p.final_url}\">.", {"final_url": p.final_url}, p.url,
                    fix_type="canonical"))
            continue
        c = tags[0]
        if raw and raw[0] and not raw[0].startswith(("http://", "https://")):
            out.append(Finding(
                "tech.canonical_relative", "technical", "info", "recommendation", "high", "Relative canonical URL",
                f"The canonical href '{raw[0]}' is relative.",
                "Relative canonicals work but are error-prone (e.g. on staging hosts).",
                f"Use the absolute URL {c}.", {"canonical_raw": raw[0], "resolved": c}, p.url, fix_type="canonical"))
        target = ctx.by_url.get(c)
        if c.rstrip("/") != p.final_url.rstrip("/"):
            if urlsplit(c).hostname and urlsplit(c).hostname.removeprefix("www.") != ctx.root_host.removeprefix("www."):
                out.append(Finding(
                    "tech.canonical_cross_domain", "technical", "info", "info", "high", "Canonical points to another domain",
                    f"The canonical is {c}.",
                    "Cross-domain canonicals are valid for syndicated content but remove this page from results.",
                    "Confirm this is intentional.", {"canonical": c}, p.url))
            elif target and (target.status or 0) >= 300:
                out.append(Finding(
                    "tech.canonical_to_non_200", "technical", "medium", "error", "high",
                    "Canonical points to a redirect or error page",
                    f"The canonical {c} returned HTTP {target.status}"
                    + (f" and redirects to {target.final_url}" if target.redirect_chain else "") + ".",
                    "Search engines may ignore a canonical that does not resolve to an indexable 200 page.",
                    "Point the canonical at the final, indexable URL.",
                    {"canonical": c, "canonical_status": target.status, "canonical_final": target.final_url}, p.url,
                    fix_type="canonical"))
            elif target and target.noindex:
                out.append(Finding(
                    "tech.canonical_to_noindex", "technical", "medium", "error", "high",
                    "Canonical points to a noindex page",
                    f"The canonical {c} is marked noindex.",
                    "Conflicting signals: this page says 'index that URL instead', but that URL says 'do not index'.",
                    "Point the canonical to an indexable page or remove the noindex.", {"canonical": c}, p.url,
                    fix_type="canonical"))
        link_header = p.headers.get("link", "")
        m = re.search(r"<([^>]+)>\s*;\s*rel=\"?canonical\"?", link_header)
        if m and m.group(1).rstrip("/") != c.rstrip("/"):
            out.append(Finding(
                "tech.canonical_header_mismatch", "technical", "medium", "error", "high",
                "HTTP Link canonical differs from HTML canonical",
                "The HTTP Link header and the HTML <link rel=canonical> name different URLs.",
                "Conflicting canonical signals may both be ignored.", "Make both canonicals identical.",
                {"header": m.group(1), "html": c}, p.url, fix_type="canonical"))
    return out


@rule
def indexability(ctx: SiteContext) -> list[Finding]:
    out = []
    home = ctx.by_url.get(ctx.start_url)
    for p in ctx.html_pages:
        if p.noindex:
            directives = (p.extracted or {}).get("meta_robots", []) + ([p.headers["x-robots-tag"]] if p.headers.get("x-robots-tag") else [])
            if p is home:
                out.append(Finding(
                    "tech.noindex_home", "technical", "critical", "error", "high", "Homepage is set to noindex",
                    "The homepage carries a noindex directive.",
                    "Search engines will drop the homepage from their index while this directive is present.",
                    "Remove the noindex directive if the homepage should appear in search results.",
                    {"directives": directives}, p.url, fix_type="robots_directive"))
            elif p.in_sitemap:
                out.append(Finding(
                    "tech.noindex_in_sitemap", "technical", "medium", "warning", "high", "Noindex page listed in sitemap",
                    "This page is in the XML sitemap but is marked noindex.",
                    "Sitemaps should list pages you want indexed; mixed signals waste crawl resources.",
                    "Remove it from the sitemap, or remove the noindex if it should be indexed.",
                    {"directives": directives}, p.url, fix_type="robots_directive"))
            else:
                out.append(Finding(
                    "tech.noindex", "technical", "info", "info", "high", "Page is noindex",
                    "This page asks search engines not to index it.", "Confirm this is intentional.",
                    "No action needed if intentional.", {"directives": directives}, p.url))
    for p in ctx.pages:
        if p.robots_blocked and p.in_sitemap:
            out.append(Finding(
                "tech.blocked_in_sitemap", "technical", "medium", "warning", "high",
                "Sitemap URL is blocked by robots.txt",
                "This URL is listed in the sitemap but robots.txt disallows crawling it.",
                "Search engines cannot crawl it, so the sitemap entry has no effect.",
                "Either allow crawling in robots.txt or remove it from the sitemap.", {}, p.url))
    return out


# --------------------------------------------------------------- sitemaps
@rule
def sitemaps(ctx: SiteContext) -> list[Finding]:
    out = []
    sm = ctx.sitemap or {}
    entries = sm.get("sitemaps", [])
    found = [e for e in entries if e.get("kind")]
    if not found:
        out.append(Finding(
            "tech.sitemap_missing", "technical", "low", "recommendation", "high", "No XML sitemap found",
            "No sitemap was referenced in robots.txt or found at /sitemap.xml or /sitemap_index.xml.",
            "Sitemaps help search engines discover pages, especially new or poorly linked ones.",
            "Publish an XML sitemap and reference it in robots.txt with a 'Sitemap:' line.",
            {"checked": [e["url"] for e in entries]}))
    for e in entries:
        for err in e.get("errors", []):
            out.append(Finding(
                "tech.sitemap_error", "technical", "medium", "error", "high", "Sitemap error",
                f"{e['url']}: {err}", "Invalid or unreachable sitemaps are ignored by search engines.",
                "Fix the sitemap so it returns HTTP 200 with valid XML under the protocol limits.",
                {"sitemap": e["url"], "status": e.get("status"), "error": err}, key=e["url"] + err[:40]))
    if found and not ctx.robots.sitemaps:
        out.append(Finding(
            "tech.sitemap_not_in_robots", "technical", "info", "recommendation", "high",
            "Sitemap not referenced in robots.txt",
            "A sitemap exists but robots.txt has no 'Sitemap:' line.",
            "Referencing the sitemap in robots.txt lets all crawlers discover it.",
            f"Add 'Sitemap: {found[0]['url']}' to robots.txt.", {"sitemap": found[0]["url"]}))
    for p in ctx.pages:
        if p.in_sitemap and p.redirect_chain:
            out.append(Finding(
                "tech.sitemap_redirect", "technical", "low", "warning", "high", "Sitemap lists a redirecting URL",
                f"The sitemap lists {p.url}, which redirects to {p.final_url}.",
                "Sitemaps should list final canonical URLs.", f"Replace it with {p.final_url}.",
                {"final_url": p.final_url}, p.url))
    return out


# --------------------------------------------------------------- headings, images, html basics
@rule
def headings(ctx: SiteContext) -> list[Finding]:
    out = []
    for p in ctx.indexable_pages:
        ex = p.extracted or {}
        hs = ex.get("headings", [])
        h1s = ex.get("h1s", [])
        if not h1s:
            out.append(Finding(
                "tech.h1_missing", "technical", "low", "warning", "high", "No H1 heading",
                "The page has no <h1> element.",
                "A clear main heading helps users and machines understand the page's topic.",
                "Add one descriptive H1 that states the page's main topic.",
                {"title": ex.get("title"), "first_headings": hs[:5]}, p.url, fix_type="h1"))
        elif len(h1s) > 1:
            out.append(Finding(
                "tech.h1_multiple", "technical", "info", "info", "high", "Multiple H1 headings",
                f"The page has {len(h1s)} H1 headings.",
                "This is valid HTML and is not a search penalty. A single H1 can make the main topic clearer.",
                "Optional: keep one H1 for the main topic and use H2s for sections.", {"h1s": h1s[:10]}, p.url))
        empty = [h for h in hs if not h["text"]]
        if empty:
            out.append(Finding(
                "tech.heading_empty", "technical", "low", "warning", "high", "Empty heading elements",
                f"{len(empty)} heading element(s) contain no text.",
                "Empty headings confuse screen readers and document outlines.",
                "Remove empty headings or add text.", {"count": len(empty)}, p.url))
        prev = 0
        for h in hs:
            if prev and h["level"] > prev + 1:
                out.append(Finding(
                    "tech.heading_skip", "technical", "info", "recommendation", "high", "Heading level skipped",
                    f"An H{h['level']} ('{h['text'][:60]}') follows an H{prev}.",
                    "Skipped levels are an accessibility issue (WCAG) and make outlines harder to parse; not a ranking penalty.",
                    "Use sequential heading levels.", {"after": f"h{prev}", "heading": h}, p.url))
                break
            prev = h["level"]
    return out


@rule
def images(ctx: SiteContext) -> list[Finding]:
    out = []
    for p in ctx.indexable_pages:
        missing = [i for i in (p.extracted or {}).get("images", []) if i.get("alt") is None and not i.get("decorative")]
        for img in missing[:30]:
            out.append(Finding(
                "tech.img_alt_missing", "technical", "low", "warning", "high", "Image missing alt attribute",
                f"An image has no alt attribute: {img['src'][:150]}",
                "Alt text is required for accessibility (WCAG 1.1.1) and helps search engines understand images. "
                "Purely decorative images should use alt=\"\".",
                "Add alt text that describes the image's content or purpose, or alt=\"\" if decorative.",
                {"src": img["src"], "context": img.get("context"), "wp_attachment_id": img.get("wp_attachment_id")},
                p.url, fix_type="image_alt", key=img["src"]))
    return out


@rule
def html_basics(ctx: SiteContext) -> list[Finding]:
    out = []
    for p in ctx.indexable_pages:
        ex = p.extracted or {}
        if not ex.get("lang"):
            out.append(Finding(
                "tech.lang_missing", "technical", "low", "warning", "high", "Missing lang attribute",
                "The <html> element has no lang attribute.",
                "The language attribute helps screen readers and search engines (WCAG 3.1.1).",
                "Add lang (e.g. <html lang=\"en\">) via your theme/template.", {}, p.url))
        if not ex.get("viewport"):
            out.append(Finding(
                "tech.viewport_missing", "technical", "medium", "warning", "high", "No mobile viewport meta tag",
                "The page has no <meta name=\"viewport\">.",
                "Without it, mobile browsers render a desktop layout; Google indexes mobile-first.",
                "Add <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">.", {}, p.url))
        if ex.get("mixed_content"):
            out.append(Finding(
                "tech.mixed_content", "technical", "medium", "error", "high", "Mixed content",
                f"This HTTPS page loads {len(ex['mixed_content'])} resource(s) over HTTP.",
                "Browsers block or warn about insecure sub-resources.",
                "Load all resources over HTTPS.", {"resources": ex["mixed_content"]}, p.url))
        if p.response_ms and p.response_ms > 3000:
            out.append(Finding(
                "tech.slow_response", "technical", "low", "warning", "low", "Slow server response",
                f"The HTML response took {p.response_ms} ms during this crawl.",
                "Slow responses hurt user experience and can reduce crawl rate. A single measurement can be noisy.",
                "Investigate caching and server performance; confirm with field data (e.g. Core Web Vitals).",
                {"response_ms": p.response_ms}, p.url))
        for h in ex.get("hreflang", []):
            if not BCP47.match(h.get("lang") or ""):
                out.append(Finding(
                    "tech.hreflang_invalid", "technical", "medium", "error", "high", "Invalid hreflang code",
                    f"hreflang='{h.get('lang')}' is not a valid language/region code.",
                    "Invalid hreflang values are ignored.", "Use ISO 639-1 language codes with optional ISO 3166-1 region.",
                    {"hreflang": h}, p.url, key=str(h.get("lang"))))
    return out


@rule
def duplicate_content(ctx: SiteContext) -> list[Finding]:
    out = []
    by_hash: dict[str, list] = defaultdict(list)
    for p in ctx.indexable_pages:
        h = (p.extracted or {}).get("content_hash")
        if h and (p.extracted or {}).get("word_count", 0) >= 50:
            by_hash[h].append(p)
    exact_dupe_urls = set()
    for pages in by_hash.values():
        if len(pages) > 1:
            urls = [p.url for p in pages]
            exact_dupe_urls.update(urls)
            for u in urls:
                out.append(Finding(
                    "tech.duplicate_content", "technical", "medium", "warning", "high", "Duplicate page content",
                    f"{len(urls)} indexable URLs have identical main content and no canonical consolidating them.",
                    "Search engines pick one version to show; the others compete with it and split signals.",
                    "Consolidate with a rel=canonical to the preferred URL, a 301 redirect, or differentiate the content.",
                    {"pages": urls[:20]}, u, fix_type="canonical"))
    pages = [p for p in ctx.indexable_pages if (p.extracted or {}).get("simhash") and p.url not in exact_dupe_urls]
    pages = pages[:400]
    for i, a in enumerate(pages):
        for b in pages[i + 1:]:
            if hamming(a.extracted["simhash"], b.extracted["simhash"]) <= 3:
                out.append(Finding(
                    "tech.near_duplicate", "technical", "low", "recommendation", "medium", "Near-duplicate content",
                    f"This page's main content is very similar to {b.url}.",
                    "Very similar pages may compete for the same queries.",
                    "Differentiate the pages or consolidate them.", {"similar_to": b.url}, a.url, key=b.url))
    return out


# --------------------------------------------------------------- structured data
REQUIRED_PROPS = {
    # Properties Google documents as *required* for rich-result eligibility (not for indexing).
    "Product": [("name",), ("offers", "review", "aggregateRating")],
    "Recipe": [("name",), ("image",)],
    "Event": [("name",), ("startDate",), ("location",)],
    "JobPosting": [("title",), ("description",), ("datePosted",), ("hiringOrganization",)],
    "FAQPage": [("mainEntity",)],
    "BreadcrumbList": [("itemListElement",)],
    "Review": [("itemReviewed",), ("reviewRating",), ("author",)],
    "VideoObject": [("name",), ("thumbnailUrl",), ("uploadDate",)],
    "LocalBusiness": [("name",), ("address",)],
}


def _nodes(data):
    if isinstance(data, list):
        for x in data:
            yield from _nodes(x)
    elif isinstance(data, dict):
        if "@graph" in data:
            yield from _nodes(data["@graph"])
        if "@type" in data:
            yield data


@rule
def structured_data(ctx: SiteContext) -> list[Finding]:
    out = []
    for p in ctx.html_pages:
        ex = p.extracted or {}
        for i, j in enumerate(ex.get("json_ld", [])):
            if not j.get("valid"):
                out.append(Finding(
                    "tech.jsonld_invalid", "technical", "high", "error", "high", "Invalid JSON-LD",
                    f"A JSON-LD block could not be parsed: {j.get('error')}.",
                    "Search engines ignore structured data that is not valid JSON.",
                    "Fix the JSON syntax (validate with a JSON-LD/Rich Results testing tool).",
                    {"error": j.get("error"), "snippet": j.get("raw", "")[:600]}, p.url, fix_type="json_ld", key=str(i)))
                continue
            if j.get("missing_context"):
                out.append(Finding(
                    "tech.jsonld_no_context", "technical", "medium", "warning", "high", "JSON-LD missing @context",
                    "A JSON-LD block has no @context, so its vocabulary is undefined.",
                    "Without \"@context\": \"https://schema.org\" consumers may not interpret the data.",
                    "Add \"@context\": \"https://schema.org\".", {"snippet": j.get("raw", "")[:400]}, p.url,
                    fix_type="json_ld", key=str(i)))
            for node in _nodes(j.get("data")):
                t = node.get("@type")
                t = t if isinstance(t, str) else (t[0] if isinstance(t, list) and t else "")
                for alternatives in REQUIRED_PROPS.get(t, []):
                    if not any(node.get(k) for k in alternatives):
                        out.append(Finding(
                            "tech.jsonld_missing_required", "technical", "low", "warning", "high",
                            f"{t} structured data missing '{' or '.join(alternatives)}'",
                            f"The {t} item lacks '{' or '.join(alternatives)}', which Google lists as required for "
                            f"{t} rich results.",
                            "The markup is still valid schema.org, but it is not eligible for that rich result type.",
                            f"Add '{alternatives[0]}' if the information is genuinely shown on the page.",
                            {"type": t, "missing": list(alternatives), "properties": sorted(node.keys())[:30]},
                            p.url, fix_type="json_ld", key=f"{t}:{alternatives[0]}"))
    home = ctx.by_url.get(ctx.start_url)
    if home and home.is_html:
        types = set((home.extracted or {}).get("schema_types", []))
        if not types & {"Organization", "LocalBusiness", "Corporation", "Person", "WebSite", "OnlineStore",
                        "Store", "Restaurant", "ProfessionalService", "MedicalBusiness", "LegalService"}:
            out.append(Finding(
                "tech.jsonld_org_missing", "technical", "low", "recommendation", "medium",
                "No Organization or WebSite structured data on the homepage",
                "The homepage has no Organization/LocalBusiness/WebSite schema.",
                "Organization markup (name, logo, url, sameAs) helps search and AI systems connect your site to "
                "your brand entity. It does not guarantee a knowledge panel.",
                "Add Organization (or LocalBusiness) JSON-LD using only facts shown on your site.",
                {"schema_types_found": sorted(types)}, home.url, fix_type="json_ld"))
    for p in ctx.indexable_pages:
        ex = p.extracted or {}
        if ex.get("is_article_like") and not set(ex.get("schema_types", [])) & {"Article", "BlogPosting", "NewsArticle", "TechArticle"}:
            out.append(Finding(
                "tech.jsonld_article_missing", "technical", "low", "recommendation", "medium",
                "Article page without Article structured data",
                "This looks like an article but has no Article/BlogPosting markup.",
                "Article markup clarifies headline, author and dates for search and AI systems.",
                "Add Article JSON-LD with headline, author, datePublished and dateModified from the page.",
                {"schema_types_found": ex.get("schema_types", [])}, p.url, fix_type="json_ld"))
    return out


# --------------------------------------------------------------- internal linking
@rule
def internal_linking(ctx: SiteContext) -> list[Finding]:
    out = []
    linked = {t for t, s in ctx.inlinks.items() if any(x["source"] != t for x in s)}
    for p in ctx.indexable_pages:
        if p.url == ctx.start_url:
            continue
        if p.url not in linked and p.final_url not in linked:
            if p.in_sitemap:
                out.append(Finding(
                    "tech.orphan_page", "technical", "medium", "warning", "medium", "Orphan page (no internal links found)",
                    "This page is in the sitemap, but no crawled page links to it.",
                    "Pages without internal links are harder to discover and receive little internal link equity.",
                    "Link to it from relevant pages (navigation, related content, hubs).",
                    {"in_sitemap": True, "note": "Based on crawled pages only."}, p.url, fix_type="internal_link_add"))
        elif len({x["source"] for x in ctx.inlinks.get(p.url, [])}) == 1 and p.depth >= 2:
            out.append(Finding(
                "tech.weakly_linked", "technical", "low", "recommendation", "medium", "Only one internal link to this page",
                "Only one crawled page links here.", "More contextual links help discovery and topical relevance.",
                "Add contextual links from related pages.",
                {"linked_from": [x["source"] for x in ctx.inlinks.get(p.url, [])][:5]}, p.url,
                fix_type="internal_link_add"))
    return out
