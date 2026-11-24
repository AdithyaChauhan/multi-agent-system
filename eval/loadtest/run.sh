#!/usr/bin/env bash
# 20-user load test (Phase 5) against a separate app container on the compose network.
#
#   docker compose build app            # the image must contain the current code
#   LOCUST=<path to locust> bash eval/loadtest/run.sh <label>
#
# The container uses the multi_agent_baseline database, the production model settings from .env
# (fallback chain and answer cache on), demo-shopper creation raised for one address, and no alert
# webhook, so simulated damage reports never reach a real channel.
#
# It costs Groq tokens. Groq's per-minute limit caps each model at about 8K tokens a minute, so a
# 3-minute test uses at most about 25K tokens per model in the fallback chain.
set -euo pipefail

LABEL="${1:-loadtest}"
USERS="${USERS:-20}"
SPAWN_RATE="${SPAWN_RATE:-2}"
DURATION="${DURATION:-3m}"
PORT="${PORT:-8001}"
OUT="${LOADTEST_OUT:-${TEMP:-/tmp}/mas-loadtest}"
IMAGE="${IMAGE:-multi-agent-system-ci-fix-cicd-app:latest}"
NETWORK="${NETWORK:-multi-agent-system-ci-fix-cicd_default}"
LOCUST="${LOCUST:-locust}"
PYTHON="${PYTHON:-python}"
NAME=multiagent-loadtest
# SMOKE=1: an invalid Groq key, so every model call fails and every reply is the busy one. Checks
# this script end to end, and the busy path under load, at 0 tokens.
SMOKE_ENV=()
[ "${SMOKE:-0}" = "1" ] && SMOKE_ENV=(-e GROQ_API_KEY=smoke-invalid-key)
# KEY_ENV_FILE=.env.eval: GROQ_API_KEY from the second key (its own quota); everything else from .env.
KEY_ENV=()
[ -n "${KEY_ENV_FILE:-}" ] && KEY_ENV=(--env-file "$KEY_ENV_FILE")

mkdir -p "$OUT"
docker rm -f "$NAME" >/dev/null 2>&1 || true
docker run -d --name "$NAME" --network "$NETWORK" -p "$PORT:8000" --env-file .env "${KEY_ENV[@]}" \
  -e DATABASE_URL=postgresql://postgres:mypassword@db:5432/multi_agent_baseline \
  -e DEMO_SHOPPERS_PER_IP_HOUR=100000 \
  -e ESCALATION_WEBHOOK_URL= \
  -e ALLOW_X_USER_ID=false \
  -e LANGCHAIN_TRACING_V2=false -e LANGSMITH_TRACING=false \
  -e GROQ_MODEL="${GROQ_MODEL:-openai/gpt-oss-20b}" \
  "${SMOKE_ENV[@]}" \
  "$IMAGE" >/dev/null  # GROQ_MODEL: production's model (render.yaml), whatever the local .env says
trap 'docker logs "$NAME" > "$OUT/${LABEL}_app.log" 2>&1 || true; docker rm -f "$NAME" >/dev/null 2>&1 || true' EXIT

for _ in $(seq 1 90); do
  curl -sf "http://localhost:$PORT/health" >/dev/null && break
  sleep 2
done
curl -sf "http://localhost:$PORT/health" >/dev/null || { echo "app did not become healthy"; exit 1; }

curl -s "http://localhost:$PORT/metrics" > "$OUT/${LABEL}_metrics_before.txt"
# Locust exits non-zero when any request failed; the summary below reports that.
LOADTEST_OUT="$OUT" LOADTEST_LABEL="$LABEL" "$LOCUST" -f eval/loadtest/locustfile.py --headless \
  -u "$USERS" -r "$SPAWN_RATE" -t "$DURATION" --host "http://localhost:$PORT" \
  --csv "$OUT/$LABEL" --only-summary || true
curl -s "http://localhost:$PORT/metrics" > "$OUT/${LABEL}_metrics_after.txt"

"$PYTHON" eval/loadtest/summarize.py "$OUT" "$LABEL"
if [ "${SMOKE:-0}" = "1" ] && ! grep -q '"llm_tokens": 0' "$OUT/${LABEL}_summary.json"; then
  echo "WARNING: smoke mode spent tokens; the invalid key did not reach the app"
fi
echo "files in $OUT"
