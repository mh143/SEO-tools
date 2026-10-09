# RankLens — Technical SEO, AEO & GEO audit platform

A subscription SaaS that audits any public website for **technical SEO**, **Answer Engine Optimization (AEO)**
and **Generative Engine Optimization (GEO) readiness**, shows the evidence behind every finding, drafts
validated fixes (rule-based and AI), lets authorized users approve and publish supported fixes to
WordPress without a plugin, and **independently verifies** every change on the live site.

> "RankLens" is a working name; it is configured via `APP_NAME`/UI text.

* No ranking, traffic or AI-citation outcome is ever promised. Scores are internal heuristics and are labelled as such.
* Keyword volumes/difficulty come only from a named data provider (DataForSEO). AI keyword ideas are labelled and carry no metrics.
* A fix is `verified` only when a fresh fetch of the live page shows the change — never because an API accepted a request.

## Status at a glance

| Area | Status |
|---|---|
| Public quick audit (URL only, no account) | ✅ working |
| Accounts, organizations, roles, invitations, audit log | ✅ working |
| SSRF-safe crawler, robots.txt, sitemaps, redirect/error confirmation | ✅ working |
| Technical / content / AEO / GEO rule engine with evidence | ✅ working (70+ checks) |
| Audit dashboard, issue details, page details, exports (CSV/JSON/MD/HTML) | ✅ working |
| Fix lifecycle (draft → approve → publish/apply → verify → rollback) | ✅ working |
| Rule-based fixes (canonical, redirects, link updates, internal links, robots) | ✅ working |
| AI fixes & content analysis (Anthropic Claude) | 🔑 requires `ANTHROPIC_API_KEY` (mock provider for tests/demo) |
| WordPress publishing (Application Passwords) | ✅ implemented & contract-tested; 🔑 needs a real WordPress 5.6+ site over HTTPS |
| Measured keyword data (DataForSEO) | 🔑 requires DataForSEO credentials (contract-tested with mocks) |
| Stripe billing (checkout, portal, webhooks, cancellation, failed payments) | 🔑 requires Stripe keys; dev billing mode (clearly labelled, simulated) works without |
| Scheduled audits, regression detection, in-app alerts | ✅ working (Celery beat) — email alerts need SMTP |
| JavaScript rendering (Playwright, SSRF-safe request routing) | ✅ working when Chromium is installed (`RENDERING_ENABLED=true`) |
| Admin dashboard | ✅ working |
| Other platforms (Webflow, Shopify, Wix), Google Search Console, brand-mention data | ❌ not implemented — see `docs/KNOWN_LIMITATIONS.md` |

## Repository layout

```
backend/    FastAPI app + Celery workers (Python 3.11+), Alembic migrations, pytest suite
frontend/   Next.js 14 (App Router, TypeScript, Tailwind), Playwright e2e tests
deploy/     nginx edge proxy config
scripts/    e2e.sh (starts the whole stack locally and runs Playwright)
docs/       ARCHITECTURE, API, INTEGRATIONS, SECURITY, DEPLOYMENT, KNOWN_LIMITATIONS
```

## Quick start (local, without Docker)

Prerequisites: Python 3.11+, Node.js 20+, PostgreSQL 14+ (16 tested), Redis 6+.

```bash
# 1. Database
sudo -u postgres psql -c "create user seo with password 'seo' createdb;"
sudo -u postgres createdb -O seo seo
sudo -u postgres createdb -O seo seo_test        # used by the test suite only

# 2. Configuration
cp .env.example .env                              # edit values; defaults work for local dev

# 3. Backend
cd backend
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"                           # add ",render" for JavaScript rendering (Playwright)
alembic upgrade head
uvicorn app.main:app --reload --port 8000         # API on :8000, docs at /api/docs

# 4. Workers (separate terminals, same venv)
celery -A app.tasks.celery_app worker -Q default,crawl --loglevel=INFO
celery -A app.tasks.celery_app beat --loglevel=INFO

# 5. Frontend
cd ../frontend
npm ci
BACKEND_URL=http://127.0.0.1:8000 npm run dev     # http://localhost:3000
```

Without Celery you can set `TASK_BACKEND=inline` (jobs run in API threads — development only).

To audit a site running on your own machine (e.g. a local WordPress), you must explicitly allow it with
`SSRF_DEV_ALLOW_HOSTS=127.0.0.1` — this is refused when `APP_ENV=production`.

## Quick start (Docker Compose)

```bash
cp .env.example .env     # set PUBLIC_APP_URL=http://localhost:8080
docker compose up --build
# open http://localhost:8080
```

The compose file was written for this project but could **not** be executed in the build environment
(no Docker daemon was available); the same services were verified using locally installed PostgreSQL,
Redis, Celery, uvicorn and Next.js.

## Tests

```bash
# Backend: unit, integration, security, contract tests (uses TEST_DATABASE_URL, default .../seo_test;
# the schema is dropped and recreated, and the DB name must contain "test")
cd backend && . .venv/bin/activate
ruff check app tests
python -m pytest -q

# Frontend: types, lint, production build
cd frontend && npx tsc --noEmit && npx next lint && npx next build

# End-to-end (starts fixture site, fake WordPress, API, web; runs Playwright in Chromium)
./scripts/e2e.sh
```

Results in the build environment: **121 backend tests passing**, **4/4 Playwright e2e tests passing**,
type-check/lint/build clean. Some tests use local test doubles (a fixture website and a fake WordPress
implementing the documented REST contract) because outbound internet was blocked.

## Environment variables

All variables are documented in [`.env.example`](.env.example). Required in production:
`APP_ENV=production`, `SECRET_KEY`, `ENCRYPTION_KEYS`, `COOKIE_SECURE=true`, `DATABASE_URL`, `REDIS_URL`,
`PUBLIC_APP_URL`, `BILLING_MODE=stripe` + Stripe keys/price ids/webhook secret. The app refuses to boot in
production with dev-only settings (dev billing, mock AI, SSRF dev allowlist, insecure cookies, missing keys).

## External accounts & credentials

| Service | Needed for | Variables |
|---|---|---|
| Anthropic | AI fix drafts, content analysis, keyword ideas | `AI_PROVIDER=anthropic`, `ANTHROPIC_API_KEY` (`ANTHROPIC_MODEL` defaults to `claude-opus-5-5`) |
| Stripe | Paid plans | `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`, `STRIPE_PRICE_STARTER/PRO/AGENCY` (monthly CAD recurring prices) |
| DataForSEO | Measured search volume / difficulty | `DATAFORSEO_LOGIN`, `DATAFORSEO_PASSWORD` |
| WordPress site (customer-owned) | Direct publishing | none server-side; customers authorize via Application Passwords |
| SMTP provider | Email alerts (optional) | `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM` |

More: [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) · [docs/SECURITY.md](docs/SECURITY.md) ·
[docs/INTEGRATIONS.md](docs/INTEGRATIONS.md) · [docs/KNOWN_LIMITATIONS.md](docs/KNOWN_LIMITATIONS.md).

**Not production-certified.** The code has extensive automated security tests, but it has not had an
independent security review or penetration test, and several integrations have only been tested against
contract test doubles. See the known-limitations document before launching.
