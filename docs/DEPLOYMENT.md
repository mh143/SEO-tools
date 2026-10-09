# Deployment

## Components
| Process | Command | Notes |
|---|---|---|
| Migrations | `alembic upgrade head` | run before starting a new version |
| API | `uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips <proxy-ip>` | stateless, scale horizontally |
| Worker | `celery -A app.tasks.celery_app worker -Q default,crawl --concurrency=4` | crawls, publishing, verification |
| Beat | `celery -A app.tasks.celery_app beat` | exactly **one** instance |
| Web | `next build` (with `BACKEND_URL` set at build time) then `next start -p 3000` | |
| Edge proxy | `deploy/nginx.conf` | routes `/api/*` → API, `/*` → web, overwrites `X-Forwarded-For`, terminate TLS here or at LB |
| PostgreSQL 14+ / Redis 6+ | managed services recommended | Redis is broker, result backend and rate-limit store |

Docker: `backend/Dockerfile` (API/worker/beat; build arg `INSTALL_RENDERER=true` adds Chromium for JS rendering),
`frontend/Dockerfile` (build arg `BACKEND_URL`), `docker-compose.yml` (all services + nginx on :8080).
The Docker files have not been executed in the development environment (no Docker daemon); the same
processes were run directly and tested.

## Production checklist
1. `APP_ENV=production` — the app refuses to start if any of the following is wrong.
2. `SECRET_KEY` (random, ≥32 bytes) and `ENCRYPTION_KEYS` (Fernet key; keep old keys appended when rotating).
3. HTTPS everywhere; `COOKIE_SECURE=true`; `PUBLIC_APP_URL=https://…` (required by the WordPress authorization flow).
4. `BILLING_MODE=stripe` with `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`, `STRIPE_PRICE_*`; webhook events per `docs/INTEGRATIONS.md`.
5. `AI_PROVIDER=anthropic` + `ANTHROPIC_API_KEY` (or `none`); never `mock`.
6. `SSRF_DEV_ALLOW_HOSTS` empty.
7. Run behind the edge proxy; set uvicorn `--forwarded-allow-ips` to the proxy address only; do not expose the API port directly.
8. Workers need outbound internet (crawling); consider an egress firewall that additionally blocks private ranges and cloud metadata endpoints (defence in depth).
9. Set `CRAWLER_USER_AGENT` to a string with a contact URL for site owners.
10. Backups for PostgreSQL; Redis can be ephemeral.
11. Monitoring: `/api/health` (liveness), `/api/health/ready` (DB + Redis), Celery worker metrics, failed webhook count on the admin dashboard.
12. `BOOTSTRAP_ADMIN_EMAIL` to create the first platform admin (sign up with that email).

## Upgrades
`alembic upgrade head` → restart API, workers, beat → rebuild/restart web. Migrations are additive-first.

## Scaling notes
Crawls are I/O bound: scale workers on the `crawl` queue; keep `CRAWLER_CONCURRENCY` per crawl low to be polite.
Fix verification/retention jobs are light. The API is stateless (sessions in PostgreSQL).
