# Phase 2: LangGraph-native architecture
- **Status:** In progress (plan approved 2026-11-20)
- **Branch:** `phase-2-architecture`
- **Depends on:** Phase 0 (replay makes the refactors cheap to verify) and Phase 1 (committed as `0e9a8e2`; this branch starts from it).
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

## Found in planning (2026-11-20)
- **The 51-conversation baseline is out of date.** It checks `subcategory` in 39 places and `result_subcategory` in 25, and Phase 1 removed that field, so it must be ported before it can give a "before" number.
- **The baseline has no replay mode,** unlike the retrieval eval. Adding one makes every refactor step free to verify.
- **`langgraph-checkpoint-postgres` 3.2.1 needs `langgraph-checkpoint` ≥ 4.3** (4.1.0 is installed), `psycopg` 3 and `psycopg-pool`.
- **`original_preferences` is redundant:** search relaxes a copy, so it always equals `preferences`. Remove it.

## Tasks
Each step is its own commit with tests.
- [x] Plan mode, approved 2026-11-20. Phase 1 committed; branch `phase-2-architecture` created.
- [x] **1. Measuring stick for conversations.**
  - Port the baseline expectations: `subcategory` becomes `product_type`, resolved from `prefs.product` through the catalog; `result_subcategory` becomes `result_type`; `category` is dropped.
  - Add `--mode record|replay` to `run_baseline.py`.
  - Record the "before" run: gpt-oss-20b, 1 run, `multi_agent_baseline`, about 180K tokens.
- [x] **2. Search loop as graph edges:** `search → check → loosen → search`, at most 4 passes. Gate: retrieval replay identical to `v2-combined` and baseline replay identical.
- [x] **3. Subgraph schemas:** product, order and support each declare input and output schemas. Remove `original_preferences`. Gate: both replays identical.
- [x] **4. Checkpointer:**
  - `PostgresSaver` on Postgres, `InMemorySaver` otherwise; thread id = session id;
  - per-turn keys are reset in the turn input;
  - delete `_session_preferences`;
  - restart test;
  - pin the new packages and check the image size.
- [x] **5. Cancellation with `interrupt()`:**
  - a `confirm_cancel` node pauses;
  - `/chat` with `confirm` resumes with `Command(resume={"confirm", "user_id"})`;
  - `cancel_order` re-checks owner and status;
  - `/cancel-order` is deleted, and the UI and baseline harness switch to resume;
  - five guardrail tests.
- [x] **6. Escalation subgraph:**
  - create the ticket, then notify (`ESCALATION_WEBHOOK_URL`, or a WARNING log if unset; it never blocks the reply);
  - used by the safety and support tickets;
  - gate: baseline replay identical.
- [ ] **7. Streaming:** `POST /chat/stream` sends server-sent events: step labels from `stream_mode="updates", subgraphs=True`, then one final reply event. `chat.html` uses it with a fallback to `/chat`.
- [ ] **8. Filter chips with patch extraction (0007):**
  - the model returns only changed fields plus `clear`, and `merge_preferences` merges them in code;
  - `ChatResponse.active_filters`;
  - chip removal re-runs the search with no LLM call;
  - the prompt is rewritten and stays under 40 lines.
- [ ] **9. Measure:**
  - live retrieval on 100 queries (about 220K tokens; no drop below 0.958 / 0.926);
  - live baseline (about 180K tokens; no regression against step 1);
  - prompt and agent-code line counts;
  - the Mermaid graph goes to `docs/architecture/graph.md`.
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
- **Before** (2026-11-20, code `07a0904` = Phase 1 + ported harness, gpt-oss-20b, 1 run, `multi_agent_baseline`): **45/51 conversations, 84/90 turns**, about 186K tokens (main key capped after 40 conversations; the other 11 ran on the `.env.eval` key from a worktree at the same commit). Recorded to `eval/cassettes/baseline_openai-gpt-oss-20b.json`; summary in `eval/baseline_runs/p2-before-combined_summary.json`.
  - p03 "table": shows laptop tables (the YAML kind `table` under laptop stand) instead of "we don't carry furniture". A data fix.
  - p10 "4k monitor": the catalog has one Full HD monitor, so the app says it doesn't carry monitors.
  - p07 "lojitec mouse" and p22 "bajaj smartwatches": the model dropped the brand.
  - p19 "usb hub with ethernet": no results with the model's extraction (today's search finds 10 for product "usb hub" with the feature "ethernet").
  - s16 "resolve support issues": routed to support, not clarify.
- **The retrieval cassettes are stale:** the Phase 1 catalog fixes made after the v2 run changed the `{types}` list in the extraction prompt, so retrieval replay misses on every query. Step 9's live run re-records them. Step 2 was checked another way: old loop against graph loop on all 100 recorded v2 preferences gives identical results and loosening steps (0 tokens).
- **Steps 2–6, baseline replay** (0 tokens, 0 cassette misses): 45/51, identical to the before-run on every turn except the cancel question, which now ends "Do you want to cancel it?" (s08, s09).
- **Postgres checkpointer verified** against `multi_agent_baseline`: filters carry over to a fresh graph and pool (a restart), and a pending cancel question survives a restart and resumes. The saver creates `checkpoints`, `checkpoint_blobs`, `checkpoint_writes` and `checkpoint_migrations` (outside Alembic).
- **Tests:** 242 pass, coverage 92%. The pinned packages install cleanly (`pip check` clean); `uvloop` is Linux-only, so it's skipped on Windows.
