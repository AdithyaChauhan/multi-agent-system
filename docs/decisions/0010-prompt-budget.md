# 0010. Fix behaviour in code, data or tests, not with more prompt rules
- **Status:** Accepted
- **Date:** 2026-11-18

## Context
Before `simplify-agents`, prompts had grown to 224 lines, with 38 one-off rules that each overrode the model for one past conversation. They conflicted, and several broke other conversations (`docs/history/SIMPLIFY_REPORT.md`). The user's first goal for the project is not to over-engineer the system prompts.

## Decision
- Each prompt in `app/prompts/` stays under 40 lines and contains no product facts. Facts come from the database (0005).
- When the model gets something wrong, the fix goes, in order of preference, into:
  1. data (a missing type, synonym or attribute);
  2. deterministic code (validation, routing, templates);
  3. a short general rule or example in the prompt, only if it is a rule for a whole class of messages, and only if a measurement shows it helps.
- Never add a prompt rule for a single conversation. Add the conversation to the eval set instead.
- Check prompt line counts at every phase's handoff.

## Consequences
- Prompts stay readable and stable. Behaviour changes show up as code or data diffs, with tests.
- Some model mistakes take longer to fix, because the fix has to be general.
