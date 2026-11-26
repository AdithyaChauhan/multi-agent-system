# Project briefing prompt

Paste everything below the line into a new Claude chat, and attach the project zip if you have it. It gives that chat the full story of the project in plain words, including the architecture walk-through from the 3D explainer. Last updated 2026-11-26, at the end of Phase 5.

---

You're helping me, the author, understand, explain and continue my capstone/portfolio project. Read this briefing fully before answering. Use simple words, short sentences and concrete examples. When you quote a number, also say how it was measured (model, number of runs, database). If the attached code disagrees with this briefing, trust the code and tell me.

## 1. What the project is

It's a chat assistant for an online electronics store, live at https://multi-agent-chatbot-58ur.onrender.com. A shopper can:
- **find products**, for example "wireless mouse under 1000", then "what about Logitech";
- **ask about the products shown**, for example "which of these is silent?";
- **check their orders**, for example "where is my TV order?";
- **get support**, for example "ORD-2004 arrived damaged", "cancel ORD-2005" or "my heater caught fire".

A visitor can press one button to become a demo shopper with their own orders, so nobody needs an account to try it.

**Tech stack:**
- FastAPI is the web server and serves the chat UI.
- LangGraph runs the agent flow, with a Postgres checkpointer.
- Groq is the LLM provider, on its free tier (`openai/gpt-oss-20b`, with a fallback chain to other models).
- Postgres holds products (with pgvector embeddings), orders, tickets and chat state.
- Render (free) hosts the app and Neon (free) the database. GitHub Actions runs CI. Docker Compose runs everything locally.

The catalog has 1,350 products in 47 types. The catalog comes from a public dataset; the orders and users are demo data.

**Architecture in one line:** a **router** reads each message and makes one structured LLM decision; plain Python then hands the message to one of three **agents** (product, order or support). Each agent is a LangGraph subgraph.

## 2. The story, phase by phase

| Phase | What changed | Measured result |
|---|---|---|
| Start (`e0bdf3c`, about 4.2/10) | It crash-looped on startup, ran out of quota after about 55 product turns a day, ran older prompt copies from a hub, and had 38 one-off override rules fighting each other | — |
| Simplify | 38 override rules → 10; 12 keyword lists → 0; agent code 2,810 → 948 lines; prompts only from git | 51 conversations: 37 → 43 passed (gpt-oss-20b and -120b, 1 run) |
| 0. Measuring stick | 100 labelled product queries, 51 multi-turn conversations, record and replay of model calls | recall@5 0.874, precision@3 0.870. Renaming the categories dropped recall to 0: search only worked through category names |
| 1. Clean product data | An LLM typed every product into 47 types with attributes; facts moved from prompts and Python constants into the database | recall@5 0.874 → 0.958, precision@3 → 0.926, empty results 9.5% → 0% |
| 2. LangGraph architecture | Checkpointer, `interrupt()` for the cancel pause, the search loop as graph edges, subgraph schemas, streaming, an escalation subgraph, filter chips | 51 conversations: 45 → 47. A pending cancel survives an app restart |
| 3. Hybrid search and cards | pgvector + full text + product type, fused by rank; local embeddings; product cards with photos | Held-out half (47 queries): recall@5 0.933 → 1.0. Renamed shop: recall drop 11.8 → 0 points. Search about 90 ms |
| 4. Demo never breaks | Model fallback chain, a "busy" reply instead of an error, an answer cache, per-user limits, a safety floor, CI replays every eval | 15 attack conversations, all safe. 51 conversations 48/51 |
| 5. Ship and showcase | One-click demo shoppers, product questions through a read-only tool loop, the live deploy, CI on GitHub, honest reply headers | See section 4 |

**A finding worth telling:** on the live site I searched "hdmi cables" and got three HDMI cables under "These don't match everything you asked for". The header trusted a model list that gpt-oss-20b often leaves empty. The evals checked the products shown, never that sentence. The fix: a header that claims nothing ("Here's what I found:"), notes only for what code checked ("I widened the price limit"), and an eval check that fails any false claim. Re-scored with that check, the two earlier release runs fell from 48/51 to 38/51, so only runs of the fixed code count.

## 3. Architecture walk-through (from my 3D explainer)

The explainer is a scroll-driven 3D page, published as a claude.ai artifact: https://claude.ai/artifact/2ZtU89shqw2C7Jqq56nGgF (source: `docs/visual/agent-flow.html`). It follows one message through the browser, FastAPI, the router, an agent, Groq and Postgres, and each stop names the file that does the work.

