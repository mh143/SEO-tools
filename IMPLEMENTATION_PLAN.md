# Implementation Plan — SEO + AEO + GEO SaaS

## 0. Repository inspection (2026-10-09)

The repository was empty (no commits, no files). There was no existing implementation
to reuse, so the recommended stack is used as-is.

Environment constraints discovered during inspection (they shape how things are tested,
not how the product works):

| Constraint | Consequence |
|---|---|
| No Docker daemon in the build sandbox | `docker-compose.yml` is provided but was not executed here; tests run against locally installed PostgreSQL 16 and Redis. |
| Outbound internet blocked except PyPI/npm | The crawler is tested end-to-end against local fixture websites. Loopback is reachable only through an explicit, dev/test-only `SSRF_DEV_ALLOW_HOSTS` allowlist that is refused when `APP_ENV=production`. |
| No Stripe / AI / keyword / WordPress credentials | Each external integration is implemented against its documented contract, covered by mocked contract tests, and shows as **unconfigured** in the UI until credentials are provided. |

## 1. Architecture summary

Modular monolith:

```
frontend/  Next.js (App Router, TypeScript, Tailwind) — talks only to /api (same-origin rewrite)
backend/   FastAPI app + Celery workers (same codebase)
  app/core         config, security (sessions, CSRF, hashing), encryption, rate limiting, audit log
  app/models       SQLAlchemy models (multi-tenant, org_id on every tenant-owned row)
  app/api          REST routes; every org-scoped route goes through a membership+role dependency
  app/crawler      SSRF-safe fetcher (DNS pinning), robots, sitemaps, HTML extraction, crawler, optional renderer
  app/audit        deterministic rule engine (technical / content / AEO / GEO), scoring
  app/ai           provider abstraction, prompt-injection-hardened prompts, strict output validation
  app/fixes        fix generation (rule-based + AI), lifecycle state machine, verification
  app/integrations connector interface + WordPress (Application Passwords) connector
  app/keywords     keyword providers (DataForSEO measured data, AI ideas — always labelled)
  app/billing      plans, entitlements, usage metering, Stripe + clearly-marked dev billing
  app/reports      JSON / CSV / Markdown / HTML exports
  app/tasks        Celery app, crawl/verify/schedule/retention tasks
```

PostgreSQL holds all state, Redis is the Celery broker and rate-limit store.

## 2. Phases

| Phase | Scope | Exit criteria |
|---|---|---|
| 1 | Docs, config, models + Alembic migration, auth (Argon2 + server-side sessions + CSRF), orgs/memberships/roles, audit log, Next.js shell | migrations apply on clean DB; auth + tenancy tests pass |
| 2 | SSRF-safe fetcher, robots.txt, sitemap discovery, extraction, crawler, deterministic audit rules | SSRF test-suite passes; fixture-site crawl produces evidence-backed issues |
| 3 | Crawl progress + audit dashboard + issue detail (API + UI) | UI renders real data with loading/empty/error/partial states |
| 4 | AI provider abstraction, validated fix generation, before/after diff editor, keyword module, exports | malformed / out-of-scope AI output rejected in tests; exports download |
| 5 | Plans + entitlements + usage metering, Stripe checkout/portal/webhooks, dev billing mode, cross-tenant tests | limits enforced server-side; webhook signature + idempotency tests pass |
| 6 | Connector framework + WordPress connector, apply → verify (independent live fetch) → rollback | contract tests: apply, verify-fail-is-not-success, rollback, conflict detection |
| 7 | Scheduled audits, regression detection, reports, admin dashboard, retention/deletion, rate limits, docker-compose, e2e | full test suite + Playwright e2e green |

After each phase: run tests, fix failures, update `TASKS.md`.

## 3. Key design decisions

* **Server-side sessions over JWT** — opaque random token in an HttpOnly, SameSite=Lax cookie; only
  its SHA-256 is stored, so sessions are revocable. CSRF uses a double-submit token on unsafe methods.
* **Tenant isolation** — every tenant-owned table carries `org_id`; all queries go through
  helpers that require an `org_id` coming from a verified membership. Cross-tenant tests try
  to read/modify every resource type of another org and must receive 404.
* **SSRF** — validation happens at *connect time* inside a custom httpcore network backend: the
  hostname is resolved once, every address is checked, and the socket connects to the
  validated IP (TLS SNI still uses the hostname). This closes DNS rebinding. Redirects are
  followed manually and each hop is re-validated. Environment proxies are ignored for crawling.
* **JS rendering** — optional Playwright mode where *every* browser sub-request is intercepted
  and fulfilled by the SSRF-safe fetcher; the browser never opens its own network connections.
* **AI output** — providers must return JSON matching a per-fix-type Pydantic schema; output is
  rejected if malformed, if it touches fields not allowed for that fix type, if it contains
  markup where none is allowed, or if it introduces numbers/prices/claims not present in the
  source page ("no invented facts" check). Page content is passed as delimited, untrusted data.
* **Verification** — a fix is `verified` only when an independent live fetch of the page
  shows the expected state. API acceptance moves it to `verifying`, never to `verified`.
* **Honest capabilities** — connectors declare capabilities discovered from the live site. The
  WordPress connector supports post/page title, excerpt, constrained content edits, and image
  alt text. It does **not** claim meta descriptions, redirects, canonicals, or robots edits.
* **Measured vs generated data** — keyword volumes/difficulty only come from a named provider;
  AI keyword ideas are stored with `source="ai_idea"` and no metrics. The GEO score is an
  internal heuristic and is labelled as such everywhere it is shown.
