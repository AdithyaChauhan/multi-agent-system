# 0001. Keep the router and three agents; rebuild only the product layer
- **Status:** Accepted
- **Date:** 2026-11-18

## Context
After the `simplify-agents` branch, the app is a FastAPI service with one LangGraph router (one structured LLM call) and three agents. Every failure seen in manual testing on 2026-11-18 was in product search:
- old category names in replies ("We don't carry bose HomeAudio");
- a follow-up that dropped the price cap and "wireless" ("what about Logitech");
- mouse pads in mouse results;
- empty searches.

Order lookup, cancellation, tickets, sign-in and safety routing behaved correctly, in manual tests and in the 51-conversation baseline. The product agent and product tools are 568 of the 1,101 lines in `app/agents/` plus `app/tools/product_tools.py`.

## Decision
Keep FastAPI, sessions, the router's single decision, the order and support agents, the cancel flow and every guardrail. Rebuild the product side: the data model (0005), search (0006) and search state (0007). Ship it in measured steps (0004), not as one rewrite.

## Consequences
- The project keeps its router-plus-three-agents shape, so the multi-agent framing survives.
- Each step can be undone; the old search keeps running until the new one wins.
- Order and support code change only where a later phase needs it (state, auth, admin page).

## Alternatives considered
- **Full rewrite.** Rejected: high risk, rebuilds parts that work, and the app stops working before the replacement is proven.
- **One autonomous tool-calling agent.** Rejected: more tokens per turn, less predictable, and qwen's first-try tool calls come back malformed 30–50% of the time (`DIAGNOSIS.md`).
- **Leaving LangGraph, or adding more agents.** Rejected: the framework never caused a failure.
