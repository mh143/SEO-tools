"""Plan catalogue.

Prices (CAD) and limits are *pricing hypotheses* and are intentionally kept in one place so they
can be tuned without code changes elsewhere. Override with PLANS_OVERRIDE_JSON if needed.
Entitlements are always enforced server-side (see app.billing.entitlements).
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field


@dataclass(frozen=True)
class Plan:
    key: str
    name: str
    price_cad_month: int
    max_websites: int
    max_pages_per_crawl: int
    max_depth: int
    crawls_per_month: int
    schedules: tuple[str, ...]  # allowed schedule frequencies
    js_rendering: bool
    rendered_pages_per_month: int
    ai_requests_per_month: int
    keyword_requests_per_month: int
    publish_ops_per_month: int
    team_seats: int
    reports_white_label: bool
    features: tuple[str, ...] = field(default_factory=tuple)
    stripe_price_env: str | None = None

    def public(self) -> dict:
        d = asdict(self)
        d.pop("stripe_price_env", None)
        return d


PLANS: dict[str, Plan] = {
    "free": Plan(
        key="free", name="Free", price_cad_month=0, max_websites=1, max_pages_per_crawl=25, max_depth=2,
        crawls_per_month=3, schedules=("none",), js_rendering=False, rendered_pages_per_month=0,
        ai_requests_per_month=10, keyword_requests_per_month=0, publish_ops_per_month=0, team_seats=1,
        reports_white_label=False,
        features=("Technical SEO audit (25 pages)", "AEO & GEO checks", "10 AI fix drafts / month", "CSV & JSON export"),
    ),
    "starter": Plan(
        key="starter", name="Starter", price_cad_month=39, max_websites=1, max_pages_per_crawl=250, max_depth=4,
        crawls_per_month=10, schedules=("none", "monthly", "weekly"), js_rendering=False,
        rendered_pages_per_month=0, ai_requests_per_month=100, keyword_requests_per_month=50,
        publish_ops_per_month=50, team_seats=2, reports_white_label=False,
        features=("1 website, 250 pages per crawl", "Weekly or monthly scheduled audits", "100 AI fix drafts / month",
                  "Direct publishing (supported platforms)", "Keyword data (when provider configured)"),
        stripe_price_env="stripe_price_starter",
    ),
    "pro": Plan(
        key="pro", name="Pro", price_cad_month=99, max_websites=5, max_pages_per_crawl=1000, max_depth=6,
        crawls_per_month=60, schedules=("none", "monthly", "weekly", "daily"), js_rendering=True,
        rendered_pages_per_month=1000, ai_requests_per_month=500, keyword_requests_per_month=300,
        publish_ops_per_month=500, team_seats=5, reports_white_label=False,
        features=("5 websites, 1,000 pages per crawl", "Daily monitoring & regression alerts", "JavaScript rendering",
                  "500 AI fix drafts / month", "5 team members"),
        stripe_price_env="stripe_price_pro",
    ),
    "agency": Plan(
        key="agency", name="Agency", price_cad_month=249, max_websites=25, max_pages_per_crawl=2000, max_depth=8,
        crawls_per_month=300, schedules=("none", "monthly", "weekly", "daily"), js_rendering=True,
        rendered_pages_per_month=5000, ai_requests_per_month=2000, keyword_requests_per_month=1500,
        publish_ops_per_month=2500, team_seats=20, reports_white_label=True,
        features=("25 websites, 2,000 pages per crawl", "White-label reports", "20 team members",
                  "2,000 AI fix drafts / month", "Priority crawl queue"),
        stripe_price_env="stripe_price_agency",
    ),
}

_override = os.environ.get("PLANS_OVERRIDE_JSON")
if _override:
    for key, values in json.loads(_override).items():
        base = asdict(PLANS[key]) if key in PLANS else {}
        base.update(values)
        for t in ("schedules", "features"):
            if t in base:
                base[t] = tuple(base[t])
        PLANS[key] = Plan(**base)


def get_plan(key: str | None) -> Plan:
    return PLANS.get(key or "free", PLANS["free"])
