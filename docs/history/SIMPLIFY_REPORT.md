# Simplification report

Branch `simplify-agents`: 15 commits on top of your work snapshot `e0bdf3c`. Nothing was pushed,
deployed or changed in LangSmith. Details behind every claim here are in `DIAGNOSIS.md` and
`eval/baseline_runs/`.

## 1. Why it was broken

The model ID was fine. The app failed for three reasons:

- **It crashed on startup** after the README's database restore: a "lint fix" commit added SQL that Postgres rejects.
- **It ran out of model quota.** The free Groq tier allows `qwen/qwen3.8-27b` 200,000 tokens a day and 8,000 a minute. The old app spent ~3,600 tokens per product question, mostly re-sending long rule-filled prompts. So it served about two product questions a minute and ~55 a day across all users, then returned errors.
- **The rules fought each other.** The prompt that actually ran came from the LangSmith hub, not the code, and it was older. On top of that, 38 one-off guards each overrode the model for one past conversation. They now broke others: "issue" contains "sue" and was read as a legal threat; "fire tv stick" triggered the safety alarm.

## 2. Before and after

| | Before (`e0bdf3c`) | After (`HEAD`) |
|---|---|---|
| System-prompt text | 224 lines in 8 prompts, 3 of which actually ran from older, different hub copies; plus 957 lines of push scripts | **67 lines in 4 files** (`app/prompts/`), read from disk |
| Steering rules that override the model | 38 | **10** (listed in §3/§4) |
| Keyword lists matched against the user's words | 12 | **0** |
| Exact guardrails (auth, ownership, cancel, escalation) | 10, one of them risky (an LLM-callable cancel tool) | **9**, all deterministic |
| Graph nodes (all graphs, subgraphs expanded) | 41 in 7 graphs | **22 in 4 graphs** |
| Agent code | 2,810 lines | **948 lines** |
| LLM calls per turn (baseline mean) | 2.34 | **2.02** |
| Tokens per turn / per product turn | 2,764 / 3,606 | **1,989 / 2,787** (−28% / −23%) |
| Seconds per turn (mean, unthrottled) | 2.19 | **1.50** |
| Baseline pass rate | **37/51** conversations (73%), 73/90 turns | **43/51** (84%), 80/90 turns, at `8b5c2b8`; see below for later fixes |
| Unit tests | 253 pass, 2 fail, 84% coverage | 175 pass, 0 fail, **90%** coverage |

**How the pass rate was measured. Please read this before quoting it.**

- **One run each, not three.** Qwen's daily quota was used up by the Phase 1 checks (`run_20_tests.py`, `test_live.py`). A full run of the old app costs ~250K tokens, more than one model's daily allowance.
- **Stand-in models.** Before and after both ran on the same key's other Groq models, which have separate quotas: p07–p25 on `openai/gpt-oss-120b`, the other 32 conversations on `openai/gpt-oss-20b`. Each conversation used the same model before and after, so the comparison is fair, but it is not a measurement of qwen.
- **The old app was measured exactly as it ran**, hub prompts included, from a worktree at `4207491`.

**After that run**, I fixed the five regressions it showed (o03, o05, p09, p10, s07) with prompt wording and a clearer ranker question (`44f4792`, `c5f0be9`). I re-tested only the 8 conversations that still failed, plus an 8-conversation regression sample, on gpt-oss-20b:
- 6 of the 8 now pass;
- p10 ("4k monitor") is flaky (the ranker answers it correctly in isolation);
- s16 fails as it did before;
- the sample passed (p01 p02 p12 p22 p23 s10 s13 o01; p22 needed the ranker change).

That is a subset check, not a new pass rate.

**On qwen itself**, checks were limited by its quota:
- the step-4 spot check showed the router misses described in §5;
- `p03` and `p09` pass on the final code, before the quota ran out again;
- in Docker, the full UI-style session (product search → order lookup → support complaint) worked on qwen at `8b5c2b8`, and on the final image with `GROQ_MODEL=openai/gpt-oss-120b`.

## 3. What was removed, and why it was safe

Case IDs are from `eval/baseline_conversations.json`.

- **The runtime hub pull and the silent fallback, plus the seven `push_*.py` scripts.** The file in git is now the prompt that runs. This fixed "calculator" (p20): the hub copy's frozen catalog put calculators in the wrong category.
- **The 235-line preference merge in `extract_preferences` (17 branches).** One structured call now receives the previous turn's filters and returns the complete new ones. Category, subcategory and type are checked against the DB catalog. Multi-turn cases now pass that failed before:
  - p02 "Samsung" after TVs;
  - p18 "what about Bajaj";
  - p12 "gaming ones under 2000";
  - p13 Fire-Boltt;
  - p23 "Sony under 500" → "under 3000".

  The cases these branches were added for still pass: p01 "cheaper", p11, p21 "calling → under 2000", p24.
- **Keyword lists:** `_GREETINGS`, `_NAVIGATION_PHRASES` (and the unclear→product override), `_POLICY_QUESTION_PHRASES`, `_COMPLAINT_KEYWORDS` (and the support→order reroute in `main.py`), `_LEGAL_THREAT_KEYWORDS`, `_SAFETY_KEYWORDS`, the phone/laptop/tablet redirects, `_price_down_words`, and the order-ID regexes and "assistant asked" phrases. The router now returns intent, order, issue and risk in one call, resolving "the tv one" against the user's real orders. Results:
  - Fixed: s10 (an order number given after "which order?" now opens the ticket instead of showing status), s18 ("issue" no longer reads as "sue"), s01 "the tv one".
  - In the subset re-test: p25 ("fire tv stick" is no longer a safety alert).
  - Still passing: s15 (a real fire report gets a critical ticket), r01–r03 greetings and sign-in, s11 policy question, s12 legal threat.
