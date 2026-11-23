# Setup, evals and deployment

How to run the assistant locally, measure it, and put the public demo online. The project overview is in the [README](../README.md).

## Run it locally

**Requirements:**
- Docker and Docker Compose;
- a Groq API key. The free tier allows 200K tokens a day per model; the app falls back across three models.

```bash
git clone https://github.com/AdithyaChauhan/multi-agent-system.git
cd multi-agent-system
cp .env.example .env            # fill in GROQ_API_KEY (and optional keys)
docker compose up -d --build    # app :8000, Postgres+pgvector :5433, mock carrier :9000, Grafana :3000
```

**Load the catalog.** The quickest way is the scrubbed copy the CI uses: 1,350 typed products, demo users and orders. Restore it, apply migrations, then embed the products for hybrid search. The embedding uses a small local model and takes about 2 minutes on a laptop CPU.

```bash
docker exec -i multiagent-db pg_restore -U postgres --no-owner --clean --if-exists \
  -d multi_agent_db < eval/fixtures/ci_baseline.dump
docker compose exec app alembic upgrade head
docker compose exec app sh -c 'python scripts/embed_catalog.py --database-url "$DATABASE_URL"'
docker compose restart app
```

Open http://localhost:8000 and press **Try as a demo shopper**.

**Rebuilding the catalog from the raw dataset** instead: see `scripts/enrich_catalog.py`. The types and brand merges are in `data/catalog/*.yaml`, the one-time labelling output is in `enriched_products.jsonl`, and the human corrections are in `review.csv`.

## API

| Method | Path | What it does |
|---|---|---|
| `POST` | `/chat` | One chat turn. `"confirm": true/false` answers a paused question (the cancel Yes/No), and `"remove_filter"` removes a filter chip. |
| `POST` | `/chat/stream` | The same turn as server-sent events: `step` labels while the graph runs, then one `reply` event with the `/chat` body. |
| `POST` | `/auth/demo-shopper` | A fresh demo shopper with five orders of their own (5 per IP per hour). |
| `GET` | `/auth/login`, `/auth/callback` | Google sign-in (optional). |
| `GET` | `/messages/{session_id}` | Conversation history. |
| `GET` | `/health`, `/metrics` | Health check, Prometheus metrics. |
| `GET` | `/carrier/tracking/{id}` | Mock carrier API (demo tracking data). |

A session continues with the `X-Session-ID` header or `session_id` in the body. Sessions expire after `SESSION_EXPIRY_MINUTES` of inactivity (HTTP 410).

## Evals

Every eval can replay recorded model answers ("cassettes") at 0 tokens; CI does exactly that. The commands are for Git Bash on Windows (`venv/Scripts/python`), or `python` on Linux and macOS.

```bash
# Product search: 100 labelled queries, same model per query as the reference runs
python eval/run_split.py check all --mode replay                      # with the LLM ranker
python eval/run_split.py check all PRODUCT_RANKER=off --mode replay   # retrieval alone
# 51 conversations through the real /chat endpoint
python eval/run_baseline.py --label check --model openai/gpt-oss-20b --mode replay
# 15 attacks (injection, cross-user orders, fake admin, someone else's "Yes")
python eval/run_baseline.py --label adv --model openai/gpt-oss-20b --mode replay \
  --conversations eval/adversarial_conversations.json --cassette eval/cassettes/adversarial_openai-gpt-oss-20b.json
# Questions about shown products (the tool-calling loop)
python eval/run_baseline.py --label qa --model openai/gpt-oss-20b --mode replay \
  --conversations eval/qa_conversations.json --cassette eval/cassettes/qa_openai-gpt-oss-20b.json
```

- `--mode record` calls Groq and saves the answers.
- `--mode fill` replays what it has and records only the missing calls.
- `--mode live` saves nothing.
- Tune search only on the dev half of `eval/query_split.json`.
- The renamed-catalog robustness check uses `scripts/make_renamed_catalog_db.py`.

## Tests

```bash
DATABASE_URL=sqlite:///./test.db GROQ_API_KEY=ci-mock-key LANGCHAIN_TRACING_V2=false \
  python -m pytest -m "not integration" --cov=app      # unit tests (SQLite), coverage >= 80%
python -m pytest -m integration                         # needs the local Postgres with embeddings
```

