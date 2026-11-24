# 0016. Product questions through a read-only ToolNode loop; one-click demo shoppers; free single-service deploy
- **Status:** Accepted, implemented (Phase 5)
- **Date:** 2026-11-23

## Context
- **Follow-ups about the products on screen weren't supported.** "Tell me more about the second one" or "which of these is the most powerful?" started a new search instead.
- **The user asked for LangGraph tool calling (a ToolNode)** where it fits. 0001, 0002 and 0009 rule out a model that calls tools for orders or for deterministic flows.
- **A judge can't try orders without an account (0013).** Shared demo accounts let one visitor's cancel break the next visitor's demo.
- **The free host allows one always-on service.** Render's free tier has 750 instance-hours a month, and its free Postgres expires after 30 days.

## Decision
- **Product Q&A** (`app/agents/product_qa.py`):
  - The router flags `about_shown` (one prompt line). The product agent sends those turns, when cards are on screen, to a subgraph: an LLM with `bind_tools` → `ToolNode` → back to the LLM, at most 3 tool rounds, then an answer without tools.
  - **Tools:** `get_product_details(position)` and `compare_products(positions)`. They read title, brand, price, rating, attributes and description for the cards on screen, by list position. The list comes from the checkpoint through `InjectedState`, which the model never sees.
  - **Safety by construction:** a prompt-injected product id or order number can't reach the tools. No tool takes a user id or touches orders, tickets or accounts, so 0002 holds.
  - `call_llm(tools=…)` records and replays tool calls, so the Q&A set replays in CI. Tool-call ids aren't part of the key.
- **Demo shoppers:**
  - `POST /auth/demo-shopper` creates `demo-<8 hex>` with five orders (delivered, in transit, shipped, and two processing) and returns a JWT.
  - Five per IP per hour; deleted after two days.
  - The login page's main button. Ownership checks are unchanged.
- **Deploy:**
  - one free Render web service, with the mock carrier API mounted at `/carrier`;
  - Neon's free Postgres;
  - a GitHub Actions ping every 10 minutes keeps it awake;
  - migrations run at container start;
  - `scripts/load_live_db.sh` loads the scrubbed fixture and the embeddings once;
  - Helm stays as the Kubernetes option, and its CI job runs on GitHub-hosted runners.

## Consequences
- **Live check** (gpt-oss-20b, baseline database):
  - "which of these is the most powerful?" made one `compare_products` call;
  - "tell me more about the second one" made one `get_product_details` call;
  - "does the first one have a warranty?" was answered "the facts don't mention a warranty", not a guess.
- **Q&A set:** 6/6 (gpt-oss-20b, 1 run).
- **Cost:** a Q&A turn costs 2–3 model calls; the cache absorbs repeats.
- **Data errors show through.** Answers are only as good as the attributes: one heater titled 2000 W carries `watts: 1000`.
- **Router cassettes changed.** The new `about_shown` field changes the router's schema, so the router cassettes were re-recorded.

## Alternatives considered
- **One autonomous tool-calling agent for everything:** rejected in 0001; less predictable, and it would need order tools.
- **Tools that take product ids:** an injected id could read any product. Positions limit the tools to what's on screen.
- **Paid always-on hosting (about $7 a month):** the user chose free hosting kept awake.
