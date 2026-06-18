#!/usr/bin/env bash
# Render startup script: run migrations then launch the API.
set -euo pipefail

echo "▶ Running database migrations…"
alembic upgrade head

echo "▶ Starting uvicorn on 0.0.0.0:${PORT:-8000}"
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
