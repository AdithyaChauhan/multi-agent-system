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
- **Query embeddings are recorded too** (`eval/cassettes/query_vectors.json`), so a replay computes no embeddings and gives the same result on any machine (ADR 0018). After a change that alters search queries, add the missing vectors at 0 tokens by replaying with `VECTOR_CASSETTE_RECORD=1`, for example `VECTOR_CASSETTE_RECORD=1 python eval/run_baseline.py --label rec --model openai/gpt-oss-20b --mode replay` (and the same for each suite).
- A replay miss prints the call that missed. On GitHub it also shows as an annotation on the run.

### Load test

`eval/loadtest/` runs 20 simulated demo shoppers against a separate app container (port 8001, the `multi_agent_baseline` database, alerts off). Locust isn't in `requirements.txt`: install `locust==2.32.4` into its own venv.

```bash
docker compose build app
SMOKE=1 USERS=5 DURATION=40s LOCUST=<path to locust> bash eval/loadtest/run.sh smoke   # 0 tokens: an invalid key, every reply is "busy"
LOCUST=<path to locust> bash eval/loadtest/run.sh p5-load-20u                          # costs tokens: about 110K over three models
```

`KEY_ENV_FILE=.env.eval` takes the second key. The summary reports p95, errors, the share of real answers, cache hits and fallbacks, and is written to `$TEMP/mas-loadtest/`.

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
| Replay evals | Postgres + pgvector service, the scrubbed fixture (with the product vectors), every eval replayed at 0 tokens with recorded query vectors, so nothing machine-specific is recomputed. `eval/ci_gate.py` fails the build if a number drops below its measured bar. |
| Docker build | the app image, with the embedding model baked in |
| Push image | GHCR (`ghcr.io/adithyachauhan/multi-agent-system`), on pushes to `main` only |
| Kubernetes | on pushes to `main`: `helm lint` and `helm template` (Helm v3.16.4); a live `helm upgrade` only when a `KUBECONFIG` secret points at a reachable cluster |

Render's free service sleeps after 15 idle minutes, and waking it takes about a minute. `keep-warm.yml` asks GitHub to ping `/health` every 10 minutes, but GitHub throttles scheduled jobs: on 2026-11-25 and 26 it ran only every 6 to 10 hours. An outside monitor (UptimeRobot's free plan, an HTTP check of `/health` every 5 minutes) keeps the demo awake; always awake uses about 720 of the free tier's 750 instance hours a month. Live evals run from this machine (the commands above), not from GitHub: a runner has no app of its own to call, and the live site ignores `X-User-ID`.

**To reproduce the replay job locally,** extract a clean copy with `git archive HEAD`, never the working folder (it holds `.env`). Run it in the CI images: `pgvector/pgvector:0.8.0-pg15` for the database, with the fixture restored by that container's own `pg_restore`, and `python:3.12` with `CI=true` for `bash eval/ci_replay.sh`.

## Put the demo online (free)

The app runs on Render's free web service and the database on Neon's free Postgres, which has pgvector and doesn't expire. The mock carrier API runs inside the app.

**`main` is the live site:** Render deploys every push to `main` without waiting for CI, so change `main` only through a PR with green CI (ADR 0019).

1. **Neon.** Create a project at [neon.tech](https://neon.tech) in the region closest to Render's (AWS Singapore for `render.yaml`). Copy the **direct** connection string: in **Connect**, turn connection pooling off (the conversation memory uses prepared statements, which the pooler breaks). It starts with `postgresql://` and ends with `?sslmode=require`. Put it in a file named `.env.deploy` in the repo root, as one line: `LIVE_DATABASE_URL=<the string>`. That file is git-ignored. With the Neon CLI instead: `neon login`, then `neon connection-string <branch> --project-id <id>` (unpooled by default).
2. **Load the database** from this machine, with the local Docker stack running:
   ```bash
   bash scripts/load_live_db.sh
   ```
3. **Discord alerts.** Create a server just for yourself if needed (**+** in the left sidebar → **Create My Own**; it comes with `#general`). Open the channel's settings → **Integrations** → **Webhooks** → **New Webhook**. Click the new webhook (it gets a random name such as "Captain Hook"), then **Copy Webhook URL**. To test it before going live, add `ESCALATION_WEBHOOK_URL=<the URL>` as a second line in `.env.deploy`.
4. **Render.** First delete any older services from earlier attempts: the free plan's 750 instance-hours a month cover one always-awake service. Then, at [render.com](https://render.com), choose **New → Blueprint**, pick this GitHub repository and the `main` branch. When asked, paste:
   - `DATABASE_URL`: the Neon string;
   - `GROQ_API_KEY`;
   - `ESCALATION_WEBHOOK_URL`: the Discord URL.

   Google sign-in variables are optional. The service's address gets a random ending when the plain name is taken; the live one is https://multi-agent-chatbot-58ur.onrender.com.
5. **Keep it awake.** On GitHub, go to **Settings → Secrets and variables → Actions → Variables** and add `LIVE_URL`, the Render URL (here `https://multi-agent-chatbot-58ur.onrender.com`).
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
