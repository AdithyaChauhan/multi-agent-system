# Phase 5: Ship and showcase
- **Status:** In progress (started 2026-11-23)
- **Branch:** `phase-5-ship`, off `phase-4-reliability`
- **Decisions:** [0013](../decisions/0013-judge-facing-priorities.md), [0016](../decisions/0016-product-qa-and-demo-shoppers.md)
- **The user's choices (2026-11-23):**
  - free hosting kept awake (Render + Neon);
  - safety alerts to a Discord channel;
  - LangGraph tool calling only for safe, read-only lookups.
- **The user's choice (2026-11-24):** stay on Groq's free tier. At 20 simultaneous users most replies are the fast "busy" reply; the load test and the docs report the answered share plainly instead of buying capacity. Write it up as an ADR at handoff.

## Goal
Meet the definition of done in `ROADMAP.md`. A judge opens the README, clicks a live link that works, tries every flow without an account, and sees measured numbers.

## Tasks
- [x] **One-click demo shopper:** `POST /auth/demo-shopper`, five orders each, 5 per IP per hour, purged after 2 days. The login page button and the chat's "things to try".
- [x] **Product Q&A:** a read-only ToolNode loop (`app/agents/product_qa.py`), the router's `about_shown`, and `names_a_search` so brands, budgets and new product words still search. Tool record and replay in `call_llm`.
- [x] **Robustness found on the way:** Groq `output_parse_failed` is retried instead of returning a 500, and a malformed tool call answers without tools.
- [x] **Deploy setup:**
  - `render.yaml` (one free service plus Neon);
  - mock carrier at `/carrier`;
  - migrations at start;
  - `keep-warm.yml` and `scripts/load_live_db.sh`;
  - the Kubernetes CI job on GitHub-hosted runners.
- [x] **Docs:** `docs/SETUP.md`, the README showcase, ADR 0016, and the regenerated graph diagram.
- [x] **Root cleanup:** 8 files removed, 11 cache folders deleted, history reports moved to `docs/history/`.
- [x] **Final run 1** (51 conversations, gpt-oss-20b): 48/51. The Q&A set 6/6; adversarial 14/15 (a12 is routing, reported).
- [ ] **Final runs 2 and 3:** live, `--mode live`, about 196K tokens each. One per key per day: `--env-file .env.eval` for one of them. The 2026-11-24 attempt was stopped and doesn't count (see Results): it found the `functions.` tool-name bug.
- [ ] **Load test:** built (`eval/loadtest/`: `locustfile.py`, `run.sh`, `summarize.py`, `SMOKE=1` for a 0-token run). First run 2026-11-24 failed the latency target and found the SDK retry wait (fixed). Rerun after the fix when gpt-oss-20b quota allows.
- [x] **The CI simulation passes** with the new cassettes (2026-11-23, `python:3.12-slim`): retrieval 0.979/0.933, baseline 48/51, adversarial 14/15 (a12 routing), Q&A 6/6, gate passed. It found the replay wrapper bug fixed in `96b74bf`.
- [ ] `docs/CASE_STUDY.md`: drafted 2026-11-24; release numbers marked pending.
- [ ] **Visual explainer:** built steps lose "Proposed", add the tool loop and hybrid search, measured numbers, republish to the same URL (see `docs/visual/README.md`).
- [x] **Grafana panels:** a "Demo never breaks" row: turn latency p50/p95 (new `chat_turn_seconds`, which times `/chat/stream` to the reply), turns by outcome (new `chat_turns_total`), fallbacks, cache hit rate, limited turns. Prometheus also scrapes the load-test container.
- [ ] **Go live with the user** (step 7 of the plan): push after asking, PR to `main`, CI green, merge; the user creates Neon, Discord and Render and pastes the secrets; `bash scripts/load_live_db.sh`; check the live link end to end; time the Discord alert.
- [ ] Final scorecard in the ROADMAP; Results; `/handoff`.

