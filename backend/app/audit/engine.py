"""Deterministic audit engine.

Rules are pure functions over a ``SiteContext`` and return ``Finding`` objects. Each finding
carries the evidence it was derived from. Findings are classified as:

* error          — objectively confirmed (e.g. a link target returned 404 twice)
* warning        — likely problem that depends on context (e.g. duplicate titles)
* recommendation — improvement opportunity, not a defect
* info           — informational; explicitly *not* a problem (e.g. multiple H1s)

No rule claims a ranking penalty; "why it matters" texts describe mechanisms, not guarantees.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from typing import Any

SEVERITY_WEIGHT = {"critical": 25, "high": 10, "medium": 5, "low": 2, "info": 0}


@dataclass
class Finding:
    rule_id: str
    category: str  # technical | content | aeo | geo
    severity: str
    finding_type: str
    confidence: str
    title: str
    description: str
    why_it_matters: str
    recommendation: str
    evidence: dict[str, Any] = field(default_factory=dict)
    url: str | None = None
    fix_type: str | None = None
    key: str = ""  # extra discriminator for the fingerprint (e.g. the link target)

    def fingerprint(self, site_key: str) -> str:
        raw = "|".join([site_key, self.rule_id, self.url or "", self.key])
        return hashlib.sha256(raw.encode()).hexdigest()

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class PageData:
    url: str
    final_url: str
    status: int | None
    depth: int
    content_type: str
    headers: dict[str, str]
    redirect_chain: list[dict]
    extracted: dict | None
    error: str | None
    error_kind: str | None
    robots_blocked: bool
    confirmed_error: bool
    response_ms: int
    in_sitemap: bool = False

    @property
    def is_html(self) -> bool:
        return self.extracted is not None and not self.extracted.get("parse_error")

    @property
    def noindex(self) -> bool:
        ex = self.extracted or {}
        directives = " ".join(ex.get("meta_robots", [])).lower() + " " + self.headers.get("x-robots-tag", "").lower()
        return "noindex" in directives or "none" in directives.split()

    @property
    def canonical(self) -> str | None:
        tags = (self.extracted or {}).get("canonical_tags") or []
        return tags[0] if tags else None

    @property
    def canonicalized_elsewhere(self) -> bool:
        c = self.canonical
        return bool(c) and c.rstrip("/") != self.final_url.rstrip("/")

    @property
    def indexable(self) -> bool:
        return (self.status == 200 and self.is_html and not self.noindex and not self.robots_blocked
                and not self.canonicalized_elsewhere)


@dataclass
class SiteContext:
    start_url: str
    root_host: str
    pages: list[PageData]
    sitemap: dict  # {"sitemaps": [...], "urls": {url: {...}}, "errors": [...]}
    robots: Any  # app.crawler.robots.Robots
    robots_status: int | None
    robots_error: str | None
    inlinks: dict[str, list[dict]]
    llms_txt: dict | None = None
    limit_reached: bool = False

    def __post_init__(self) -> None:
        self.by_url: dict[str, PageData] = {}
        for p in self.pages:
            self.by_url[p.url] = p
            self.by_url.setdefault(p.final_url, p)

    @property
    def html_pages(self) -> list[PageData]:
        return [p for p in self.pages if p.status == 200 and p.is_html and p.final_url == p.url]

    @property
    def indexable_pages(self) -> list[PageData]:
        return [p for p in self.html_pages if p.indexable]


Rule = Callable[[SiteContext], list[Finding]]
_RULES: list[Rule] = []


def rule(fn: Rule) -> Rule:
    _RULES.append(fn)
    return fn


def run_rules(ctx: SiteContext) -> list[Finding]:
    from app.audit.rules import content, technical  # noqa: F401  (registers rules)

    findings: list[Finding] = []
    for r in _RULES:
        try:
            findings.extend(r(ctx))
        except Exception as exc:  # a broken rule must not fail the audit
            findings.append(Finding(
                rule_id="engine.rule_error", category="technical", severity="info", finding_type="info",
                confidence="high", title=f"Audit rule {r.__name__} could not run",
                description=f"Internal error: {type(exc).__name__}", why_it_matters="Some checks were skipped.",
                recommendation="No action needed; this is reported to the platform team.", key=r.__name__))
    return findings


def scores(ctx: SiteContext, findings: list[Finding]) -> dict[str, Any]:
    """Heuristic 0-100 scores per category.

    These are internal heuristics to track progress over time. They are NOT an industry
    standard and do not predict rankings or AI citations.
    """
    n = max(1, len(ctx.html_pages))
    out: dict[str, Any] = {}
    for cat in ("technical", "content", "aeo", "geo"):
        penalty = 0.0
        for f in findings:
            if f.category != cat:
                continue
            w = SEVERITY_WEIGHT.get(f.severity, 0)
            # Site-wide findings count fully, page-level ones are normalized by page count.
            penalty += w if f.url is None else w * min(1.0, 3.0 / n)
        out[cat] = max(0, round(100 - penalty))
    out["disclaimer"] = ("Scores are internal heuristics for tracking improvements over time. They are not an "
                         "industry standard and do not predict rankings, traffic or AI citations.")
    return out
