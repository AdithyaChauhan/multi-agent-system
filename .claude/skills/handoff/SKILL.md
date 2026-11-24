---
name: handoff
description: Save this session's state to the repo docs before the chat ends. Ticks plan tasks, records results, writes ADRs for new decisions, updates the roadmap, adds a progress entry and suggests a commit. Use at the end of every session, when the context is getting long, or when the user says handoff, wrap up, or save progress.
---

# Handoff

1. In the current phase plan (`docs/plans/phase-N-*.md`):
   - tick finished tasks and add any new tasks found during the session;
   - add measured numbers to **Results**, each with the date, model, number of runs and database.
2. If the session made a decision that would be costly to reverse, or easy to undo by accident, write an ADR in `docs/decisions/`: take the next number, use the template in that folder's README, and add it to the index. To reverse an old ADR, write a new one that supersedes it, and change only the old one's Status line.
3. Update `ROADMAP.md`: the "Now" section (current phase, branch, next action, blockers) and the phase status. Change the scorecard's Today column only with measured evidence.
4. Add an entry at the top of `docs/PROGRESS.md`, using the template in that file. Keep it under about 12 lines: numbers and links, not narrative.
5. If the phase is finished, check its acceptance criteria one by one, mark it Done in `ROADMAP.md`, and move anything deferred into a later phase's plan.
6. Never write secrets, keys or `.env` values into any of these files.
7. Show `git status --short` and suggest a commit message (for example `docs: handoff 2026-11-20, phase 0`, or a feature message if code changed). Commit only if the user asks.
8. End by telling the user to type `/resume` in the next chat.
