#!/usr/bin/env bash
# Replay every eval against the scrubbed fixture at 0 tokens, then apply the gate (Phase 4, ADR 0015).
# CI runs this; to try it locally, restore eval/fixtures/ci_baseline.dump into an empty database and
# set CI_DATABASE_URL to it. Needs the mock carrier API on :9000 (order replies use it).
set -euo pipefail

: "${CI_DATABASE_URL:?set CI_DATABASE_URL to the restored fixture database}"
export BASELINE_DATABASE_URL="$CI_DATABASE_URL"
export GROQ_API_KEY="${GROQ_API_KEY:-ci-replay-no-calls}"  # replay never calls the model
export LANGCHAIN_TRACING_V2=false

DATABASE_URL="$CI_DATABASE_URL" python -m alembic upgrade head
python scripts/embed_catalog.py --database-url "$CI_DATABASE_URL"

python eval/run_split.py ci-retrieval all PRODUCT_RANKER=off --mode replay
python eval/run_baseline.py --label ci-baseline --model openai/gpt-oss-20b --mode replay
python eval/run_baseline.py --label ci-adversarial --model openai/gpt-oss-20b --mode replay \
  --conversations eval/adversarial_conversations.json --cassette eval/cassettes/adversarial_openai-gpt-oss-20b.json
python eval/run_baseline.py --label ci-qa --model openai/gpt-oss-20b --mode replay   --conversations eval/qa_conversations.json --cassette eval/cassettes/qa_openai-gpt-oss-20b.json

python eval/ci_gate.py
