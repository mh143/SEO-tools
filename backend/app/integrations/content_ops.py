"""Deterministic, minimal edits on stored HTML content (e.g. WordPress ``content.raw``).

Each function either returns the new content or raises ``ConnectorError``; nothing is guessed.
Inserted HTML is always sanitized with the allowlist from ``app.ai.tasks.sanitize_html``.
"""

from __future__ import annotations

import html as html_lib
import re
from urllib.parse import urljoin, urlsplit

from app.ai.tasks import sanitize_html
from app.integrations.base import ConnectorError

_TAG = re.compile(r"<[^>]+>")


def _text(s: str) -> str:
    return re.sub(r"\s+", " ", html_lib.unescape(_TAG.sub(" ", s))).strip().lower()


def _is_block_content(content: str) -> bool:
    return "<!-- wp:" in content


def _wrap(content: str, html: str) -> str:
    html = sanitize_html(html)
    if _is_block_content(content):
        return f"\n\n<!-- wp:html -->\n{html}\n<!-- /wp:html -->\n"
    return "\n" + html + "\n"


def insert_after_heading(content: str, heading_text: str, html: str) -> str:
    target = _text(heading_text)
    pattern = re.compile(r"<h([1-6])\b[^>]*>(.*?)</h\1>", re.I | re.S)
    matches = [m for m in pattern.finditer(content) if _text(m.group(2)) == target]
    if not matches:
        raise ConnectorError("The question heading was not found in the stored page content.")
    if len(matches) > 1:
        raise ConnectorError("The heading appears more than once; refusing an ambiguous edit.")
    end = matches[0].end()
    # In block content, insert after the heading block's closing comment if present.
    m_close = re.compile(r"\s*<!-- /wp:heading -->").match(content, end)
    if m_close:
        end = m_close.end()
    return content[:end] + _wrap(content, html) + content[end:]


def append(content: str, html: str) -> str:
    return content.rstrip() + "\n" + _wrap(content, html)


def _href_variants(href: str, base: str) -> set[str]:
    absolute = urljoin(base, href)
    p = urlsplit(absolute)
    path = p.path + (("?" + p.query) if p.query else "")
    v = {href, absolute, path}
    for x in list(v):
        v.add(x.rstrip("/") if x.endswith("/") and len(x) > 1 else x + "/")
    return {x for x in v if x}


def replace_href(content: str, old_href: str, new_href: str, base: str) -> str:
    if not new_href or not re.match(r"^https?://|^/", new_href):
        raise ConnectorError("The new link target must be an absolute URL or a site path.")
    variants = _href_variants(old_href, base)
    count = 0

    def repl(m: re.Match) -> str:
        nonlocal count
        quote, value = m.group(1), m.group(2)
        if html_lib.unescape(value) in variants:
            count += 1
            return f"href={quote}{html_lib.escape(new_href, quote=True)}{quote}"
        return m.group(0)

    out = re.sub(r"href=([\"'])(.*?)\1", repl, content)
    if count == 0:
        raise ConnectorError("No link to the old URL was found in the stored content (it may come from the theme or a widget).")
    return out


def link_phrase(content: str, phrase: str, href: str) -> str:
    """Wrap the first occurrence of ``phrase`` that is in text (not in a tag or an existing link)."""
    if not phrase.strip():
        raise ConnectorError("A phrase to link is required.")
    parts = re.split(r"(<[^>]+>)", content)
    in_link = 0
    rx = re.compile(r"\b" + r"\s+".join(map(re.escape, phrase.split())) + r"\b", re.I)
    for i, part in enumerate(parts):
        if part.startswith("<"):
            t = part.lower()
            if re.match(r"<a\b", t):
                in_link += 1
            elif t.startswith("</a"):
                in_link = max(0, in_link - 1)
            continue
        if in_link or part.startswith("<!--"):
            continue
        m = rx.search(part)
        if m:
            link = f'<a href="{html_lib.escape(href, quote=True)}">{m.group(0)}</a>'
            parts[i] = part[: m.start()] + link + part[m.end():]
            return "".join(parts)
    raise ConnectorError("The phrase was not found as plain text in the stored content.")


def set_img_alt(content: str, src: str, alt: str, base: str) -> tuple[str, int]:
    variants = _href_variants(src, base)
    count = 0

    def repl(m: re.Match) -> str:
        nonlocal count
        tag = m.group(0)
        sm = re.search(r"\ssrc=([\"'])(.*?)\1", tag)
        if not sm or html_lib.unescape(sm.group(2)) not in variants:
            return tag
        count += 1
        safe_alt = html_lib.escape(alt, quote=True)
        if re.search(r"\salt=([\"']).*?\1", tag):
            return re.sub(r"\salt=([\"']).*?\1", f' alt="{safe_alt}"', tag, count=1)
        return re.sub(r"<img\b", f'<img alt="{safe_alt}"', tag, count=1)

    out = re.sub(r"<img\b[^>]*>", repl, content, flags=re.I)
    if count == 0:
        raise ConnectorError("The image was not found in the stored content (it may come from the theme).")
    return out, count
