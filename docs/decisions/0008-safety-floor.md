# 0008. Safety: model risk flag plus an escalate-only pattern
- **Status:** Accepted
- **Date:** 2026-11-18

## Context
Safety detection is only the router model's `risk` field (0002). The old keyword gate was removed because it fired on product names ("fire tv stick") and read "issue" as "sue". If the model misses a real report, no critical ticket is opened.

## Decision
- Add a short, high-precision pattern ("caught fire", "burned my", "electric shock", "sparks from" and similar), checked alongside the router.
- If the model or the pattern flags safety, the turn escalates.
- The pattern can only escalate; it never routes a message anywhere else.
- Tests cover real reports and product names such as Fire TV and Fire-Boltt.

## Consequences
Fewer missed safety reports, at the cost of a rare false escalation, which only creates a ticket.
