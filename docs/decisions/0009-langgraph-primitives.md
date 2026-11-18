# 0009. Use LangGraph's built-in features instead of hand-written control flow
- **Status:** Accepted (planned for Phase 2). Supersedes the storage part of 0007.
- **Date:** 2026-11-18

## Context
The user's goals for the project are short prompts, a sound architecture, and a clear demonstration of how agents are built: subgraphs, loops, ticket creation. Several of those currently exist as custom plumbing around the graph:
- an in-memory `_session_preferences` dict for search state;
- a flag plus a separate `/cancel-order` endpoint for confirmation;
- a Python `for` loop inside `find_products` for loosening filters;
- one shared state object for every agent;
- a ticket that ends as a database row.

LangGraph 1.2.1 (already installed) provides checkpointers, `interrupt()` and `Command(resume=...)`, cycles, per-subgraph state schemas and streaming.

## Decision
Adopt a LangGraph feature only where it replaces existing code:
- **Checkpointer (Postgres)**, one thread per chat session, holds the conversation and search state. This replaces the planned `session_state` table from 0007. 0007's other ideas stay: the model returns only what changed, code merges it, and active filters appear as chips.
- **`interrupt()`** pauses the support flow for the user's cancel confirmation. The actual cancellation stays a plain Python node with the owner and status checks (0002 is unchanged).
- **A loop in the graph** replaces the loosening `for` loop, with the same order and at most 4 passes.
- **Subgraph input and output schemas** for the product, order and support agents.
- **Streaming of step labels** to the UI.
- **An escalation subgraph** (ticket → notify → waiting), which Phase 5's admin page completes.

New dependency: `langgraph-checkpoint-postgres` (which uses psycopg 3).

## Consequences
- Less custom code. Restarts and multiple app instances keep conversations.
- Every agent behaviour (loop, pause, handoff) shows in the graph diagram and in traces.
- The cancel flow's HTTP contract changes: the UI resumes the paused thread instead of calling `/cancel-order`.

## Alternatives considered
- **A supervisor agent, more agents, or model-driven tool calling for orders and cancellation.** Rejected (0001): more tokens and less predictability, for flows that are deterministic.
- **Keeping the custom plumbing.** Rejected: it works, but it's harder to follow and shows less of how agents are built.
