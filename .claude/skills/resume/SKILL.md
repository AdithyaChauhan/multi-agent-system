---
name: resume
description: Load this project's working context at the start of a session (roadmap status, the current phase plan, the latest progress entries, relevant decisions) and propose the next task. Use at the start of every new chat on this repo, or when the user says resume, continue, or "where were we".
---

# Resume

1. Read `ROADMAP.md`: the "Now" section and the phase table. The current phase is the one marked In progress; if none is, it's the first one marked Not started.
2. Read that phase's plan in `docs/plans/`. Note the unchecked tasks, the acceptance criteria and anything already in Results.
3. Read the two newest entries at the top of `docs/PROGRESS.md`.
4. Read `docs/decisions/README.md`, then only the ADRs that the next task touches.
5. Run `git status --short` and `git log --oneline -5`. Check that you're on the branch named in the plan. If that branch doesn't exist yet, say so; don't create it without asking.
6. If the phase is Not started, switch to plan mode and refine its plan file from the roadmap and the latest progress notes. Get the user's approval before writing code, then mark the phase In progress in `ROADMAP.md`.
7. Report in under 15 lines:
   - where the project stands (phase, and how the last session ended);
   - the next 1–3 tasks from the plan;
   - open questions or decisions only the user can make;
   - the token cost of the next task, if it calls the model (Groq free tier: 200K tokens a day per model).

   Then start the next task, unless a decision is pending.

Don't re-derive what the docs already record. Trust them unless the code contradicts them; if it does, say so and fix the doc.
