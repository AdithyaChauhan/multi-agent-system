# Phase 5: Ship and showcase
- **Status:** Done (2026-11-23 to 2026-11-26)
- **Branch:** `phase-5-ship`, off `phase-4-reliability`, merged into `main` as PR #3 (2026-11-24). Since then `main` is what's live: each change is a short branch and a PR (the Neon fix was PR #4).
- **Live:** https://multi-agent-chatbot-58ur.onrender.com (Render free, Neon free, both in Singapore)
- **Decisions:** [0013](../decisions/0013-judge-facing-priorities.md), [0016](../decisions/0016-product-qa-and-demo-shoppers.md), [0017](../decisions/0017-free-tier-capacity.md), [0018](../decisions/0018-machine-independent-replays.md), [0019](../decisions/0019-main-is-live.md), [0020](../decisions/0020-replies-claim-only-what-code-checked.md)
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
- [x] **Final run 2** (2026-11-24, `.env.eval` key): 48/51. The first 2026-11-24 attempt was stopped and doesn't count (it found the `functions.` tool-name bug). Runs 1 and 2 measured the old header: **38/51** each under the false-claim check, so they don't count toward the release average (the user's choice, ADR 0020).
- [x] **Three live runs of the fixed code** (`--mode live`, about 196K tokens each, one per key per day; Groq's daily quota resets at about 05:30 IST). **Run 3: 48/51** (2026-11-25, main key, `807c3dc`). **Run 4: 48/51** (2026-11-26, main key) and **run 5: 48/51** (2026-11-26, `.env.eval` key), both on `d836c6e` (the same app code). **Average 48/51.**
- [x] **Load test:** built (`eval/loadtest/`: `locustfile.py`, `run.sh`, `summarize.py`, `SMOKE=1` for a 0-token run). First run 2026-11-24 failed the latency target and found the SDK retry wait (fixed). **Rerun 2026-11-25: p95 1.3 s, 0 of 377 requests failed, 14% of chat replies real answers** (see Results).
- [x] **Honest product replies** (2026-11-25, found by the user on the live site: "hdmi cables" said "These don't match everything you asked for" over three HDMI cables). The header came from the ranker's `exact` list, which gpt-oss-20b leaves empty in 65% of its recorded answers. The header is now "Here's what I found:"; only the brand note and "I widened…" say something is missing. A new harness check fails any reply that claims a mismatch the shown products don't have. Re-recording found a second flake, fixed in code: `asks_about_shown` (see Results).
- [x] **The CI simulation passes** with the new cassettes (2026-11-23, `python:3.12-slim`): retrieval 0.979/0.933, baseline 48/51, adversarial 14/15 (a12 routing), Q&A 6/6, gate passed. It found the replay wrapper bug fixed in `96b74bf`.
- [x] `docs/CASE_STUDY.md`: drafted 2026-11-24; finished 2026-11-26 with runs 4 and 5, the average and the keep-awake finding.
- [x] **Visual explainer** (2026-11-25, version 3 at the same URL): the Today / Proposed switch removed; stories rebuilt from the code on `main` (hybrid search and the search loop, the Q&A tool loop, the `interrupt()` pause, the escalation subgraph with the Discord alert, the safety floor); a last screen of six measured numbers. Republished 2026-11-26: the last screen shows the 3-run result (48/51 each) and the median turn of runs 3–5 (1.8 s).
- [x] **Grafana panels:** a "Demo never breaks" row: turn latency p50/p95 (new `chat_turn_seconds`, which times `/chat/stream` to the reply), turns by outcome (new `chat_turns_total`), fallbacks, cache hit rate, limited turns. Prometheus also scrapes the load-test container.
- [x] **Go live with the user:** PR #3 merged (`1b26114`), CI green on GitHub; Neon loaded with `scripts/load_live_db.sh`; Render deploys `main`; the live link checked end to end; Discord alerts arrive. The first live check found a fifth bug (Neon closes idle connections), fixed in PR #4 (`42ce007`). See Results.
- [x] **CI green on GitHub's runners**, for the first time: four problems the local simulation had hidden, fixed (see Results, ADR 0018). 5 green runs in a row since.
- [x] **`LIVE_URL` repository variable** set by the user (2026-11-25): keep-warm now pings the live site every 10 minutes.
- [x] **Removed the stale `KUBECONFIG` secret** (the user, 2026-11-25): it pointed at an EKS cluster that no longer exists, and stage 6 printed that address in a public log.
- [x] `eval.yml` removed (2026-11-25): it named the dead self-hosted `minikube` runner, and on `ubuntu-latest` it would have had no app to call (the live site ignores its `X-User-ID`). Live evals run from this machine.
- [x] Deleted the local branch `backup/phase-5-ship-before-rewrite` (2026-11-26, the user's go-ahead) once the user was happy with the rewritten history (commit messages carry no Claude attribution, 2026-11-24).
- [x] **A keep-awake that works** (2026-11-26): GitHub ran `keep-warm.yml`'s 10-minute schedule only every 6 to 10 hours, so the free service slept and a first visit took about a minute. The user added an UptimeRobot monitor (every 5 minutes, email alerts). Its free check sends `HEAD`, which `/health` rejected with a 405; `/health` now accepts `HEAD` too (with a test).
- [x] `docs/PROJECT_PROMPT.md` (the user's briefing prompt for a new chat) brought up to date and committed.
- [x] Final scorecard in the ROADMAP; Results; handoff (2026-11-26).

## Acceptance criteria
- The live link works, and search, an order and a cancel can be tried within 2 minutes without an account.
- Baseline ≥ 47/51 averaged over 3 live runs; 0 failures on the adversarial safety cases; the Q&A set passes.
- p95 under 3 s and under 1% errors in the 20-user load test, with the share of real answers reported next to them (free-tier ceiling, the user's choice 2026-11-24).
- A safety report reaches Discord within 1 minute.
- Prompts under 40 lines (router 27, Q&A 6); the graph diagram shows the subgraphs, the loop, the pause and the tool loop.
- The case study and the visual explainer show measured numbers.

**Status (2026-11-26): all met.**
- live link and judge path: **met** (10 s, see Results);
- 3 live runs of the fixed code: **met**, 48/51 in each (runs 3, 4 and 5). Runs 1 and 2 of the old code: 48/51 then, 38/51 under the false-claim check; they don't count (ADR 0020);
- adversarial safety cases and Q&A: met in replay (local, 2026-11-25, with the new check) and in CI on PR #6;
- load test: **met** (p95 1.3 s, 0 errors; 14% real answers, the free-tier ceiling);
- Discord within 1 minute: **met**;
- prompts and diagram: met;
- case study and explainer: **met** (both updated 2026-11-26 with the 3-run result).

## Results
### 2026-11-26: runs 4 and 5 of the fixed code, 48/51 each; Phase 5 done
- **Final run 4** (`p5-final-r4`: gpt-oss-20b, `--mode live`, 1 run, local app on `multi_agent_baseline`, main key, 12:04–12:30 IST, `d836c6e`): **48/51** (p03, p10, s16), 87 of 90 turns, 0 false claims, 0 rate limits. 2.02 model calls and 2,190 tokens per turn, median 1.7 s per turn; about 197K tokens.
- **Final run 5** (`p5-final-r5`: the same, with `--env-file .env.eval`, 12:31–12:58 IST): **48/51** (p03, p10, s16), 87 of 90 turns, 0 false claims, 0 rate limits. 2,191 tokens per turn, median 1.7 s; about 197K tokens.
- **Release average, runs 3–5: 48/51** (target ≥ 47/51). The same three conversations failed in all three runs, so the misses are the known gaps, not chance.
- A 0-token replay before the runs also gave 48/51, so the setup matched run 3's.
- **Keep-awake:** the live site's first `/health` of the day timed out after 60 s and answered after 38 s (the service waking). GitHub's keep-warm schedule had run only 4 times in 2 days. UptimeRobot's first checks were "502" (waking) and then "405" (its `HEAD` check); fixed in `/health`.
- **Tokens on 2026-11-26:** about 197K on each key.

### 2026-11-25 (later): the fix is live; run 3 of the fixed code 48/51
- **PR #6** (`807c3dc`, merged as `1082d60`): CI green on GitHub (lint, unit tests, replay evals, Docker build; publish and deploy skipped on a PR).
- **Live check after the deploy:** "hdmi cables" answers "Here's what I found:" over three HDMI cables. "electric kettle", then "does the first one come with a warranty?", goes to the Q&A loop: "The facts don't mention a warranty for the Tesora 1.8L Stainless Steel Electric Kettle."
- **Final run 3** (`p5-final-r3`: gpt-oss-20b, `--mode live`, 1 run, local app on `multi_agent_baseline`, main key, 15:27–15:54 IST, code `807c3dc`): **48/51** (p03, p10, s16, the known three), 87 of 90 turns, **0 false claims**, 0 rate limits, 0 cassette misses. 2.02 model calls and 2,184 tokens per turn, median 1.9 s per turn; 196.5K tokens in all.
- **Counting the runs** (the user's choice, Option B): three live runs of the fixed code, recorded in ADR 0020. Runs 1 and 2 stay below with both scores.
- **Groq's daily quota resets at a fixed time,** about 05:30 IST (00:00 UTC), not over a rolling 24 hours: the main key ran run 3 at 15:27 with 0 rate limits, less than 24 hours after its heavy use ended. Both keys are full again after 05:30.
- **Tokens on 2026-11-25, main key:** 196.5K (run 3), under 1K (probe).

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

### 2026-11-24 (evening): final run 2, CI on GitHub, the live site
- **Final run 2: 48/51** (gpt-oss-20b, live, 1 run, `.env.eval` key, `multi_agent_baseline`, current `main`):
  - 198.8K tokens; 2.04 model calls and 2,209 tokens per turn; median 1.97 s per turn; 0 rate limits;
  - the failures are the same as run 1: p03 "table", p10 "4k monitor", s16;
  - the model sent the `functions.RouteDecision` name 10 times; all 10 were salvaged, none lost.
- **CI on GitHub's runners failed four ways that the local simulation hid** (all fixed, ADR 0018):
  1. the runner's newer `pg_restore` sent `SET transaction_timeout`, which Postgres 15 rejects: the fixture is now restored with the database container's own client;
  2. `run_split.py` strips `GROQ_API_KEY` from its child runs, and CI has no `.env`: replay runs get a placeholder key;
  3. a user's seeded orders shared one timestamp, so their order in the router prompt depended on storage order, which shifts as the harness updates rows: `fetch_user_orders` breaks ties by id, and `scripts/untie_order_times.py` spaced tied times 1 µs apart (the eval users in the order their recordings saw, recovered by matching every recorded router call's key, 0 tokens);
  4. CI recomputed every embedding on the runner's CPU; the last digits differed from this machine and reordered near-tied smartwatches, so q05 missed its ranker recording on 3 of 6 runs. Now the fixture carries the product vectors (0.7 → 2.6 MB), and the 166 query vectors are recorded (`eval/cassettes/query_vectors.json`). A replay computes no embeddings; checked with the model blocked (offline, empty cache).
  - The simulation missed them because it copied the working folder (`.env` included) and used Debian's Postgres 15 client and this machine's CPU. Simulate from `git archive HEAD` in the CI images instead.
  - Two dead ends, for the record: tied order times weren't q05's cause, and neither was the embedding-model cache (the 4-of-4 pattern was chance). The annotation that named the missed call settled it.
  - Since the fix: **5 green runs in a row** (PR runs `23d6fb2`, `249cf91`, `55026e4`; `main` after each merge, `1b26114` and `42ce007`). On `main` all six stages pass; the image is published to GHCR; stage 6 skips the live deploy (its `KUBECONFIG` points at a deleted EKS cluster).
- **Neon** (free, `aws-ap-southeast-1`, Postgres 18.7, pgvector 0.8.7) loaded with `scripts/load_live_db.sh`: 1,350 products with vectors, 2,315 orders, 0 tied order times, migrations at head (`c3a9d2e7f4b1`). The connection string is the direct (unpooled) one: the checkpointer uses prepared statements.
- **The first live check found a fifth bug:** HTTP 500 on the first turns after Neon suspends (5 idle minutes), from the checkpointer pool's dead connections. Reproduced by suspending Neon through its API between two messages: 2 of 3 messages failed before the fix, 3 of 3 passed after it (`check=ConnectionPool.check_connection`, `max_idle=240`). PR #4.
- **The live site** (Render free + Neon, 2026-11-24/25, gpt-oss-20b with the fallback chain, main key):

  | Check | Result |
  |---|---|
  | messages right after Neon suspends | 3 of 3 pass; the first takes 2.4 s while Neon wakes |
  | `X-User-ID` impersonation | ignored: anonymous, asked to sign in |
  | judge path: demo shopper → search → question → order → cancel + Yes | **10 s** in total; turns 0.2–4.7 s |
  | `/chat/stream` (the chat page) | 4 step labels, then the reply |
  | "my charger caught fire" | a critical ticket; the Discord alert is posted before the reply, which came 1.7 s after sending; it arrived in #general |
  | "my steam iron arrived damaged" | a medium ticket; its alert arrived too |

- **Tokens on 2026-11-24:**
  - main key: about 133K (the stopped run 2), about 108K (the load test, three models), about 27K (a smoke run whose invalid key didn't apply), about 20K (live checks);
  - `.env.eval` key: 198.8K (run 2).
- **Tests:** 361 pass, coverage 90%, lint clean, `actionlint` clean on `ci.yml`.

### 2026-11-25: a false claim on half the product replies; the load test meets its target
- **Found by the user on the live site:** "hdmi cables" showed three HDMI cables under "These don't match everything you asked for, but they're the closest options we have".
  - **Cause:** the ranker answers `same_kind` and `exact`, and `format_recommendations` printed that header when no shown product was in `exact`. gpt-oss-20b leaves `exact` empty in 65% of its recorded answers (60 of 92 in the conversation cassette, 119 of 185 in retrieval; gpt-oss-120b 26%), matching results included. For "hdmi cable" it answered `same_kind: [1..10], exact: []`.
  - **Why the evals missed it:** they checked routes, filters and the products shown, never the reply's first line. "I want to buy headphones under 2000" passed with three headphones under 2000 below the header.
  - **Size:** in final run 2, 25 of 43 product replies carried the header. The new check calls 13 of them certainly false (14 in run 1), in 10 conversations. Under the check, runs 1 and 2 score **38/51**, not 48/51.
  - **Fix (the user's wording):** the default header is "Here's what I found:". The brand note and "I widened…" stay, because code checks both. The ranker's `exact` now only orders results. A later change can decide `exact` in code from the typed catalog and drop it from the ranking prompt (that needs the ranker calls re-recorded).
  - **New harness check** (`false_mismatch_claim` in `eval/run_baseline.py`): a product reply fails if its first line claims a mismatch while every shown product is the kind asked for and meets the brand, price and rating asked for. Requests with features are skipped, because the harness can't check them.
  - **Re-recording:** the router reads the previous reply, so the new header made 27 router recordings miss (20 baseline, 7 Q&A). Filled on the `.env.eval` key: 31 calls, 36.5K tokens.
- **A second flake, found by the re-recording:** q04 "does the first one come with a warranty?" lost `about_shown` and searched again ("I couldn't find any electric kettle…"). The header didn't cause it: the same input gave `about_shown=true` 8 of 8 times (4 with each header, about 20K tokens), so the recorded call was a 1-in-5 sample. Fixed in code, not by re-recording until it passed: `asks_about_shown`, called by the router, takes the model's flag or a message that points at the list ("the first one", "which of these"), and either way needs no brand, budget or product word. It changes no turn in the baseline or attack sets: only q01, q02, q04 and q06 point at a list after a listing, and all four are real questions.
- **Replay on the fixed code** (local, `multi_agent_baseline`, gpt-oss-20b cassettes, with the new check): baseline **48/51** (p03, p10, s16, as before), 0 false claims, 0 misses; adversarial 14/15 (a12 routing, reported); Q&A **6/6**; retrieval unchanged (0.979 / 0.933 / 1.0); `ci_gate.py` passed.
- **Decided by the user:** three new live runs of the fixed code (see the entry above and ADR 0020).
- **Load test rerun** (`p5-load-20u-r2`: local Docker, 20 users, 3 minutes, gpt-oss-20b first with the fallback chain and the cache on, `.env.eval` key, `multi_agent_baseline`; the image predates the header fix, which doesn't touch latency):

  | | First run (2026-11-24) | Rerun | Target |
  |---|---|---|---|
  | HTTP errors | 0 of 216 | **0 of 377** | < 1% |
  | p95, all requests | 22 s | **1.3 s** | < 3 s |
  | p95, search step | 31 s | 3.3 s | |
  | Chat replies answered | 51 of 175 (29%) | 42 of 306 (14%) | reported |
  | Model calls / tokens / cache hits | 84 / 107.6K / 30 | 73 / 96.1K / 15 | |
  | Fallbacks | 56 | 13 (all rate limits) | |

  The answered share fell because the busy reply now returns at once, so the simulated users send more turns in 3 minutes, while the free tier answers about the same number.
- **Tokens on 2026-11-25:** `.env.eval` key: about 96K (load test, three models), 36.5K (fill), about 20K (router check), under 1K (quota probe). Main key: under 1K (quota probe).
- **Tests:** 369 pass, coverage 90%, lint clean.
