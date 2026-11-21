#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
if [ -f .env ]; then
    set -a
    . ./.env
    set +a
fi
exec .venv/bin/uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000 "$@"
