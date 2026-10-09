from __future__ import annotations

from urllib.parse import parse_qsl, quote, unquote, urlencode, urljoin, urlsplit, urlunsplit

TRACKING_PARAMS = {"utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content", "gclid", "fbclid", "msclkid"}
SKIP_EXTENSIONS = (
    ".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".ico", ".pdf", ".zip", ".gz", ".mp4", ".mp3", ".avi",
    ".mov", ".woff", ".woff2", ".ttf", ".eot", ".css", ".js", ".xml", ".json", ".doc", ".docx", ".xls", ".xlsx",
    ".ppt", ".pptx", ".dmg", ".exe", ".rar", ".7z", ".tar", ".avif", ".bmp",
)


def normalize_url(url: str, base: str | None = None) -> str | None:
    """Absolute, fragment-free, lower-cased scheme/host, default port removed, tracking params dropped."""
    if base:
        url = urljoin(base, url.strip())
    try:
        p = urlsplit(url.strip())
    except ValueError:
        return None
    if p.scheme.lower() not in ("http", "https") or not p.hostname:
        return None
    scheme = p.scheme.lower()
    host = p.hostname.lower().rstrip(".")
    try:
        port = p.port
    except ValueError:
        return None
    netloc = host if port is None or (scheme, port) in (("http", 80), ("https", 443)) else f"{host}:{port}"
    path = quote(unquote(p.path or "/"), safe="/%:@!$&'()*+,;=-._~")
    query = urlencode([(k, v) for k, v in parse_qsl(p.query, keep_blank_values=True) if k.lower() not in TRACKING_PARAMS])
    return urlunsplit((scheme, netloc, path, query, ""))


def host_of(url: str) -> str:
    return (urlsplit(url).hostname or "").lower()


def same_site(url: str, root_host: str) -> bool:
    """Same host, treating www. and the bare domain as the same site."""
    h = host_of(url)
    strip = lambda x: x[4:] if x.startswith("www.") else x  # noqa: E731
    return strip(h) == strip(root_host.lower())


def looks_like_page(url: str) -> bool:
    path = urlsplit(url).path.lower()
    return not path.endswith(SKIP_EXTENSIONS)


def origin(url: str) -> str:
    p = urlsplit(url)
    return f"{p.scheme}://{p.netloc}"
