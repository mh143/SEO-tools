import pytest

from app.audit.engine import run_rules
from app.core.config import get_settings
from app.crawler.crawler import CrawlConfig, crawl
from app.crawler.extractor import extract
from app.crawler.robots import parse_robots
from app.services.crawl_service import build_context
from tests.fixtures.demo_site import INJECTION, demo_site


@pytest.fixture(autouse=True)
def allow_loopback(monkeypatch):
    monkeypatch.setattr(get_settings(), "ssrf_dev_allow_hosts", "127.0.0.1")


async def _crawl(site, **kw):
    return await crawl(CrawlConfig(start_url=site.base + "/", max_pages=kw.get("max_pages", 50),
                                   max_depth=kw.get("max_depth", 5), delay=0))


async def test_crawl_respects_robots_and_limits():
    with demo_site() as site:
        out = await _crawl(site)
        assert out.fatal_error is None
        assert "/private/secret" not in site.hits
        urls = set(out.pages)
        assert site.base + "/guides/pour-over" in urls
        assert site.base + "/orphan" in urls  # discovered via sitemap
        assert out.robots.sitemaps
        # page limit
        out2 = await _crawl(site, max_pages=2)
        assert len([p for p in out2.pages.values() if p.fetch]) <= 2
        assert out2.limit_reached


async def test_findings_have_evidence():
    with demo_site() as site:
        out = await _crawl(site)
    findings = run_rules(build_context(out))
    by_rule = {}
    for f in findings:
        by_rule.setdefault(f.rule_id, []).append(f)

    # Confirmed broken link with evidence of source and status
    broken = by_rule["tech.broken_internal_link"]
    assert any(f.evidence["target"].endswith("/missing") and f.evidence["target_status"] == 404 for f in broken)
    assert all(f.finding_type == "error" for f in broken)
    # Redirect chain (2 hops) and link to redirect
    chain = by_rule["tech.redirect_chain"][0]
    assert len(chain.evidence["chain"]) == 2
    assert "tech.link_to_redirect" in by_rule
    # Invalid JSON-LD is an error with the parser message
    bad = by_rule["tech.jsonld_invalid"][0]
    assert bad.finding_type == "error" and bad.evidence["error"]
    # Duplicate titles across home and shop
    dup = by_rule["tech.title_duplicate"]
    assert {f.url for f in dup} == {site.base + "/", site.base + "/shop"}
    # Multiple H1 is info, not an error
    multi = by_rule["tech.h1_multiple"][0]
    assert multi.finding_type == "info" and multi.severity == "info"
    # Missing alt only for image without alt attribute; alt="" is decorative and fine
    alts = by_rule["tech.img_alt_missing"]
    assert [f.evidence["src"].rsplit("/", 1)[-1] for f in alts] == ["kettle.jpg"]
    # noindex page in sitemap is a warning
    assert by_rule["tech.noindex_in_sitemap"][0].url == site.base + "/about"
    # Orphan page from sitemap
    assert any(f.url == site.base + "/orphan" for f in by_rule["tech.orphan_page"])
    # Missing lang
    assert any(f.url == site.base + "/contact" for f in by_rule["tech.lang_missing"])
    # AEO: unanswered question heading
    assert any("grind size" in f.evidence["question"] for f in by_rule["aeo.question_unanswered"])
    # GEO: unsupported statistic, missing author, stale date
    assert any("87%" in s for f in by_rule["geo.unsupported_claims"] for s in f.evidence["sentences"])
    assert "geo.author_missing" in by_rule
    assert "geo.ai_crawlers_blocked" in by_rule
    assert "GPTBot" in by_rule["geo.ai_crawlers_blocked"][0].evidence["blocked"]
    # Heading skip is a recommendation
    assert by_rule["tech.heading_skip"][0].finding_type == "recommendation"
    # Every finding carries evidence or is site-level with explanation
    for f in findings:
        assert f.title and f.why_it_matters and f.recommendation
        assert f.severity in ("critical", "high", "medium", "low", "info")


def test_hidden_text_excluded_from_main_text():
    ex = extract(INJECTION, "https://example.com/widgets", "example.com")
    assert "ignore all previous instructions" not in ex["main_text"].lower()
    assert ex["hidden_text_chars"] > 0


def test_robots_wildcards_and_precedence():
    r = parse_robots("User-agent: *\nDisallow: /*.pdf$\nDisallow: /shop\nAllow: /shop/public\n\nUser-agent: GPTBot\nDisallow: /\n")
    assert not r.is_allowed("https://x.com/file.pdf")
    assert r.is_allowed("https://x.com/file.pdf?x=1")
    assert not r.is_allowed("https://x.com/shop/cart")
    assert r.is_allowed("https://x.com/shop/public/item")
    assert not r.is_allowed("https://x.com/", "GPTBot")
    assert r.is_allowed("https://x.com/", "RankLensBot")
    assert r.explicitly_blocks_root("GPTBot")


async def test_robots_server_error_means_disallow_all():
    from tests.fixtures.site import FixtureSite, page

    with FixtureSite({"/": (200, {}, page("Home", "<p>hi</p>")), "/robots.txt": (503, {}, "down")}) as site:
        out = await _crawl(site)
    assert out.robots.disallow_all
    assert all(p.robots_blocked for p in out.pages.values())
    findings = run_rules(build_context(out))
    assert any(f.rule_id == "tech.robots_unreachable" and f.severity == "critical" for f in findings)


async def test_xxe_in_sitemap_not_resolved():
    from tests.fixtures.site import FixtureSite, page

    xxe = """<?xml version="1.0"?><!DOCTYPE x [<!ENTITY e SYSTEM "file:///etc/passwd">]>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"><url><loc>&e;</loc></url></urlset>"""
    with FixtureSite({"/": (200, {}, page("Home", "<p>hi</p>")), "/sitemap.xml": (200, {}, xxe)}) as site:
        out = await _crawl(site)
    assert not any("root:" in u for u in out.sitemap.urls)
