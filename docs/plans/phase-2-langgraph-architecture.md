# Phase 2: LangGraph-native architecture
- **Status:** Not started
- **Branch:** `phase-2-architecture`
- **Depends on:** Phase 0 (replay makes the refactors cheap to verify). Phase 1 helps but isn't required.
- **Decisions:** [0009](../decisions/0009-langgraph-primitives.md) (supersedes the storage part of 0007), [0010](../decisions/0010-prompt-budget.md)

## Goal
Replace hand-written control flow with LangGraph's built-in features where they make the code smaller and the agent behaviour easier to see. The result should show subgraphs, a graph loop, a human-in-the-loop pause, persistent state, streaming and a real ticket handoff, without adding agents or prompt text.

## Why
- The project's purpose includes showing how agents are built: subgraphs, loops, ticket creation.
- Today several of those exist only as Python inside one function, or as custom plumbing around the graph (an in-memory dict, an extra endpoint).
- The rule for this phase: **adopt a feature only if it replaces existing code.** Never add one for show.

## Scope
- **In:** checkpointer, `interrupt()` for cancellation, the search loop as graph edges, subgraph input/output schemas, streaming of step progress, an escalation subgraph with a notification hook, and filter chips (moved here from the old state phase).
- **Out:**
  - new agents, a supervisor agent, model-driven tool calling for deterministic flows (ADR 0001);
  - the admin page, which stays in Phase 5;
  - any change to prompt wording.

## Tasks
- [ ] Plan mode: confirm the order below and the new dependency (`langgraph-checkpoint-postgres`, which uses psycopg 3) with the user. Record the dependency in ADR 0009.
- [ ] **Checkpointer.**
  - Compile the router graph with the Postgres checkpointer; thread id = chat session id.
  - Delete `_session_preferences` from `app/main.py`.
  - Keep the `messages` table for the UI history.
  - Test: restarting the app mid-conversation keeps the filters.
- [ ] **Cancellation with `interrupt()`.**
  - `handle_cancellation` pauses the graph with `{"type": "confirm_cancel", "order_id": ...}` and `/chat` returns the question with Yes and No buttons.
  - The Yes button resumes the same thread with `Command(resume=True)`.
  - A plain Python node then cancels, only for the signed-in owner and only while the order is processing.
  - Tests:
    - no cancellation without a resume;
    - a resume from another user is refused;
    - a resume after the order shipped is refused;
    - "No" leaves the order unchanged.
  - Retire `/cancel-order`, or keep it as a thin wrapper until the UI is switched over.
- [ ] **Search loop as graph edges.** `find_products` becomes `search → check → loosen → search`, at most 4 passes, with the same loosening order as today. Because no prompt changes, **Phase 0 replay must give identical results at 0 tokens.**
- [ ] **Subgraph schemas.** Product, order and support subgraphs declare their own input and output fields. The router passes only those.
- [ ] **Streaming.** `/chat/stream` (server-sent events) built on `graph.stream(stream_mode="updates")`. The UI shows short step labels ("Checking your order…") and then the reply. `/chat` keeps working unchanged.
- [ ] **Escalation subgraph.** Create ticket → notify (a webhook or log hook, configurable) → mark waiting. The notification target is a setting. The human reply path comes with the Phase 5 admin page.
- [ ] **Filter chips** (from ADR 0007):
  - the model returns only what changed, and code merges it into the checkpointed state;
  - `ChatResponse` gains `active_filters`, shown as removable chips in `app/static/chat.html`.
- [ ] Measure:
  - Phase 0 replay (identical results expected for the loop refactor);
  - a live Phase 0 run after the patch change;
  - the 51-conversation baseline;
  - prompt line count and agent code line count, before and after.
- [ ] Fill in Results, update the ROADMAP and run `/handoff`.

## Acceptance criteria
- Phase 0 replay is identical after the loop refactor, and no Phase 0 metric drops after the whole phase.
- The 51-conversation baseline doesn't regress (same model, same number of runs).
- The restart test, the four cancellation tests and the chip-removal test pass.
- Total prompt lines don't grow. Agent code grows by less than about 10%, and shrinks where hand-written plumbing is removed.
- The graph diagram (`get_graph().draw_mermaid()`) shows the subgraphs, the loop and the pause. Save it in `docs/` for the Phase 5 explainer.

## Risks and notes
- **psycopg 3 sits alongside psycopg2.** That's fine, but pin both versions and check the Docker image size.
- **A paused graph waits forever if the user never answers.** On the next message in the same thread, discard the pending pause.
- **Streaming must not bypass guardrails.** Stream only step labels and the final reply, never raw model output.

## Results
_Fill in during the phase._
