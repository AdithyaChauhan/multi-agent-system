# Multi-Agent E-Commerce Chatbot

A production-style multi-agent customer service system built with **LangGraph**, **FastAPI**, and **PostgreSQL**. Three specialized LangGraph agents handle product discovery, order tracking, and customer support — all routed dynamically by an LLM-based intent classifier. Full observability through **LangSmith** and a **Grafana + Loki** monitoring dashboard.

---

## Architecture

```
POST /chat
    │
    ▼
Router — one structured LLM call: intent, order_id, support issue, risk
    ├── safety risk ──► critical ticket for a human (any user)
    ├── unclear     ──► the router's own short reply
    ├── order/support while anonymous ──► sign-in prompt
    ├── product_agent  extract filters (LLM) → search with one relaxation loop → rank (LLM) → reply
    ├── order_agent    owner-only DB lookup + carrier API → templated status (no LLM)
    └── support_agent  policy / ask which order / UI-confirmed cancel / ticket / drafted reply (LLM, low severity only)
```

What the model decides and what the code decides:

- **Model:** intent, which of the user's orders they mean, the support issue, whether there's a
  safety or legal risk, the product filters (with the previous turn's filters as input), and which
  search results actually match.
- **Code (deterministic):** sign-in before orders/support; every order lookup is filtered by the
  signed-in user; cancellation only after the user presses "Yes" in the UI (`POST /cancel-order`);
  safety, legal and damaged/wrong/refund issues become tickets for a human, one open ticket per order.

LLM calls per message: router only for orders, support, sign-in, clarify and safety; +1 for a
low-severity support reply; product searches make 3 (router, filters, ranking).

Prompts live in [`app/prompts/`](app/prompts/) (router, product extraction, product ranking,
support resolution) and are read from disk. The file in git is the prompt that runs.

| Layer | Technology |
|---|---|
| Backend | FastAPI + Uvicorn |
| Agents | LangGraph (StateGraph) |
| LLM | Groq `qwen/qwen3.8-27b` (one setting: `GROQ_MODEL` in `app/core/config.py`) |
| Database | PostgreSQL (SQLAlchemy 2.0) |
| Auth | Google OAuth 2.0 + JWT |
| Observability | LangSmith (tracing + eval) |
| Monitoring | Grafana + Loki + Promtail |
| CI/CD | GitHub Actions (6 stages) |

---

## Quick Start

### Deploy a public demo on Render

The repository includes a `render.yaml` Blueprint for a public FastAPI service,
managed PostgreSQL, and the mock carrier service. In Render, choose
**New → Blueprint**, connect this repository, and enter `GROQ_API_KEY` and
`LANGCHAIN_API_KEY` when prompted. Google OAuth variables are optional; without
them, recruiters can still use the anonymous chat flow, while order cancellation
remains authentication-protected.

After the first deploy, copy the generated public URL into `GOOGLE_REDIRECT_URI`
as `https://<your-service>.onrender.com/auth/callback` if OAuth is enabled, and
add that same callback URL in Google Cloud Console. The service health check is
`/health`, and the public demo is the service root URL.

### Prerequisites

- Docker + Docker Compose
- Groq API key. On Groq's free tier the app's model allows 200,000 tokens/day and 8,000 tokens/minute:
  roughly 2 product searches a minute and ~70 a day across all users. Past that, Groq returns 429 and
  chats fail until the quota refills. A paid Groq tier removes this ceiling.
- LangSmith account (free tier at [smith.langchain.com](https://smith.langchain.com))
- Google OAuth credentials (for the login UI)

### 1. Clone and configure

```bash
git clone https://github.com/AdithyaChauhan/multi-agent-system.git
cd multi-agent-system
cp .env.example .env
# Fill in GROQ_API_KEY, LANGCHAIN_API_KEY, GOOGLE_CLIENT_ID/SECRET
```

### 2. Start all containers

```bash
docker compose up -d --build
```

This starts:
- `multiagent-app` — FastAPI app on **http://localhost:8000**
- `multiagent-db` — PostgreSQL on port **5433**
- `multiagent-mock-api` — Mock carrier tracking API on port **9000**
- `multiagent-grafana` — Grafana dashboard on **http://localhost:3000**
- `multiagent-loki` — Log aggregation on port 3100
- `multiagent-promtail` — Log shipper

### 3. Restore the database

The app uses a pre-seeded catalog. Restore from the included backup:

```bash
# Drop and recreate schema
docker exec multiagent-db psql -U postgres -d multi_agent_db -c \
  "DROP SCHEMA public CASCADE; CREATE SCHEMA public; GRANT ALL ON SCHEMA public TO postgres;"

# Restore data
docker exec -i multiagent-db psql -U postgres -d multi_agent_db \
  < backups/pre_taxonomy_migration_20260530_152745.sql

# Apply taxonomy migrations
docker exec -i multiagent-db psql -U postgres -d multi_agent_db \
  < backups/v6_taxonomy_migration_20260531.sql
docker exec -i multiagent-db psql -U postgres -d multi_agent_db \
  < backups/mobiles_dissolution_20260531.sql
docker exec -i multiagent-db psql -U postgres -d multi_agent_db \
  < backups/remaining_category_cleanup_20260531.sql

# Restart the app so it picks up the restored data
docker compose restart app
```

The app adds the `support_tickets` columns this backup predates on startup. You can also run
`docker compose exec app alembic upgrade head`; `migrations/env.py` uses the container's `DATABASE_URL`.

### 4. Open the chat UI

Navigate to **http://localhost:8000** — you'll be redirected to the chat interface. Sign in with Google to enable order tracking.

### 5. Health check

```bash
curl http://localhost:8000/health
# {"status":"ok"}
```

---

## Redeploy after code changes

```bash
# Python code changed (agents, tools, main.py, etc.)
docker compose build app && docker compose up -d --no-recreate db && docker compose up -d app

# Static HTML/JS only — live immediately, no rebuild needed
```

---

## API

| Method | Path | Description |
|---|---|---|
| `POST` | `/chat` | Send a message; returns agent response + session ID |
| `GET` | `/messages/{session_id}` | Retrieve conversation history for a session |
| `GET` | `/health` | Health check |
| `GET` | `/auth/login` | Initiate Google OAuth flow |
| `GET` | `/auth/callback` | OAuth callback (handled automatically) |

### Session management

Pass `X-Session-ID` header to continue an existing session. The response always includes `X-Session-ID`. Sessions expire after `SESSION_EXPIRY_MINUTES` (default 30) of inactivity — a 410 response signals a new session is needed.

```bash
# First turn
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -H "X-User-ID: my-user-id" \
  -d '{"message": "show me headphones under 2000"}'

# Follow-up (reuse session)
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -H "X-User-ID: my-user-id" \
  -H "X-Session-ID: <session_id_from_above>" \
  -d '{"message": "show me cheaper options"}'
```

---

## LangSmith

Traces and evaluation results are visible in LangSmith. Prompts are **not** loaded from the
LangSmith hub any more: they live in `app/prompts/*.md` and git is their history.

- **Project:** `multi-agent-ecommerce`
- **Evaluation dataset:** `multi-agent-ecommerce-eval`

### View traces

1. Go to [smith.langchain.com](https://smith.langchain.com)
2. Open the **multi-agent-ecommerce** project
3. Each chat request appears as a top-level run with nested node executions, LLM calls, and tool calls

### Run evaluation

```bash
# Router accuracy on the LangSmith dataset (calls the app's own router node)
python app/evaluation/run_eval.py

# CI fixture mode (stored responses, rule-based metrics, no API calls)
python eval/run_deepeval.py

# Live mode (calls the running app). The gpt-4o-mini GEval judge needs EVAL_OPENAI_API_KEY;
# without it, live mode uses the rule-based metrics and says so.
RUN_LIVE_EVAL=true python eval/run_deepeval.py
```

### Behavioural baseline

`eval/baseline_conversations.json` holds 51 multi-turn conversations (the eval dataset, the old
regression suites and one case per bug fixed in the git history) with plain assertions.
`eval/run_baseline.py` replays them through the real `/chat` endpoint and graph and records pass/fail,
LLM calls, tokens and seconds per turn. It needs the `db` and `mock-carrier-api` containers and a
restored database:

```bash
python eval/run_baseline.py --label after --runs 1                       # all conversations
python eval/run_baseline.py --label check --only p01,s08 --model openai/gpt-oss-20b
```

It paces itself under Groq's tokens-per-minute limit; a full run of the current app uses about
170K tokens, close to one model's daily free quota. Results land in `eval/baseline_runs/`.

---

## Monitoring — Grafana

Open **http://localhost:3000** (admin / admin).

The pre-configured dashboard shows:
- Request volume over time
- Agent selection distribution (product / order / support)
- Average latency per agent
- Error rate over time
- LLM token consumption

Application logs are ingested into Loki and searchable by `session_id`, `agent_name`, and `log_level` from the Explore tab.

---

## Running Tests

```bash
source venv/bin/activate

# Unit tests (CI-compatible — no PostgreSQL required)
python -m pytest -m "not integration" --cov=app --cov-report=term-missing

# Integration tests (requires live PostgreSQL on localhost:5433)
python -m pytest -m integration

# With coverage threshold
python -m pytest -m "not integration" --cov=app --cov-fail-under=80
```

---

## CI/CD Pipeline

GitHub Actions runs on every push to `main`/`stable` and on pull requests targeting `main`.

| Stage | What | When |
|---|---|---|
| 1 — Lint | `black --check` + `flake8` | All pushes |
| 2 — Tests | `pytest` + 80% coverage threshold | All pushes |
| 3 — LLM Eval | DeepEval in fixture mode; reports uploaded as artifacts | All pushes |
| 4 — Docker Build | Build app image | All pushes |
| 5 — Push Image | Push to GHCR | `main` only |
| 6 — Deploy | `helm upgrade --install` + smoke test + auto-rollback | `main` only |

Required GitHub Actions secrets: `LANGCHAIN_API_KEY`, `KUBECONFIG`, `APP_URL`.

---

## Project Structure

```
app/
  agents/       router.py + product/order/support agents + state
  api/          Google OAuth (auth.py)
  core/         config (GROQ_MODEL), shared LLM client (llm.py), logger, JWT utils, prompt loader
  prompts/      the four system prompts, read from disk
  db/           SQLAlchemy engine + seed scripts
  models/       ORM models (Product, Order, User, Session, Message, Review, Spec, SupportTicket)
  tools/        DB query functions used by agents
  static/       Frontend HTML/JS (chat.html, login.html, callback.html)
  evaluation/   LangSmith evaluation scripts
eval/
  dataset.json  12 test cases for CI evaluation
  config.yaml   Metric thresholds
  run_deepeval.py  DeepEval evaluation script
  baseline_conversations.json + run_baseline.py  behavioural baseline (see above)
  baseline_runs/   measured before/after results
helm/           Kubernetes Helm charts
monitoring/     Grafana + Loki + Promtail configuration
tests/          pytest test suite (90% coverage)
backups/        DB backup snapshots + migration SQL files
```

---

## Environment Variables

See [.env.example](.env.example) for the full list. Key variables:

| Variable | Description |
|---|---|
| `DATABASE_URL` | PostgreSQL connection string |
| `GROQ_API_KEY` | Groq API key for the chatbot model |
| `GROQ_MODEL` | Optional: Groq model ID (default `qwen/qwen3.8-27b`). `LLM_MODEL`/`MODEL_NAME` in old `.env` files are not read. |
| `LANGCHAIN_API_KEY` | LangSmith API key |
| `LANGCHAIN_PROJECT` | LangSmith project name (`multi-agent-ecommerce`) |
| `GOOGLE_CLIENT_ID` | Google OAuth client ID |
| `GOOGLE_CLIENT_SECRET` | Google OAuth client secret |
| `JWT_SECRET_KEY` | Secret for signing JWT tokens |
| `SESSION_EXPIRY_MINUTES` | Session inactivity timeout (default: 30) |
