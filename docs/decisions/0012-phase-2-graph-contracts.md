# 0012. Phase 2 graph contracts: state, pause, chips and grounding
- **Status:** Accepted, implemented (Phase 2)
- **Date:** 2026-11-21

## Context
Phase 2 moved hand-written plumbing into LangGraph (0009). Several of the resulting behaviours are easy to undo by accident in a later refactor, and some differ from what 0009 assumed:
- The v3 eval showed the patch-style extraction (0007) sometimes returns a bare type, or no product on a first message.
- An unreachable database at startup silently left the app without its catalog until a restart.
- Two subgraph nodes with the same name break the diagram.

## Decision
- **State:**
  - One checkpointed thread per chat session, `thread_id` = session id, using `PostgresSaver` (`InMemorySaver` off Postgres).
  - The saver owns its four tables through `setup()`, outside Alembic.
  - `router.new_turn()` clears every per-turn key, so only `preferences` carries over between turns.
- **Cancel:**
  - `support_agent.confirm_cancel` calls `interrupt()` and has no side effects before it.
  - `/chat` with `confirm` resumes the thread, only for the session's signed-in owner and only while a question is pending.
  - `cancel_order` re-checks the caller, and the database update re-checks owner and status.
  - There is no `/cancel-order` endpoint any more.
- **Chips:**
  - The extraction model returns only what a message changes (plus `clear`), and `merge_preferences` keeps the rest.
  - A product of another type starts fresh.
  - Removing a chip (`remove_filter`) skips the router and the extraction, and ranks with `order_by_score`: no model call.
- **Grounding:** `ground_product` checks the model's product against catalog words in the shopper's own message:
  - a missed product on a first message is taken from the message;
  - a bare type keeps the kind the shopper named;
  - text fields are cut at a line break or tag.
- **Catalog loading:** `get_catalog()` keeps a catalog only if it has types; otherwise the next call retries. The evals abort if the catalog didn't load.
- **Streaming:** `/chat/stream` uses `stream_mode="tasks"` and sends only fixed step labels plus the final `/chat` body, never model text. Run ids come from a `RunCollectorCallbackHandler` in the config, not `collect_runs()`.
- **Naming:** subgraph node names are unique across the whole graph (`safety_handoff`, `ticket_handoff`), so `draw_mermaid(xray=True)` works.

## Consequences
- Conversations survive restarts and multiple instances. Follow-ups can't lose the product.
- Chip clicks cost no tokens.
- Prompts stay short (68 runtime lines), because product checks live in code and data (0010).
- Agent code grew about 50% (858 → 1,284 lines). Most of that is new features: per-agent schemas, the escalation subgraph, chips, and the pause.
- A new per-turn state key must be added to `new_turn()`, or it leaks into the next turn.

## Alternatives considered
- **Complete filters from the model** (the Phase 1 prompt): this lost the product on follow-ups (q087). Rejected.
- **Prompt rules for the v3 misses:** these are against 0010. They were fixed in code instead.
- **Keeping `/cancel-order` as a wrapper:** a second path to cancel is a second thing to secure. It was removed.
