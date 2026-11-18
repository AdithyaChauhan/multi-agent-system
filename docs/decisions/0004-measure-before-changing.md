# 0004. Evals gate every change to prompts, search, data or models
- **Status:** Accepted
- **Date:** 2026-11-18

## Context
The `simplify-agents` work caught its regressions (o03, o05, p09, p10, s07) only because a 51-conversation baseline existed. CI's DeepEval gate is phrase matching unless `EVAL_OPENAI_API_KEY` is set. The Groq free tier (200K tokens a day per model) limits how often live runs can happen.

## Decision
- Phase 0 builds the measuring stick before any search work:
  - about 100 labelled product queries with the product ids that should come back;
  - a retrieval scorer (recall@5, precision@3, MRR, empty-result rate);
  - record and replay for LLM calls, so reruns are free and give the same answers.
- Every change to prompts, search, data or models is measured before and after, on the same queries, model and database. The numbers go in the phase plan's Results section.
- Every reported number says how it was measured: model, number of runs, database. A single run is labelled as a single run.

## Consequences
- The first phase ships no user-visible change. Every later decision has a number behind it.
- Token use is planned: replay mode in CI, live runs on the gpt-oss models or spread across days.
