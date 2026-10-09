#!/usr/bin/env bash
# Run the Playwright end-to-end suite against a locally started stack.
# Requires: PostgreSQL + Redis running, backend venv installed, frontend deps installed.
# Uses a dedicated database (seo_e2e) that is recreated on each run.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LOG="${E2E_LOG_DIR:-/tmp/seo-e2e}"; mkdir -p "$LOG"
DB_URL="${E2E_DATABASE_URL:-postgresql+psycopg://seo:seo@localhost:5432/seo_e2e}"
PIDS=()
# Every service is started with setsid (its own process group) so that children such as the
# Next.js server spawned by npx are stopped too.
cleanup() { for p in "${PIDS[@]}"; do kill -- "-$p" 2>/dev/null || kill "$p" 2>/dev/null || true; done; }
trap cleanup EXIT

for port in 3000 8000 8301 8302; do
  if curl -s -o /dev/null "http://127.0.0.1:$port/" 2>/dev/null; then
    echo "Port $port is already in use; stop the process using it first." >&2; exit 1
  fi
done

if command -v dropdb >/dev/null && [ "${E2E_RESET_DB:-1}" = "1" ]; then
  export PGPASSWORD="${PGPASSWORD:-seo}"
  dropdb -w --if-exists -U "${PGUSER:-seo}" -h localhost seo_e2e
  createdb -w -U "${PGUSER:-seo}" -h localhost seo_e2e
fi

# Clear rate-limit counters left by previous local runs (keys are prefixed "rl:").
if command -v redis-cli >/dev/null; then redis-cli --scan --pattern 'rl:*' | xargs -r redis-cli del >/dev/null || true; fi

cd "$ROOT/backend"
source .venv/bin/activate
DATABASE_URL="$DB_URL" alembic upgrade head >"$LOG/migrate.log" 2>&1
setsid python scripts/e2e_fixtures.py >"$LOG/fixtures.log" 2>&1 & PIDS+=($!)
setsid env APP_ENV=development DATABASE_URL="$DB_URL" TASK_BACKEND=inline BILLING_MODE=dev AI_PROVIDER=mock \
  SSRF_DEV_ALLOW_HOSTS=127.0.0.1 CRAWLER_DELAY_SECONDS=0 PUBLIC_APP_URL=http://localhost:3000 \
  uvicorn app.main:app --host 127.0.0.1 --port 8000 >"$LOG/api.log" 2>&1 & PIDS+=($!)

cd "$ROOT/frontend"
if [ "${E2E_SKIP_BUILD:-0}" != "1" ]; then rm -rf .next && NEXT_TELEMETRY_DISABLED=1 npx next build >"$LOG/build.log" 2>&1; fi
setsid env BACKEND_URL=http://127.0.0.1:8000 NEXT_TELEMETRY_DISABLED=1 npx next start -p 3000 >"$LOG/web.log" 2>&1 & PIDS+=($!)

for i in $(seq 1 60); do curl -sf http://localhost:3000/api/health >/dev/null && break; sleep 1; done
npx playwright test "$@"