**Every message starts the same way:**
1. The chat UI posts to `/chat` (`app/main.py`). Who you are comes from the session cookie, never from the message text.
2. LangGraph loads the conversation's saved state from Postgres (the checkpointer).
3. The router (`app/agents/router.py`, prompt `app/prompts/router.md`, 27 lines) makes one structured Groq call and gets back intent, order id, issue type, risk and whether you're asking about the shown products. Plain Python (`route()`) picks the next step: safety first, then sign-in, then intent.

**The seven stories:**
1. **Refine a product search** ("what about Logitech"). The model returns only what changed; code merges it into the saved filters, shown as chips. Hybrid search finds candidates; if nothing fits, the graph loops back and widens one filter at a time. One small ranking call orders them. A template writes the reply, with cards.
2. **Ask about the cards** ("which of these is silent?"). The only tool-calling part: a LangGraph `ToolNode` loop whose tools only read facts of the products already shown (`app/agents/product_qa.py`).
3. **Track an order** ("where is my TV order?"). Every lookup is filtered by your own user id. The reply is a template filled from the database row.
4. **Report a damaged item** ("ORD-2004 arrived damaged"). A fixed map, not the model, turns the issue into a ticket, one open ticket per order. The escalation subgraph alerts a person on Discord.
5. **Cancel an order** ("cancel ORD-2005"). The graph pauses with `interrupt()` and the chat shows Yes and No. Only the owner's Yes resumes it, and a Python node checks the owner and status again before cancelling.
6. **Report a safety risk** ("my heater caught fire"). The model's flag or a narrow pattern escalates it, even for a guest: a critical ticket and a Discord alert within a minute.
7. **Ask while signed out** ("track my order"). It stops at sign-in; no order data is touched. Product search still works.

**The explainer's design style** matters to me: dark full-screen 3D scene, one idea per screen, big serif headlines, short copy, labels only on the active stop, a minimal HUD. A denser version with side panels and a legend was rejected as cluttered.

## 4. Where it stands (Phase 5, the last phase)

Release numbers (gpt-oss-20b, local app on the `multi_agent_baseline` database unless said otherwise):
- **51 conversations, 3 live runs of the fixed code:** **48/51** in each run (runs 3, 4 and 5, 2026-11-25 and 26, two API keys), 0 false claims; the same three conversations failed each time. Two earlier runs of the old code scored 38/51 once false claims were counted, so they don't count.
- **Attack set:** all safety cases pass (prompt injection, other users' orders, someone else pressing Yes); replayed in CI.
- **Questions about shown products:** 6/6.
- **20-user load test:** p95 1.3 s, 0 of 377 requests failed. Only 14% of replies were real answers; the rest were a quick "busy" reply, because the free tier allows about 5 product turns a minute.
- **Safety alert:** reaches Discord before the 1.7 s reply.
- **Keeping the free site awake:** an outside monitor (UptimeRobot) pings `/health` every 5 minutes; GitHub's scheduled ping ran only every few hours.
- **Judge path on the live site:** demo shopper, search, a question, an order, a cancel in 10 s.
- **Unit tests:** 370, coverage 90%. CI replays every eval at 0 tokens and fails the build if a number drops.

What's still weak:
- three conversations fail: "table" shows laptop tables instead of "we don't sell furniture"; "4k monitor" (the catalog has one Full HD monitor); "resolve support issues" goes to support instead of asking what's wrong;
- precision on the renamed shop is about 10 points lower than on the real one;
- one instance only: rate limits and the answer cache live in process memory;
- the data is synthetic, and the 100 query labels still need a human reviewer.

## 5. Rules this project follows (please respect them in any advice)
- **Don't over-engineer prompts.** Fix model mistakes in data, code or tests, never with a one-off prompt rule. Every prompt stays under 40 lines (today 7 prompts, 95 lines, the longest 31).
- **Guardrails live in Python:** sign-in, order ownership, cancel only after Yes, escalation. The model never gets a tool that acts on orders or takes a user id.
- **Keep the router and three agents.** No supervisor agent, no extra agents, no model tool-calling for deterministic flows.
- **A reply claims only what code checked,** and the evals check the claims.
- **Measure before and after** any change to prompts, search, data or models.
- **Facts about products belong in the database,** not in prompt lists or Python constants.
- Free-tier budget: 200K tokens a day and 8K a minute per model, so live runs are planned and replay is used where possible.
- `main` is the live site: changes go through a short branch and a PR with green CI.
- Secrets (`.env`, API keys) are never shown or committed.

## 6. How to help me
Depending on what I ask, you might:
- explain any part of this in simpler words, or as I'd say it in an interview;
- quiz me on the architecture and the trade-offs;
- turn it into portfolio or case-study text, using only the measured numbers above, labelled with how they were measured;
- suggest improvements that fit the rules in section 5.

Start by replying with a 5-sentence summary of the project in plain words, then ask me what I'd like to do.
