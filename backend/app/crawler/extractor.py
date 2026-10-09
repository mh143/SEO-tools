"""HTML extraction.

Produces a JSON-serializable dict of everything the audit rules and AI prompts need. Text that is
hidden from users (``hidden``, ``aria-hidden``, ``display:none``) is excluded from ``main_text`` and
counted separately: hidden text is a common vector for prompt injection aimed at AI tools.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any
from urllib.parse import urlsplit

import lxml.html
from lxml import etree

from app.crawler.urls import normalize_url, same_site

_WS = re.compile(r"\s+")
_HIDDEN_STYLE = re.compile(r"display\s*:\s*none|visibility\s*:\s*hidden", re.I)
_QUESTION_START = re.compile(
    r"^(what|why|how|when|where|who|which|can|does|do|is|are|should|will|could|would|did)\b", re.I
)
_STRIP_TAGS = ("script", "style", "noscript", "template", "svg", "iframe", "object", "embed", "canvas")


def _clean(s: str | None) -> str:
    return _WS.sub(" ", s or "").strip()


def _text(el) -> str:
    return _clean(el.text_content()) if el is not None else ""


def _is_hidden(el) -> bool:
    if el.get("hidden") is not None or el.get("aria-hidden") == "true":
        return True
    style = el.get("style")
    return bool(style and _HIDDEN_STYLE.search(style))


def simhash(text: str) -> str:
    words = re.findall(r"\w+", text.lower())
    shingles = [" ".join(words[i : i + 3]) for i in range(max(1, len(words) - 2))] if words else []
    v = [0] * 64
    for sh in shingles:
        h = int.from_bytes(hashlib.blake2b(sh.encode(), digest_size=8).digest(), "big")
        for i in range(64):
            v[i] += 1 if (h >> i) & 1 else -1
    out = 0
    for i in range(64):
        if v[i] > 0:
            out |= 1 << i
    return f"{out:016x}"


def hamming(a: str, b: str) -> int:
    return bin(int(a, 16) ^ int(b, 16)).count("1")


def _jsonld_types(node: Any, out: list[str]) -> None:
    if isinstance(node, dict):
        t = node.get("@type")
        if isinstance(t, str):
            out.append(t)
        elif isinstance(t, list):
            out.extend(x for x in t if isinstance(x, str))
        for k, v in node.items():
            if k != "@context":
                _jsonld_types(v, out)
    elif isinstance(node, list):
        for x in node:
            _jsonld_types(x, out)


def _jsonld_find(node: Any, key: str) -> list[Any]:
    found: list[Any] = []
    if isinstance(node, dict):
        for k, v in node.items():
            if k == key:
                found.append(v)
            found.extend(_jsonld_find(v, key))
    elif isinstance(node, list):
        for x in node:
            found.extend(_jsonld_find(x, key))
    return found


def extract(html: str, url: str, root_host: str) -> dict[str, Any]:
    out: dict[str, Any] = {}
    try:
        doc = lxml.html.document_fromstring(html.encode("utf-8", errors="replace") if isinstance(html, str) else html)
    except (etree.ParserError, ValueError):
        return {"parse_error": True}
    base_url = url
    base_el = doc.find(".//base[@href]")
    if base_el is not None:
        base_url = normalize_url(base_el.get("href"), url) or url

    html_el = doc if doc.tag == "html" else doc.find(".//html")
    out["lang"] = (html_el.get("lang") if html_el is not None else None) or None

    head = doc.find(".//head")
    scope = head if head is not None else doc
    out["title_tags"] = [_text(t) for t in doc.iter("title") if t.getparent() is not None and t.getparent().tag == "head"] or [
        _text(t) for t in scope.iter("title")
    ]
    out["title"] = out["title_tags"][0] if out["title_tags"] else None

    metas = list(doc.iter("meta"))
    def meta_by(attr: str, name: str) -> list[str]:
        return [_clean(m.get("content")) for m in metas if (m.get(attr) or "").lower() == name]

    out["meta_descriptions"] = meta_by("name", "description")
    out["meta_description"] = out["meta_descriptions"][0] if out["meta_descriptions"] else None
    out["meta_robots"] = meta_by("name", "robots") + meta_by("name", "googlebot")
    out["viewport"] = bool(meta_by("name", "viewport"))
    out["generator"] = (meta_by("name", "generator") or [None])[0]
    out["og"] = {(m.get("property") or "")[3:]: _clean(m.get("content")) for m in metas
                 if (m.get("property") or "").lower().startswith("og:")}
    out["meta_author"] = (meta_by("name", "author") or [None])[0]

    links_rel = list(doc.iter("link"))
    def rel_has(el, name):
        return name in (el.get("rel") or "").lower().split()

    out["canonical_tags"] = [normalize_url(el.get("href") or "", base_url) or (el.get("href") or "")
                             for el in links_rel if rel_has(el, "canonical")]
    out["canonical_raw"] = [el.get("href") for el in links_rel if rel_has(el, "canonical")]
    out["hreflang"] = [{"lang": el.get("hreflang"), "href": normalize_url(el.get("href") or "", base_url)}
                       for el in links_rel if rel_has(el, "alternate") and el.get("hreflang")]
    out["rel_author"] = [el.get("href") for el in links_rel if rel_has(el, "author")]
    out["wp_rest_link"] = next((normalize_url(el.get("href") or "", base_url) for el in links_rel
                                if rel_has(el, "alternate") and (el.get("type") or "") == "application/json"
                                and "/wp-json/" in (el.get("href") or "")), None)
    out["llms_link"] = None

    # JSON-LD
    jsonld = []
    for s in doc.iter("script"):
        if (s.get("type") or "").lower().strip() != "application/ld+json":
            continue
        raw = (s.text or "").strip()
        item: dict[str, Any] = {"raw": raw[:5000], "valid": False, "error": None, "types": []}
        try:
            data = json.loads(raw)
            item["valid"] = True
            types: list[str] = []
            _jsonld_types(data, types)
            item["types"] = sorted(set(types))
            item["data"] = data if len(raw) < 20000 else None
            if isinstance(data, dict) and "@context" not in data and "@graph" not in data:
                item["missing_context"] = True
        except json.JSONDecodeError as exc:
            item["error"] = f"{exc.msg} at line {exc.lineno} column {exc.colno}"
        jsonld.append(item)
    out["json_ld"] = jsonld
    out["schema_types"] = sorted({t for j in jsonld for t in j["types"]} | {
        (el.get("itemtype") or "").rsplit("/", 1)[-1] for el in doc.iter() if el.get("itemtype")} - {""})

    # Body (visible content)
    body = doc.find(".//body")
    if body is None:
        body = doc
    hidden_chars = 0
    for el in list(body.iter()):
        if not isinstance(el.tag, str):
            continue
        if el.tag in _STRIP_TAGS or _is_hidden(el):
            if el.tag not in ("script", "style") and _is_hidden(el):
                hidden_chars += len(_text(el))
            if el.getparent() is not None:
                el.drop_tree()  # keeps the element's tail text
    out["hidden_text_chars"] = hidden_chars

    headings = []
    for el in body.iter("h1", "h2", "h3", "h4", "h5", "h6"):
        headings.append({"level": int(el.tag[1]), "text": _text(el)[:300]})
    out["headings"] = headings
    out["h1s"] = [h["text"] for h in headings if h["level"] == 1]

    images = []
    for img in body.iter("img"):
        src = img.get("src") or img.get("data-src") or ""
        cls = img.get("class") or ""
        m = re.search(r"wp-image-(\d+)", cls)
        images.append({
            "src": normalize_url(src, base_url) or src[:500],
            "src_raw": src[:500],
            "alt": img.get("alt"),
            "decorative": img.get("role") == "presentation" or img.get("aria-hidden") == "true",
            "wp_attachment_id": int(m.group(1)) if m else None,
            "context": _clean(img.getparent().text_content() if img.getparent() is not None else "")[:200],
        })
    out["images"] = images[:500]

    links = []
    for a in body.iter("a"):
        href = (a.get("href") or "").strip()
        if not href or href.startswith(("#", "javascript:", "mailto:", "tel:", "data:")):
            continue
        n = normalize_url(href, base_url)
        if not n:
            continue
        links.append({
            "href": n,
            "text": _text(a)[:200],
            "nofollow": "nofollow" in (a.get("rel") or "").lower(),
            "internal": same_site(n, root_host),
        })
    out["links"] = links[:2000]
    out["internal_link_count"] = sum(1 for link in links if link["internal"])
    out["external_link_count"] = sum(1 for link in links if not link["internal"])

    # Main content region
    main = None
    for xp in (".//main", ".//*[@role='main']", ".//article"):
        main = body.find(xp)
        if main is not None:
            break
    region = main if main is not None else body
    if main is None:
        region = lxml.html.fromstring(lxml.html.tostring(body))
        for el in list(region.iter("nav", "header", "footer", "aside")):
            if el.getparent() is not None:
                el.drop_tree()
    main_text = _clean(region.text_content())
    out["main_text"] = main_text[:30000]
    out["word_count"] = len(re.findall(r"\b\w+\b", main_text))
    out["content_hash"] = hashlib.sha256(main_text.lower().encode()).hexdigest() if main_text else None
    out["simhash"] = simhash(main_text) if out["word_count"] >= 50 else None

    paragraphs = []
    for p in region.iter("p", "li"):
        t = _text(p)
        if len(t) < 20:
            continue
        paragraphs.append({"text": t[:1200], "has_link": p.find(".//a") is not None, "tag": p.tag})
        if len(paragraphs) >= 300:
            break
    out["paragraphs"] = paragraphs
    out["list_count"] = len(list(region.iter("ul", "ol")))
    out["table_count"] = len(list(region.iter("table")))

    # Question-style headings and the answer that follows them.
    qh = []
    for el in region.iter("h2", "h3", "h4"):
        t = _text(el)
        if not t or not (t.endswith("?") or _QUESTION_START.match(t)):
            continue
        answer = ""
        sib = el.getnext()
        while sib is not None and not (isinstance(sib.tag, str) and sib.tag in ("h1", "h2", "h3", "h4")):
            if isinstance(sib.tag, str):
                answer = _text(sib)
                if answer:
                    break
            sib = sib.getnext()
        qh.append({"question": t[:300], "level": int(el.tag[1]), "answer_preview": answer[:400],
                   "answer_words": len(answer.split())})
    out["question_headings"] = qh[:50]

    # Author & dates
    byline = None
    for el in body.iter():
        if not isinstance(el.tag, str):
            continue
        cls = f"{el.get('class') or ''} {el.get('rel') or ''} {el.get('itemprop') or ''}".lower()
        if re.search(r"\b(author|byline)\b", cls):
            t = _text(el)
            if 2 < len(t) < 120:
                byline = t
                break
    ld_data = [j.get("data") for j in jsonld if j.get("data") is not None]
    ld_authors = []
    for a in _jsonld_find(ld_data, "author"):
        for x in a if isinstance(a, list) else [a]:
            if isinstance(x, dict) and x.get("name"):
                ld_authors.append(str(x["name"])[:120])
            elif isinstance(x, str):
                ld_authors.append(x[:120])
    out["author"] = {"meta": out["meta_author"], "rel_author": out["rel_author"][:3], "schema": ld_authors[:3],
                     "byline": byline}
    out["has_author"] = bool(out["meta_author"] or out["rel_author"] or ld_authors or byline)

    published = [str(x) for x in _jsonld_find(ld_data, "datePublished") if isinstance(x, str)]
    modified = [str(x) for x in _jsonld_find(ld_data, "dateModified") if isinstance(x, str)]
    published += meta_by("property", "article:published_time")
    modified += meta_by("property", "article:modified_time") + meta_by("property", "og:updated_time")
    times = [t.get("datetime") for t in body.iter("time") if t.get("datetime")]
    out["dates"] = {"published": published[:3], "modified": modified[:3], "time_elements": times[:5]}

    # Mixed content (https page loading http subresources)
    mixed = []
    if url.startswith("https://"):
        for el in doc.iter("img", "script", "link", "iframe", "source", "video", "audio"):
            attr = "href" if el.tag == "link" else "src"
            v = el.get(attr) or ""
            if v.startswith("http://") and (el.tag != "link" or "stylesheet" in (el.get("rel") or "")):
                mixed.append(v[:300])
    out["mixed_content"] = mixed[:20]

    out["is_article_like"] = bool(
        {"Article", "BlogPosting", "NewsArticle", "TechArticle"} & set(out["schema_types"])
        or (out.get("og", {}).get("type") == "article")
        or (body.find(".//article") is not None and out["word_count"] >= 300)
    )
    out["is_home"] = urlsplit(url).path in ("", "/")
    return out
