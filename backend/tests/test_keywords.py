import httpx
import respx

from app.core.config import get_settings
from tests.conftest import crawl_site, set_plan
from tests.fixtures.demo_site import demo_site


def _ok(result):
    return httpx.Response(200, json={"status_code": 20000, "tasks": [{"status_code": 20000, "result": result}]})


def test_measured_keywords_require_provider(alice, loopback):
    set_plan(alice.org_id, "pro")
    with demo_site() as site:
        res = crawl_site(alice, site.base)
    wid = res["website"]["id"]
    r = alice.post(f"/api/orgs/{alice.org_id}/websites/{wid}/keywords/research", {"seeds": ["pour over coffee"]})
    assert r.status_code == 503 and "never estimated by AI" in r.json()["detail"]


def test_dataforseo_contract_and_labelling(alice, loopback, monkeypatch):
    set_plan(alice.org_id, "pro")
    s = get_settings()
    monkeypatch.setattr(s, "dataforseo_login", "login")
    monkeypatch.setattr(s, "dataforseo_password", "pw")
    with demo_site() as site:
        res = crawl_site(alice, site.base)
    wid = res["website"]["id"]
    with respx.mock(base_url="https://api.dataforseo.com", assert_all_called=True) as mock:
        vol = mock.post("/v3/keywords_data/google_ads/search_volume/live").mock(return_value=_ok(
            [{"keyword": "pour over coffee", "search_volume": 2900, "cpc": 1.2, "competition": "LOW"}]))
        mock.post("/v3/dataforseo_labs/google/bulk_keyword_difficulty/live").mock(return_value=_ok(
            [{"items": [{"keyword": "pour over coffee", "keyword_difficulty": 34}]}]))
        mock.post("/v3/dataforseo_labs/google/keyword_ideas/live").mock(return_value=_ok(
            [{"items": [{"keyword": "how to make pour over coffee", "keyword_info": {"search_volume": 1000, "cpc": 0.5,
                                                                                    "competition_level": "LOW"},
                         "keyword_properties": {"keyword_difficulty": 20},
                         "search_intent_info": {"main_intent": "informational"}}]}]))
        r = alice.post(f"/api/orgs/{alice.org_id}/websites/{wid}/keywords/research",
                       {"seeds": ["pour over coffee"], "location": "Canada", "language": "en"})
        assert r.status_code == 200, r.text
        assert vol.calls[0].request.headers["authorization"].startswith("Basic ")
    rows = r.json()
    main = next(k for k in rows if k["keyword"] == "pour over coffee")
    assert main["search_volume"] == 2900 and main["difficulty"] == 34 and main["source"] == "measured"
    assert "DataForSEO" in main["data_provider"]
    # AI ideas never have metrics
    r = alice.post(f"/api/orgs/{alice.org_id}/websites/{wid}/keywords/ideas")
    assert r.status_code == 200
    for k in r.json():
        assert k["source"] == "ai_idea" and k["search_volume"] is None and k["difficulty"] is None
        assert "not measured" in k["notes"]
    r = alice.post(f"/api/orgs/{alice.org_id}/websites/{wid}/keywords/on-page")
    assert all(k["source"] == "on_page" and k["search_volume"] is None for k in r.json())


def test_rate_limiter():
    from app.core.ratelimit import hit

    results = [hit("test:abc", 3, 60) for _ in range(5)]
    assert results == [True, True, True, False, False]