## CI/CD (`.github/workflows/ci.yml`)

| Stage | What |
|---|---|
| Lint | `black --check`, `flake8` |
| Unit tests | `pytest`, coverage ≥ 80% |
| Replay evals | Postgres + pgvector service, scrubbed fixture, every eval replayed at 0 tokens. `eval/ci_gate.py` fails the build if a number drops below its measured bar. |
| Docker build | the app image, with the embedding model baked in |
| Push image | GHCR, on pushes to the release branches |
| Kubernetes | `helm lint` and `helm template` always; a live `helm upgrade` only when a `KUBECONFIG` secret points at a reachable cluster |

`keep-warm.yml` pings the live demo every 10 minutes, and `eval.yml` is the manual live DeepEval run.

## Put the demo online (free)

The app runs on Render's free web service and the database on Neon's free Postgres, which has pgvector and doesn't expire. The mock carrier API runs inside the app.

1. **Neon.** Create a project at [neon.tech](https://neon.tech) and copy the connection string, which starts with `postgresql://` and ends with `?sslmode=require`. Put it in a file named `.env.deploy` in the repo root, as one line: `LIVE_DATABASE_URL=<the string>`. That file is git-ignored.
2. **Load the database** from this machine, with the local Docker stack running:
   ```bash
   bash scripts/load_live_db.sh
   ```
3. **Discord alerts.** In a Discord server, go to the channel's settings, then **Integrations**, then **Webhooks**, then **New Webhook**, and copy the webhook URL.
4. **Render.** At [render.com](https://render.com), choose **New → Blueprint**, pick this GitHub repository and the `main` branch. When asked, paste:
   - `DATABASE_URL`: the Neon string;
   - `GROQ_API_KEY`;
   - `ESCALATION_WEBHOOK_URL`: the Discord URL.

   Google sign-in variables are optional.
5. **Keep it awake.** On GitHub, go to **Settings → Secrets and variables → Actions → Variables** and add `LIVE_URL`, the Render URL (for example `https://multi-agent-chatbot.onrender.com`).
6. **Check it.** Open the live URL in a private window, press **Try as a demo shopper**, then search for a product, ask about one of the results, track an order, and cancel the processing one. "My charger caught fire" should post to the Discord channel.

`helm/` remains as the Kubernetes option (`helm upgrade --install … --values helm/values.yaml`).

## Environment variables

See [.env.example](../.env.example) for the full list.

| Variable | What it does |
|---|---|
| `DATABASE_URL` | Postgres connection string |
| `GROQ_API_KEY` | The Groq API key |
| `GROQ_MODEL` | The first model tried (the live demo uses `openai/gpt-oss-20b`) |
| `GROQ_FALLBACK_MODELS` | Tried in order when the first is rate-limited, down or retired. If none answers, the chat says it's busy instead of failing. |
| `PRODUCT_SEARCH` | `hybrid` (the default: pgvector, full text and type, fused) or `type`. It falls back to `type` until embeddings exist. |
| `ESCALATION_WEBHOOK_URL` | A Discord or Slack webhook for safety reports and tickets. Unset: the app log only. |
| `CHAT_RATE_PER_MINUTE`, `CHAT_TURNS_PER_DAY` | Per-user (per-IP when anonymous) limits, 20 and 150 by default |
| `MOCK_CARRIER_API_URL` | Where order tracking is fetched (the live demo: the app's own `/carrier`) |
| `JWT_SECRET_KEY`, `SESSION_EXPIRY_MINUTES` | Sign-in tokens and session timeout |
| `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_REDIRECT_URI` | Optional Google sign-in |
| `LANGCHAIN_API_KEY`, `LANGCHAIN_TRACING_V2` | Optional LangSmith tracing (emails and phone numbers are masked) |
| `ALLOW_X_USER_ID` | Tests and eval harnesses only: lets the `X-User-ID` header name the caller. Never set it on a deployed app. |

## Monitoring

`docker compose up` also starts Grafana at http://localhost:3000 (admin / admin). It shows request volume, routes, latency, errors, tokens, fallbacks, cache hits and rate limits. Logs go to Loki.