- **Three overlapping fallbacks** (`broaden_search`, `retry_search`, `keyword_recovery`, the post-rank broaden loop) became one loop. It relaxes type → price +25% → brand → keywords, on a copy, so the shopper's own filters survive to the next turn. The "we don't carry Bose" reply, unreachable before, now appears (p22, which covers `test_live` #5 and #7).
- **LLM calls that redid deterministic work:**
  - the order agent's reply and its tracking ToolNode (the data was already fetched; replies are now templates over the DB row);
  - the support classifier (folded into the router);
  - the policy ToolNode and second drafting call;
  - the clarify call (the router writes that reply);
  - the "unavailable" suggestion call.
- **Ranking:** 8 weights, a reviews fetch and a specs fetch (the specs table is empty) became one score (rating, budget fit, brand/feature match) after the LLM ranker.

## 4. What was kept, and why

The real guardrails, all deterministic in code:
- **Sign-in** before order and support (r03).
- **Ownership:** every order lookup is filtered by the signed-in user (o05, s17).
- **Cancellation only after the user presses "Yes"** in the UI (s08 checks the DB before and after; s17 tries another user's order through the endpoint and is refused). The LLM-callable `cancel_order` tool, whose `user_id` came from the model, is gone.
- **Escalation to a human:**
  - safety risk → critical ticket (s15);
  - legal threat → ticket (s12);
  - damaged/defective/wrong item/refund → ticket (s03, s13);
  - one open ticket per order (s13).
- **Catalog scope:** phones, laptops and tablets in the DB are never offered.

The 10 steering rules that remain, all small and catalog- or policy-driven:
- catalog check on extracted values;
- category taken from the catalog;
- single-order auto-select;
- the relaxation loop;
- the "we don't carry X" note;
- the "not every detail matches" header;
- fuzzy brand match;
- the three-factor score;
- order-ID formatting;
- the issue → ticket/drafted-reply mapping.

Also kept: the LLM ranker (it removes wrong-kind items such as mouse pads and cleaning kits), the fuzzy brand matcher (now case-insensitive), monitoring, CI and Helm.

## 5. What still fails or needs you

- **Groq quota: your call.** Qwen hits the free tier's daily cap after ~70 product questions (down from ~55 needed before). A paid Groq tier removes the ceiling.
- **Model choice: your call.** On qwen, 30–50% of structured (tool-call) replies come back malformed on the first try; a single retry recovers them, but each costs time and tokens. On gpt-oss-120b/20b it was 0 of 97. Switching is one setting: `GROQ_MODEL=openai/gpt-oss-120b`. I didn't change the default.
- **Live DeepEval needs a real OpenAI key** as `EVAL_OPENAI_API_KEY` for the `gpt-4o-mini` judge. Your `.env`'s `OPENAI_API_KEY` is the Groq key. Your WIP had silently switched the judge to phrase-matching. Now, without the key, live mode says so and uses the rule-based metrics; fixture mode (CI) passes 12/12.
- **Three runs per side** weren't possible, for the quota reasons above. To repeat on qwen when it has quota (~180K tokens per run): `python eval/run_baseline.py --label after_qwen --runs 1`.
- **Still failing on the final code (subset checks):**
  - p10 "4k monitor" (flaky ranker);
  - s16 "resolve support issues" (the UI's quick-action phrase goes to support and asks which order, not to clarify; failed before too).

  On qwen, the router occasionally sent "show me some TVs" (p02) to an empty extraction and once sent "ORD-2004" after "which order?" to product (s10); both passed on re-test.
- **Reverted: nothing.** The regressions were fixed forward, see §2.
- **Trade-off to confirm:** there are no ToolNodes any more. If your capstone brief required "every agent has a ToolNode" (commit `bd804ce`), that requirement is no longer met. They were a second LLM round-trip to fetch data the graph already had.
- **Not fixed, noted in `DIAGNOSIS.md`:**
  - `seed.py`'s ORD-9901 collides with the backup (live-eval tc_008);
  - preferences live in a process-global dict;
  - catalog mislabels (a cleaning kit under "monitor").
- **Your environment:**
  - `.env` still has `LLM_MODEL`/`MODEL_NAME` set to a retired model. Nothing reads them, but they should go.
  - Your existing `multi_agent_db` Docker volume was not touched. I restored the README backup into a separate database, `multi_agent_baseline`, in the same container, and the baseline needs it. Containers are stopped.

## 6. Numbers for the portfolio

Measured, and labelled as such:
- "Rewrite raised a 51-conversation regression baseline from 37 to 43 passing (one run each, Groq gpt-oss-20b/120b)."
- "28% fewer LLM tokens per message (2,764 → 1,989) and 2.34 → 2.02 LLM calls per message on the same baseline."
- "Agent code cut from 2,810 to 948 lines; 38 hand-written override rules to 10; 224 lines of prompt to 67."

Sentences in the Multi-Agent case study (`../Portfolio-main/preview.html`) that are no longer true:
- "**7 LangGraph state graphs**": now 4.
- "**5-step query relaxation**": 4 optional filters in one loop (it was already 4 in your WIP).
- "**Deterministic safety gates** keep auth and cancellation logic in Python, never in the LLM": auth and cancellation are still in Python, more strictly than before. The safety *detection*, however, is now the router LLM's `risk` field; only the escalation is deterministic.
- Request-flow diagram "**User → Safety Gate → LLM Router**": there is no gate before the router any more.

Already untrue before this work:
- "**GPT-4o-mini**" (skills and project tags): the app has used Groq since your WIP.
- "**80% DeepEval quality bar**": in CI it is a phrase-match check, not an LLM judge, unless `EVAL_OPENAI_API_KEY` is set.
