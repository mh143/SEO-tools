# Tasks

Legend: ✅ done & tested · 🔑 implemented, needs external credentials to use for real · ⏳ not done

## Phase 1 — Foundation, authentication, database, UI framework ✅
- ✅ Repository inspection (empty repo) and implementation plan
- ✅ FastAPI app factory, settings with production safety validation
- ✅ SQLAlchemy models for all entities + Alembic migration `0001`
- ✅ Argon2 password hashing, server-side sessions (hashed tokens), CSRF double-submit, session revocation
- ✅ Organizations, memberships, roles (owner/admin/editor/viewer), invitations, last-owner protection
- ✅ Audit log, rate limiting (Redis with local fallback)
- ✅ Next.js + Tailwind UI shell, API client with CSRF
- Tests: `test_auth.py`, `test_orgs.py`

## Phase 2 — Secure crawler, extraction, deterministic rules ✅
- ✅ SSRF protection: scheme/port/credential checks, IP classification, connect-time DNS pinning (rebinding-safe),
  per-hop redirect validation, size caps, gzip-bomb caps, timeouts, proxies ignored
- ✅ robots.txt (RFC 9309 semantics), sitemap discovery (index, gzip, XXE-safe), llms.txt presence check
- ✅ HTML extraction (hidden text removed from AI-visible content)
- ✅ BFS crawler with page/depth/concurrency limits, robots respect, error confirmation by retry
- ✅ 70+ checks across technical, content, AEO and GEO, classified error/warning/recommendation/info
- ✅ Optional Playwright rendering with every request routed through the SSRF-safe fetcher
- Tests: `test_ssrf.py` (50 cases), `test_crawl_audit.py`, `test_renderer.py`

## Phase 3 — Audit dashboard & issue details ✅
- ✅ Websites CRUD, crawl start/cancel/progress, issue filters/grouping/pagination, page details, snapshots
- ✅ Public quick audit (anonymous, rate limited, token-scoped, expiring)
- ✅ UI: landing, pricing, public audit, overview, websites, crawl dashboard (loading/empty/error/partial states), issue detail, page detail
- Tests: `test_api_audit.py`, e2e `public quick audit`

## Phase 4 — AI fixes, content suggestions, exports ✅ / 🔑
- ✅ Provider abstraction (Anthropic structured outputs, mock for tests, none)
- ✅ Prompt-injection defences, strict output validation (allowed fields, markup, length, "no invented facts")
- ✅ Rule-based fix generators; AI generators for title, description, H1, alt, answers, FAQ, JSON-LD, content plan
- ✅ Fix editor with before/after diff, manual editing with validation
- ✅ Exports: audit CSV/JSON/Markdown/HTML, fix JSON/CSV/instructions
- ✅ Keywords: DataForSEO (measured), AI ideas (labelled, no metrics), on-page terms
- 🔑 Real AI output requires `ANTHROPIC_API_KEY`; real keyword data requires DataForSEO
- Tests: `test_ai_validation.py`, `test_fixes.py`, `test_keywords.py`

## Phase 5 — Tenancy, plans, usage, Stripe ✅ / 🔑
- ✅ Org-scoped access on every route (404 for non-members), IDOR tests across all resource types
- ✅ Configurable plans (CAD pricing hypotheses), server-side entitlements with row locking
- ✅ Separate metering: audits, crawled pages, rendered pages, AI requests/tokens, keyword requests, publish ops
- ✅ Stripe checkout, billing portal, cancellation, signed + idempotent webhooks, failed-payment downgrade
- ✅ Dev billing mode (simulated, labelled, refused in production)
- 🔑 Live Stripe requires keys and price ids
- Tests: `test_tenancy.py`, `test_billing.py`

## Phase 6 — Authorized publishing (WordPress), verification, rollback ✅ / 🔑
- ✅ Connector interface (authorize, verify identity, capabilities, locate, read, apply, rollback, disconnect)
- ✅ WordPress via core Application Passwords (authorization flow + manual), capabilities discovered per site/user
- ✅ Supported ops: title, image alt, insert answer after heading, append FAQ, replace link href, add contextual link
- ✅ Unsupported ops declared with reasons (meta description, head JSON-LD, canonical, redirects, robots)
- ✅ Publish preflight, encrypted credentials, independent live verification with retries, rollback with conflict detection
- 🔑 Tested against a fake WordPress implementing the documented REST contract, not a real WordPress install
- Tests: `test_wordpress.py`, e2e `audit → fix → publish → verify → rollback`

## Phase 7 — Scheduling, monitoring, reports, hardening, deployment ✅ (partially ⏳)
- ✅ Celery app, beat schedule (scheduled audits, verification retries, retention, stale-run cleanup) — verified with a real worker
- ✅ Regression detection (issues whose fixes were verified reappear), new/resolved diffs, in-app notifications, optional SMTP alerts
- ✅ Reports (white-label on Agency), admin dashboard, data deletion (website, org, account), retention jobs
- ✅ Readiness endpoint, security headers, Dockerfiles, docker-compose with nginx edge proxy, CI workflow
- ✅ Playwright e2e suite + `scripts/e2e.sh`
- ⏳ Docker Compose not executed (no Docker daemon in build environment)
- ⏳ Email verification, password reset, 2FA, SSO
- ⏳ Additional connectors (Webflow, Shopify), Google Search Console, brand-mention data sources
- ⏳ Independent security review / penetration test
