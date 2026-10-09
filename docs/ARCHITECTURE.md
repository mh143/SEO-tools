# Architecture

## Overview

```
Browser ──► nginx (edge) ──► /api/*  ──► FastAPI (uvicorn)  ──► PostgreSQL
                         └─► /*      ──► Next.js (UI)            ▲
                                                                 │
                         Redis ◄──── Celery worker(s) / beat ────┘
                                         │
                                         └──► Internet (crawls, WordPress, Anthropic, Stripe, DataForSEO)
                                              via the SSRF-safe fetcher (customer-supplied hosts)
```

Modular monolith: one Python codebase serves the API and runs the workers; one Next.js app serves the UI.
In development Next.js proxies `/api/*` to FastAPI (rewrite resolved at build time from `BACKEND_URL`);
in production nginx routes `/api/*` directly to FastAPI.

## Backend modules (`backend/app`)

| Module | Responsibility |
|---|---|
| `core/config.py` | Settings from env; refuses unsafe production config |
| `core/security.py`, `api/deps.py` | Argon2 hashing, opaque session tokens (SHA-256 stored), CSRF, org membership/role checks, `scoped_get` |
| `core/crypto.py` | Fernet (MultiFernet, key rotation) for integration credentials |
| `core/ratelimit.py` | Redis fixed-window limiter (in-process fallback outside production) |
| `models/entities.py` | All tables (see below) |
| `crawler/ssrf.py`, `crawler/fetcher.py` | URL validation, connect-time DNS pinning, manual redirects, size/time limits |
| `crawler/robots.py`, `crawler/sitemap.py`, `crawler/extractor.py`, `crawler/crawler.py` | robots.txt, sitemaps, HTML extraction, BFS crawl |
| `crawler/renderer.py` | Optional Playwright rendering; all browser requests fulfilled by the safe fetcher |
| `audit/engine.py`, `audit/rules/*` | Deterministic rules → `Finding` (evidence, severity, finding type, confidence), heuristic scores |
| `ai/provider.py`, `ai/tasks.py` | Provider abstraction, prompts, JSON schemas, output validation |
| `fixes/*` | Fix types, generator, lifecycle state machine, live verification, publisher (apply/verify/rollback) |
| `integrations/*` | Connector interface, WordPress connector, deterministic content edits |
| `keywords/*` | DataForSEO client, AI ideas, on-page terms |
| `billing/*` | Plans, entitlements & metering, Stripe service |
| `reports/export.py` | CSV/JSON/Markdown/HTML exports (escaped, formula-injection safe) |
| `services/*` | Crawl orchestration & persistence, scheduler, retention, notifications |
| `tasks/*` | Celery app/beat schedule, job functions, inline dispatcher for dev |

## Data model

`users`, `user_sessions`, `organizations`, `memberships` (role), `invitations`, `websites`,
`integrations` (encrypted credentials, capabilities), `crawl_runs`, `pages`, `page_snapshots` (gzip HTML),
`issues` (rule, severity, finding type, confidence, evidence JSON, fingerprint, status), `fix_proposals`
(before/after, validation, provider resource, original state, provider response, rollback ref, verification
result, approver, timestamps), `change_logs` (every fix state transition), `keyword_research` (source +
data provider), `usage_events`, `subscriptions`, `billing_webhook_events` (Stripe event id PK → idempotency),
`audit_logs`, `notifications`.

Every tenant-owned table has `org_id`. Anonymous public audits use `org_id IS NULL` and are only reachable
through a random token (hash stored) until they expire.

## Crawl → audit pipeline

1. `create_run` checks entitlements (audits/month, JS rendering) and records usage.
2. Worker `execute_run`: fetch start URL (follow validated redirects) → robots.txt → llms.txt → sitemaps →
   BFS over same-site links within page/depth limits; 5xx/timeouts retried once to *confirm* errors.
3. Pages, snapshots and findings are persisted; findings get a stable fingerprint
   (`website + rule + url + key`) used for diffs, ignore carry-over and regression detection.
4. Summary: heuristic scores, counts by type/severity, diff vs previous run; notifications on regressions.

## Fix lifecycle

```
detected → analyzed → drafted → awaiting_approval → approved → applying → verifying → verified
                 ↘ (validation failed: stays analyzed)          ↘ failed      ↘ failed (not visible after N checks)
drafted/awaiting/approved → externally_applied_unverified → verifying → verified | failed
verified/failed → rolled_back                    awaiting/approved → rejected → drafted
```

Transitions are enforced in `fixes/lifecycle.py`; `verified` can only be set by the verifier after a
successful live check. Each transition writes a `change_logs` row (actor, message, data).

## Heuristic scores

Per category: `100 − Σ severity weights` (page-level findings normalised by page count). They are for tracking
progress only and are labelled as non-standard everywhere they appear.
