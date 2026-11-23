# Multi-Agent E-Commerce Assistant

A chat assistant for an online electronics store. It finds products, answers questions about them, tracks orders, cancels them after a human "Yes", and hands safety reports to a person. It's built with LangGraph, FastAPI, Postgres + pgvector and Groq, and it was rebuilt in measured phases from a fragile prototype (about 4/10) to a tested, guarded system.

**Live demo:** _link added at deploy_. Press **Try as a demo shopper**: no sign-up, and you get your own pretend account with five orders.

**Things to try:**
1. `something to keep my room warm under 2000`, then `which of these is the most powerful?`
2. `remove fuzz balls from my sweaters` (no product word, found by meaning)
3. `where is my TV order?`
4. `cancel my mouse order`, then press **Yes**
5. `my charger caught fire` (a critical ticket, plus an alert to a human channel)

**Docs:** [Case study](docs/CASE_STUDY.md) · [Setup, evals, deploy](docs/SETUP.md) · [Roadmap and scorecard](ROADMAP.md) · [Decisions (ADRs)](docs/decisions/README.md) · [Graph diagram](docs/architecture/graph.md)

## Measured results
Every number comes from a recorded run. The runs replay in CI at 0 tokens, and the build fails if a number drops.

| What | Result | How it was measured |
|---|---|---|
| Right product in the top 5 (recall@5) | **0.979** (100 queries); **1.0** on the held-out half | 100 labelled queries; tuned on 53, reported on 47; gpt-oss-20b, gpt-oss-120b and qwen, 1 run |
| Precision of the top 3 | **0.933** | same queries |
| Shop with its section names renamed | recall drop **0 points** (it was 97 points before the rebuild) | 35 queries on a renamed copy of the catalog |
| 51 multi-turn conversations | **48/51** | gpt-oss-20b, 1 run (the 3-run average follows at release) |
| Attack conversations (prompt injection, cross-user orders, fake admin, someone else pressing Yes) | **15/15 safe** | scored on routes and database effects, never on wording |
| Questions about shown products (tool loop) | **6/6** | gpt-oss-20b, 1 run |
| A model is retired or rate-limited | still answers through the next model | live check with a retired model name |
| Unit tests | 348, coverage 89% | `pytest` in CI |

## How it works

```
Browser ── /chat/stream ──► FastAPI (sign-in, rate limits, streaming step labels)
                              │
                              ▼
                 LangGraph router (Postgres checkpointer: one thread per chat)
     one structured LLM call: intent · order · issue · risk  ──► deterministic route()
       │            │                │                   │
   product        order           support              safety
   subgraph      subgraph         subgraph            escalation
       │            │                │                   │
 extract filters  owner-only     cancel: interrupt()   critical ticket
 hybrid search    DB lookup +    pause, Yes resumes    + webhook alert
 (pgvector + full  carrier API   then a Python check
  text + type,     template      tickets → escalation
  fused) in a      reply         subgraph → webhook
  relax loop
 LLM ranker → product cards
 questions about the cards → ToolNode loop (read-only tools)
```

**What the model decides:**
- the intent, the order meant, the support issue and the risk;
- the search filters (only what changed in each message);
- which results really match;
- which product facts to look up when asked about the products on screen.

**What the code decides:**
- **Sign-in and ownership:** every order lookup is filtered by the signed-in user.
- **Cancelling:** an order is cancelled only after that user presses Yes, which resumes the paused graph, and a Python node re-checks owner and status.
- **Tickets:** escalation to tickets and alerts.
- **The catalog's say:** whether we sell something is checked against the catalog, by meaning.
- **Limits and fallbacks:** rate limits, the model fallback chain, and masking emails and phone numbers in logs and traces.
- **The model's tools** read product facts for the products on screen only. No tool takes a user id or touches orders ([ADR 0002](docs/decisions/0002-guardrails-in-python.md), [0016](docs/decisions/0016-product-qa-and-demo-shoppers.md)).

**LangGraph features in use:**
- subgraphs with their own input and output schemas;
- the search loop as graph edges;
- `interrupt()` for the cancel pause;
- a Postgres checkpointer, so a conversation survives restarts;
- `stream_mode="tasks"` for live step labels;
- a `ToolNode` agent loop with `InjectedState`.

Each was adopted only where it replaced hand-written code ([ADR 0009](docs/decisions/0009-langgraph-primitives.md)). Every prompt is under 40 lines and lives in `app/prompts/` ([ADR 0010](docs/decisions/0010-prompt-budget.md)).

| Layer | Technology |
|---|---|
| Agents | LangGraph 1.2 (subgraphs, checkpointer, `interrupt()`, ToolNode) |
| LLM | Groq: gpt-oss-20b, falling back to gpt-oss-120b, then qwen3.8-27b |
| Search | pgvector (HNSW) + Postgres full text, fused by reciprocal rank; local `fastembed` embeddings |
| Backend | FastAPI, SQLAlchemy 2, Alembic |
| Evals | 100 labelled queries, 51 + 15 + 6 conversations, record and replay, a CI gate |
| Ops | Docker, GitHub Actions, Render + Neon, Helm (Kubernetes option), Prometheus, Grafana, Loki |

## Honest limits
- **The data is synthetic.** The catalog comes from a public Amazon India dataset, and the orders and users are demo data. There's no production traffic or A/B evidence.
- **One known miss:** "table" shows laptop tables rather than "we don't sell furniture" ([ADR 0015](docs/decisions/0015-demo-never-breaks.md)).
- **One instance only:** the rate limits and the answer cache are per process.
- **Free-tier quota:** about 200K tokens a day per model. The fallback chain and the cache stretch it, and past it the chat says it's busy.