## Acceptance criteria
- The live link works, and search, an order and a cancel can be tried within 2 minutes without an account.
- Baseline ≥ 47/51 averaged over 3 live runs; 0 failures on the adversarial safety cases; the Q&A set passes.
- p95 under 3 s and under 1% errors in the 20-user load test, with the share of real answers reported next to them (free-tier ceiling, the user's choice 2026-11-24).
- A safety report reaches Discord within 1 minute.
- Prompts under 40 lines (router 27, Q&A 6); the graph diagram shows the subgraphs, the loop, the pause and the tool loop.
- The case study and the visual explainer show measured numbers.

## Results (so far)
- **Live response times** (gpt-oss-20b, 2026-11-23):
  - product search turn: median 2.5 s;
  - question about shown products: median 2.4 s;
  - about 0.8 s per model call;
  - repeated questions are answered from the cache in under 0.1 s.
- **Final run 1 caught a regression.** It first scored 45/51: the router flagged "what about Bajaj" and "philps air purifier" as questions about the cards. `names_a_search` fixed it, and the run, re-scored in fill mode at 0 extra tokens, is **48/51**. The failures are the same as Phase 4: p03, p10 and s16.
- **Q&A set: 6/6.** In a live check the model used `compare_products` and `get_product_details`, and said "the facts don't mention a warranty" rather than guessing.
- **Data error seen through Q&A:** a heater titled 2000 W carries `watts: 1000`.
- **Tokens on 2026-11-23:** about 196K (run 1, `.env.eval` key), plus about 36K (Q&A), plus about 25K (adversarial).

### 2026-11-24: final checks found four bugs
- **Final run 2, first try:** a short network outage made every call fail with `APIConnectionError`, and the harness still wrote a 1/51 result. 0 tokens. The harness now treats an unreachable Groq like a rate limit (wait 65 s, retry once, then stop) and counts `unreachable_calls`. The result files were deleted.
- **Final run 2, second try, stopped at 23 of 51** (gpt-oss-20b, main key, about 133K tokens, not scored). 9 of 49 router calls came back with the tool name `functions.RouteDecision` instead of `RouteDecision`. The parser rejected them, so the turn became "unclear" and the reply asked the user to clarify (p07, p12, p20, p21, p22 failed that way). No such name appears in run 1's cassettes: the model's behaviour is new. Fix in code (`_salvage` in `app/core/llm.py`): a prefixed name that matches the schema is validated against it; anything else stays a failure.
- **Load-test smoke mode (invalid key, 0 tokens):** a rejected Groq key returned HTTP 500 on every turn. Now it ends the turn with the busy reply at once (all models share the key) and logs `LLM_KEY_REJECTED`.
- **Load test, 20 users, 3 minutes** (`p5-load-20u`, local Docker, gpt-oss-20b first, fallback chain and cache on, main key, `multi_agent_baseline`):

  | | Result | Target |
  |---|---|---|
  | HTTP errors | **0 of 216** | < 1% |
  | p95, all requests | **22 s** (search 31 s, follow-up 22 s, order 18 s) | < 3 s |
  | Chat replies answered | 51 of 175 (29%); 124 busy | |
  | Model calls / tokens / cache hits | 84 / 107.6K / 30 | |
  | Fallbacks | 56 (all per-minute rate limits): to 120b 36, to qwen 20 | |

  - **Why so slow:** the Groq SDK retried each 429 once, after sleeping for `retry-after` (9 s in a traced turn), before our chain could move on. Model-call p95 was 10.9 s. Fixed: `max_retries=0`; the chain's cooldowns already handle 429s.
  - **Why mostly busy:** all 125 rate limits were per minute (gpt-oss-20b and -120b about 7K tokens a minute, qwen on input tokens). Three models give about 22K tokens a minute, about 5 product turns. 20 users with 5–15 s think time ask for far more. This is the free tier's ceiling, not a bug.
  - The rerun after the fix needs fresh gpt-oss-20b quota (the main key spent about 170K on it today).
- **Tests:** 355 pass, coverage 90%, lint clean.
