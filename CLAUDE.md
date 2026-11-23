# CLAUDE.md

Multi-agent e-commerce chat assistant: FastAPI, a LangGraph router with product, order and support agents, Groq for the LLM and Postgres for data. It's a portfolio and capstone project, being rebuilt in phases toward a 9/10 bar.

@ROADMAP.md

## Every session
- **Start:** run `/resume`. It reads the current phase plan, the latest progress entry and the relevant decisions, then proposes the next task.
- **One chat per phase** (or per large task). A new phase starts in plan mode: refine its file in `docs/plans/` and get approval before writing code.
- **End, or when the context gets long:** run `/handoff`. It ticks the plan, adds a progress entry, writes ADRs for new decisions and updates the roadmap.
- Trust the docs unless the code contradicts them. If it does, say so and fix the doc.

## Where things are
| Path | What |
|---|---|
| `ROADMAP.md` | Phases, status, scorecard, definition of done |
| `docs/plans/` | One plan per phase: tasks, acceptance criteria, results |
| `docs/decisions/` | ADRs. Read the relevant one before reversing a design choice |
| `docs/PROGRESS.md` | Session log, newest first |
| `docs/visual/` | Scroll-driven 3D explainer (claude.ai artifact). Update it in Phase 5 |
| `DIAGNOSIS.md`, `SIMPLIFY_REPORT.md` | What was broken, and what the `simplify-agents` branch changed |
| `app/main.py` | FastAPI: `/chat` (also resumes a paused cancel), sessions |
| `app/agents/router.py` | One structured LLM decision, then deterministic `route()` |
| `app/agents/product_agent.py`, `app/tools/product_tools.py`, `app/search/` | Product search: extraction, the search loop, hybrid retrieval (pgvector + full text + type, fused) |
| `app/agents/order_agent.py`, `app/agents/support_agent.py` | Deterministic, template replies |
| `app/prompts/*.md` | Every prompt. The file in git is the prompt that runs |
| `app/core/llm.py`, `app/core/config.py` | One shared ChatGroq client; `GROQ_MODEL` is the only model setting |
| `eval/` | 51-conversation behavioural baseline, DeepEval, run logs |

## Commands (Git Bash on Windows)
```bash
DATABASE_URL=sqlite:///./test.db GROQ_API_KEY=ci-mock-key LANGCHAIN_TRACING_V2=false \
  venv/Scripts/python -m pytest -m "not integration" --cov=app -p no:cacheprovider; git checkout -q test.db   # unit tests, CI env; >= 80% coverage
venv/Scripts/python eval/run_retrieval.py --label <name> --model openai/gpt-oss-20b --mode replay            # product-search metrics, 0 tokens
PRODUCT_SEARCH=hybrid PRODUCT_RANKER=off venv/Scripts/python eval/run_retrieval.py --label <name> --model openai/gpt-oss-20b --mode replay   # retrieval alone, 0 tokens
venv/Scripts/python scripts/embed_catalog.py --database-url <postgres url>   # after the catalog changes (hybrid search)
venv/Scripts/python eval/run_baseline.py --conversations eval/adversarial_conversations.json --label <name> --model openai/gpt-oss-20b --mode replay --cassette eval/cassettes/adversarial_openai-gpt-oss-20b.json   # 15 attack conversations, 0 tokens
CI_DATABASE_URL=<restored fixture> bash eval/ci_replay.sh   # what CI's replay-evals job runs; fixture from scripts/make_ci_fixture.py
black --check app/ tests/ eval/ && flake8 app/ tests/ eval/                         # CI pins black 26.5.1, flake8 7.3.0
venv/Scripts/python eval/run_baseline.py --label <name> --runs 1 --model openai/gpt-oss-20b   # costs tokens, see below
docker compose up -d --build              # full stack; UI at http://localhost:8000/static/login.html
docker exec multiagent-db psql -U postgres -d multi_agent_baseline -c "<read-only SQL>"
```
- Black and flake8 aren't in `venv/`. Use `%TEMP%/mas-lint-venv` if it still exists, or pip install the pinned versions into a temp venv.
- `-p no:cacheprovider` stops pytest from leaving `pytest-cache-files-*` folders in the repo (OneDrive blocks its cache rename).
- Without the CI env vars, `tests/conftest.py` imports `app.main`, which tries to reach the Docker host `db` and fails. Tests also rewrite the tracked `test.db`; restore it with `git checkout -q test.db`.
- Retrieval eval: `--mode record` (default) calls Groq and saves answers in `eval/cassettes/`; `--mode replay` reuses them for free and fails loudly if a prompt changed. `--mode fill` replays what it has and records only the missing calls. Tune search on the dev half of `eval/query_split.json` only. Labels: `eval/label_queries.py` (see `eval/product_queries.json`).

## Ground rules
- Never print, log, copy or commit secrets: `.env`, `helm/templates/secret.yaml`, API keys. Read keys only from the environment.
- Never push, deploy (Render, Helm) or change LangSmith hub prompts unless asked in the current session. Commit only when the user asks; `/handoff` suggests a message.
- Don't modify `dump.sql`, `backups/` or `ecommerce.db`. Change data only through Alembic migrations and scripts.
- Use the `multi_agent_baseline` database (README-migrated catalog) for tests and evals. `multi_agent_db` is the user's own volume with the old taxonomy: read-only unless asked.
- OneDrive syncs this folder. Keep large or temporary files (over a few MB) in `%TEMP%` or the scratchpad, not the repo.
- `X-User-ID` names the caller only when `ALLOW_X_USER_ID=true` (tests and eval harnesses set it). Never enable it in a deployed app: it lets anyone act as any user. `/auth/demo-login` accepts only the seeded `demo-user-N` accounts.
- Guardrails stay in Python: sign-in, order ownership, cancel only after the user presses Yes (resuming the graph's `interrupt()`; a Python node re-checks owner and status), and escalation to tickets. Never give the model a tool that acts on orders or takes a user id (ADR 0002).
- Groq free tier: 200K tokens a day and 8K a minute, per model. Estimate tokens before any live run; a full baseline costs about 180K. Use `openai/gpt-oss-20b` / `-120b` (separate quotas), spread runs across days, or use replay mode (from Phase 0).
- Measure before and after any change to prompts, search, data or models (ADR 0004). Say how a number was measured (model, runs, database).
- Don't over-engineer prompts (ADR 0010): fix model mistakes in data, code or tests. Never add a prompt rule for a single conversation; add the case to the evals instead. Every prompt stays under 40 lines.
- Use LangGraph features only where they replace hand-written code (ADR 0009). No new agents, supervisor agent, or tool calling for deterministic flows.
- A second Groq key, in another organization with its own quota, may exist in `.env.eval` (git-ignored). Use it with `--env-file .env.eval` on eval scripts when the main key is capped. Never print it, and make sure `GROQ_API_KEY` isn't exported in the shell, because that would win.
- Give the user bash syntax for anything they run by hand.
