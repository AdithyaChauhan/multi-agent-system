# Multi-Agent E-Commerce Chatbot

A production-style multi-agent customer service system built with **LangGraph**, **FastAPI**, and **PostgreSQL**. Three specialized LangGraph agents handle product discovery, order tracking, and customer support — all routed dynamically by an LLM-based intent classifier. Full observability through **LangSmith** and a **Grafana + Loki** monitoring dashboard.

---

## Architecture

```
POST /chat
    │
    ▼
Router (LLM intent classifier)
    ├── product_agent  ──► product_enrichment_subgraph
    ├── order_agent    ──► shipment_tracking_subgraph
    └── support_agent  ──► escalation_handler_subgraph
```

| Layer | Technology |
|---|---|
| Backend | FastAPI + Uvicorn |
| Agents | LangGraph (StateGraph) |
| LLM | OpenAI GPT-4o-mini |
| Database | PostgreSQL (SQLAlchemy 2.0) |
| Auth | Google OAuth 2.0 + JWT |
| Observability | LangSmith (tracing + prompts + eval) |
| Monitoring | Grafana + Loki + Promtail |
| CI/CD | GitHub Actions (6 stages) |

---

## Quick Start

### Prerequisites

- Docker + Docker Compose
- OpenAI API key
- LangSmith account (free tier at [smith.langchain.com](https://smith.langchain.com))
- Google OAuth credentials (for the login UI)

### 1. Clone and configure

```bash
git clone https://github.com/AdithyaChauhan/multi-agent-system.git
cd multi-agent-system
cp .env.example .env
# Fill in OPENAI_API_KEY, LANGCHAIN_API_KEY, GOOGLE_CLIENT_ID/SECRET
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
```

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

Pass `X-Session-ID` header to continue an existing session. The response always includes `X-Session-ID`. Sessions expire after `SESSION_EXPIRY_MINUTES` (default 60) of inactivity — a 410 response signals a new session is needed.

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

All traces, prompt versions, and evaluation results are visible in LangSmith.

- **Project:** `multi-agent-ecommerce`
- **Prompts in Hub:** `router-classification-prompt`, `support-classification-prompt`
- **Evaluation dataset:** `multi-agent-ecommerce-eval`

### View traces

1. Go to [smith.langchain.com](https://smith.langchain.com)
2. Open the **multi-agent-ecommerce** project
3. Each chat request appears as a top-level run with nested node executions, LLM calls, and tool calls

### Push updated prompts

After editing `ROUTER_SYSTEM_PROMPT` in `app/agents/router.py`:

```bash
python3 push_router_prompt.py
```

### Run evaluation

```bash
# Against the LangSmith dataset (uses real LLM)
source venv/bin/activate && python3 app/evaluation/run_eval.py

# CI fixture mode (no API calls)
python eval/run_deepeval.py

# Live mode (calls the running app)
RUN_LIVE_EVAL=true python eval/run_deepeval.py
```

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
  agents/       router.py + product/order/support agents + subgraphs + state
  api/          Google OAuth (auth.py)
  core/         config, logger, JWT utils, LangSmith prompt loader
  db/           SQLAlchemy engine + seed scripts
  models/       ORM models (Product, Order, User, Session, Message, Review, Spec, SupportTicket)
  tools/        DB query functions used by agents
  static/       Frontend HTML/JS (chat.html, login.html, callback.html)
  evaluation/   LangSmith evaluation scripts
eval/
  dataset.json  12 test cases for CI evaluation
  config.yaml   Metric thresholds
  run_deepeval.py  DeepEval evaluation script
helm/           Kubernetes Helm charts
monitoring/     Grafana + Loki + Promtail configuration
tests/          pytest test suite (81% coverage)
backups/        DB backup snapshots + migration SQL files
```

---

## Environment Variables

See [.env.example](.env.example) for the full list. Key variables:

| Variable | Description |
|---|---|
| `DATABASE_URL` | PostgreSQL connection string |
| `OPENAI_API_KEY` | OpenAI API key for GPT-4o-mini |
| `LANGCHAIN_API_KEY` | LangSmith API key |
| `LANGCHAIN_PROJECT` | LangSmith project name (`multi-agent-ecommerce`) |
| `GOOGLE_CLIENT_ID` | Google OAuth client ID |
| `GOOGLE_CLIENT_SECRET` | Google OAuth client secret |
| `JWT_SECRET_KEY` | Secret for signing JWT tokens |
| `SESSION_EXPIRY_MINUTES` | Session inactivity timeout (default: 60) |
