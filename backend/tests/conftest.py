from __future__ import annotations

import os

os.environ["APP_ENV"] = "test"
# Tests DROP and recreate the schema: they only ever use TEST_DATABASE_URL, never DATABASE_URL.
_test_db = os.environ.get("TEST_DATABASE_URL", "postgresql+psycopg://seo:seo@localhost:5432/seo_test")
if "test" not in _test_db.rsplit("/", 1)[-1]:
    raise RuntimeError("TEST_DATABASE_URL must point to a database whose name contains 'test'.")
os.environ["DATABASE_URL"] = _test_db
os.environ.setdefault("TASK_BACKEND", "inline")
os.environ.setdefault("BILLING_MODE", "dev")
os.environ.setdefault("AI_PROVIDER", "mock")
os.environ.setdefault("SSRF_DEV_ALLOW_HOSTS", "")
os.environ.setdefault("CRAWLER_DELAY_SECONDS", "0")

import pytest  # noqa: E402
from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402

from alembic import command  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.core.db import Base, get_engine, session_factory  # noqa: E402

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture(scope="session", autouse=True)
def _migrate():
    engine = get_engine()
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public;"))
    cfg = Config(os.path.join(BACKEND_DIR, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(BACKEND_DIR, "alembic"))
    command.upgrade(cfg, "head")
    yield


@pytest.fixture(autouse=True)
def _clean_db():
    yield
    engine = get_engine()
    tables = ", ".join(f'"{t.name}"' for t in Base.metadata.sorted_tables)
    with engine.begin() as conn:
        conn.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))


@pytest.fixture
def db():
    s = session_factory()()
    try:
        yield s
    finally:
        s.close()


@pytest.fixture
def settings():
    return get_settings()


class ApiClient:
    """TestClient wrapper that keeps the session cookie and echoes the CSRF token."""

    def __init__(self, app):
        self.c = TestClient(app)
        self.csrf: str | None = None
        self.user: dict | None = None

    def _h(self, headers=None):
        h = dict(headers or {})
        if self.csrf:
            h["X-CSRF-Token"] = self.csrf
        return h

    def get(self, url, **kw):
        return self.c.get(url, headers=self._h(kw.pop("headers", None)), **kw)

    def post(self, url, json=None, **kw):
        return self.c.post(url, json=json, headers=self._h(kw.pop("headers", None)), **kw)

    def patch(self, url, json=None, **kw):
        return self.c.patch(url, json=json, headers=self._h(kw.pop("headers", None)), **kw)

    def put(self, url, json=None, **kw):
        return self.c.put(url, json=json, headers=self._h(kw.pop("headers", None)), **kw)

    def delete(self, url, **kw):
        return self.c.delete(url, headers=self._h(kw.pop("headers", None)), **kw)

    def signup(self, email, password="correct-horse-battery", org_name="Acme"):
        r = self.post("/api/auth/signup", {"email": email, "password": password, "name": "T", "org_name": org_name})
        assert r.status_code == 200, r.text
        self.csrf = r.json()["csrf_token"]
        self.user = r.json()["user"]
        return self

    @property
    def org_id(self) -> str:
        return self.user["organizations"][0]["id"]


@pytest.fixture
def app():
    from app.main import create_app

    return create_app()


@pytest.fixture
def client_factory(app):
    def make():
        return ApiClient(app)

    return make


@pytest.fixture
def alice(client_factory):
    return client_factory().signup("alice@example.com", org_name="Alice Co")


@pytest.fixture
def bob(client_factory):
    return client_factory().signup("bob@example.com", org_name="Bob Co")


@pytest.fixture
def loopback(monkeypatch):
    monkeypatch.setattr(get_settings(), "ssrf_dev_allow_hosts", "127.0.0.1")


def set_plan(org_id: str, plan_key: str) -> None:
    import uuid

    from sqlalchemy import select

    from app.core.db import db_session
    from app.models import Organization, Subscription

    with db_session() as s:
        sub = s.scalar(select(Subscription).where(Subscription.org_id == uuid.UUID(org_id)))
        sub.plan_key, sub.status = plan_key, "active"
        s.get(Organization, uuid.UUID(org_id)).plan_key = plan_key


def crawl_site(client, base_url: str, **crawl_body) -> dict:
    from app.tasks.dispatch import wait_inline

    org = client.org_id
    sites = client.get(f"/api/orgs/{org}/websites").json()
    site = next((s for s in sites if s["root_url"].startswith(base_url)), None)
    if site is None:
        r = client.post(f"/api/orgs/{org}/websites", {"url": base_url + "/", "name": "Fixture"})
        assert r.status_code == 200, r.text
        site = r.json()
    r = client.post(f"/api/orgs/{org}/websites/{site['id']}/crawls", crawl_body or None)
    assert r.status_code == 200, r.text
    wait_inline(120)
    crawl = client.get(f"/api/orgs/{org}/crawls/{r.json()['id']}").json()
    return {"website": site, "crawl": crawl}
