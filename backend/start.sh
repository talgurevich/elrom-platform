#!/usr/bin/env bash
# Render startup script: run migrations then launch the API.
set -euo pipefail

echo "▶ Running database migrations…"
alembic upgrade head

echo "▶ Seeding default tenant (no-op if one already exists)…"
python -m scripts.seed_dev || true

echo "▶ Backfilling אל-רום tenant.system_context (no-op if already set)…"
python -m scripts.backfill_tenant_context || true

echo "▶ Running pending one-time data migrations…"
# Versioned runner (scripts/run_data_migrations.py) — each backfill runs
# exactly once ever and is recorded in the data_migrations table. Replaces
# the old always-run pile that re-scanned the corpus on every deploy.
python -m scripts.run_data_migrations || true

echo "▶ Starting uvicorn on 0.0.0.0:${PORT:-8000} with ${WEB_CONCURRENCY:-2} workers"
# Run at least 2 workers so /api/health stays responsive while another worker
# is busy on a long-running OCR upload. Render's default WEB_CONCURRENCY=1
# starves health checks during multi-minute OCR jobs and the platform restarts
# the instance mid-request.
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}" --workers "${WEB_CONCURRENCY:-2}"
