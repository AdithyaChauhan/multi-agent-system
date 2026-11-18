# 0007. Search state in Postgres; refinements as patches
- **Status:** Accepted
- **Date:** 2026-11-18

## Context
- Follow-up filters live in `_session_preferences`, a dict inside one Python process (`app/main.py`). A restart forgets them, and two replicas don't share them.
- The model returns the complete filter set every turn, so it can drop filters. On 2026-11-18, "what about Logitech" lost both the price cap and "wireless".

## Decision
- A `session_state` table (session id, state as JSONB, `updated_at`) holds the last query, its constraints and the products shown.
- The model returns only what changed (fields to set or unset). Code merges that patch into the stored state.
- The chat UI shows active filters as removable chips. Removing one sends an explicit patch.

## Consequences
- The app becomes stateless, so restarts and multiple replicas are safe.
- A dropped filter becomes visible, and the user can fix it in one tap.
