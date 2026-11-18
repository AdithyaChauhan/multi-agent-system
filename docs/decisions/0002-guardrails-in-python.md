# 0002. Guardrails live in Python, not in prompts or model tools
- **Status:** Accepted, implemented on `simplify-agents`
- **Date:** 2026-11-18 (records the design of that branch)

## Context
The earlier work in progress let the model call a `cancel_order` tool whose `user_id` came from the model. It also ran keyword lists in front of the router to detect safety and legal threats, and those misfired: "issue" was read as "sue", and "fire tv stick" raised a safety alarm.

## Decision
- Sign-in, order ownership, cancellation and escalation are enforced in Python.
- Every order lookup filters by the signed-in user id from the session, never from model output.
- The graph never cancels anything. It returns `action_required: confirm_cancel`. Only `POST /cancel-order`, called when the user presses Yes, changes an order, and only if it belongs to that user and is still processing.
- Safety risks, legal threats and ticket-worthy issues reach tickets through fixed rules in `route()` and `route_support()`.
- No ToolNodes. Agents call their tools directly, because the data is already fetched in code.

## Consequences
- The model can misunderstand a message, but it can't act on another user's data or cancel anything.
- Safety detection depends on the router's `risk` field. 0008 closes that gap.
- If the capstone brief requires a ToolNode in every agent (commit `bd804ce`), this doesn't meet it. Check the brief before Phase 5.

## Alternatives considered
- Model-callable action tools that take a user id: rejected, because the model could act for another user.
- Keyword gates in front of the router: removed because of false positives.
