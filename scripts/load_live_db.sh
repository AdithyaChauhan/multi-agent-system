#!/usr/bin/env bash
# Load the public demo's database (Neon) once: the scrubbed catalog and demo data, the latest
# migrations, and the product embeddings. Run from the repo root in Git Bash:
#
#     bash scripts/load_live_db.sh
#
# Reads LIVE_DATABASE_URL from .env.deploy (git-ignored; one line: LIVE_DATABASE_URL=postgresql://...).
# The URL is never printed. Needs the local Postgres container (for pg_restore) and venv/.
set -euo pipefail

if [ ! -f .env.deploy ]; then echo "Create .env.deploy with LIVE_DATABASE_URL=... first"; exit 1; fi
LIVE_DATABASE_URL="$(grep -E '^LIVE_DATABASE_URL=' .env.deploy | head -1 | cut -d= -f2-)"
if [ -z "$LIVE_DATABASE_URL" ]; then echo "LIVE_DATABASE_URL is missing in .env.deploy"; exit 1; fi
PY=venv/Scripts/python; [ -x "$PY" ] || PY=python

echo "1/3 restoring the scrubbed catalog (eval/fixtures/ci_baseline.dump)..."
docker exec -i multiagent-db pg_restore --no-owner --no-privileges --clean --if-exists \
  -d "$LIVE_DATABASE_URL" < eval/fixtures/ci_baseline.dump

echo "2/3 applying migrations..."
DATABASE_URL="$LIVE_DATABASE_URL" "$PY" -m alembic upgrade head

echo "3/3 embedding the products (about 2 minutes)..."
"$PY" scripts/embed_catalog.py --database-url "$LIVE_DATABASE_URL"
echo "done"
