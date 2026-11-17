# Diagnosis: why the multi-agent chatbot is broken

Branch `simplify-agents`, starting from `c8a0fa6` (the uncommitted work snapshot: OpenAI → Groq switch).
Everything below was checked on 2026-11-17 against the real model, the real database restore and the
real code. Nothing was pushed, deployed or changed in LangSmith. `file:line` references are to `c8a0fa6`.

## Summary

The model ID is fine. The app breaks for four reasons, in the order a user would hit them:

1. **It doesn't start** after the README's database restore. A startup "migration" added by a commit
   titled *Fix CI lint and coverage blockers* issues SQL that Postgres rejects.
2. **It stalls after two product questions a minute.** The Groq key is on the free tier
   (8,000 tokens/minute, 1,000 requests/day). A product turn makes 3 calls that send ~3,650 tokens, mostly
   fixed system-prompt text, so the third product turn in a minute waits 10–14 s per call and takes ~30 s.
3. **The prompt that runs is not the prompt in the code.** Product extraction and support resolution are
   pulled from the LangSmith hub at runtime. The hub copies are older: the product one has a frozen catalog
   that disagrees with the database ("calculator" returns nothing) and lacks the last four rules that were
   added to the code copy as fixes.
4. **The guards fight each other.** Each fix added a rule for one conversation; several now cancel out.
   The three-way "we don't carry Bose" reply can't be reached because an earlier relaxation step already
   dropped the brand, and keyword lists misfire ("issue" contains "sue", which reads as a legal threat).

## How this was checked

| Check | Result |
|---|---|
| Groq model list (`GET /openai/v1/models`) | `qwen/qwen3.8-27b` is **active**. No change needed. Moved to one config value, `app/core/config.py: GROQ_MODEL`. |
| Groq limits (response headers) | 1,000 requests/day, 8,000 tokens/minute for this model and key. |
| `.env` | `LLM_MODEL` / `MODEL_NAME` = `llama-3.3-70b-versatile` (retired on Groq, but **not read by any code**). `OPENAI_API_KEY` holds the Groq key; no OpenAI key is available. |
| `pytest -m "not integration"` (CI settings) | 253 passed, **2 failed**, coverage 84%. Both failures come from the WIP snapshot (see B5). |
| Stack per README (docker compose + restore + taxonomy SQL) | App **crash-loops on startup** (B1). Works after `alembic upgrade head`. Restored into a separate database `multi_agent_baseline`; the existing `multi_agent_db` volume was left untouched. |
| `scripts/run_20_tests.py` | **11/20** (last saved run: 18/20). 8 failures are 30 s client timeouts from rate limiting (B2), 1 is "calculator" (B3). |
| `test_live.py` | **8/10**. Both failures are the unreachable brand reply (B4). |
| `test_suite_results.txt` (33/34) | The 34-case script is not in the repository or its history, so that run can't be repeated. Its cases were rebuilt into the baseline. |
| LangSmith hub | Read-only `pull_prompt(<name>:latest)` for all 5 prompts. Every hub copy differs from its code copy. |

## What breaks

| # | Symptom | Root cause | Where |
|---|---|---|---|
| B1 | Following the README, `docker compose up` gives a crash-looping app: `column "safety_alert" is of type boolean but default expression is of type integer`. | `ensure_support_ticket_priority_column()` runs at import time and issues `ALTER TABLE support_tickets ADD COLUMN safety_alert BOOLEAN DEFAULT 0`. SQLite accepts it; Postgres doesn't. The README restore leaves the DB at alembic `c8cdf9913d44`, before the `safety_alert` migration, and the README never says to run `alembic upgrade head`. `alembic.ini` also hard-codes `localhost:5432/multi_agent_db` (compose publishes 5433) and ignores `DATABASE_URL`. Added in `b46591c` *Fix CI lint and coverage blockers*. | `app/db/migrate_schema.py:71-80`, called from `app/main.py:161`; `alembic.ini:89`; README "Restore the database" |
| B2 | After two product questions, each turn takes ~30 s; `run_20_tests.py` times out on 8 of 20. Server log: router call 0.6 s on the 1st turn, 10–14 s from the 3rd turn on. | Free-tier Groq quota: 8,000 tokens/min. One product turn = router (1,460 tokens) + extraction (1,665) + ranking (520) ≈ **3,650 tokens**, of which ~3,100 is fixed system-prompt text resent on every call. The third product turn in any minute gets HTTP 429; `langchain-groq` retries silently (default `max_retries=2`) after the server's retry-after. Whole-app capacity is about two product turns per minute, shared by all users. The 1,000 requests/day cap is ~330 product turns per day. | Prompt sizes: `app/agents/router.py:26-95` (code copy), hub `product-extraction-prompt`; one `ChatGroq` per agent |
| B3 | "calculator" → "I couldn't find any products…" (`run_20_tests` #18). | At runtime `extract_preferences` uses the **hub** prompt, not the code prompt. The hub copy has a catalog snapshot frozen when it was pushed. It lists `calculators` under Electronics; the database has calculators under Office Products / `office electronics`. The model obeys the prompt, the search returns 0, and relaxation never touches category/subcategory. Three related facts: (a) the dynamic `PROMPT_CATALOG` from the DB (`95987fb`) only runs when LangSmith is down; (b) four rules added to the code copy as fixes (`916d676` navigation filler, `e7e95d7` "… ones/type", the need/goal rule, the absent-product rule) never run in production; (c) `b46591c`, titled as a lint fix, switched product extraction and support resolution back to the hub after `bc1ccff`/`180e93e` had bypassed it. | `app/agents/product_agent.py:243-247`, `app/agents/support_agent.py:427-431`, `app/core/prompt_loader.py:22-52` |
| B4 | "bose speakers" and "bajaj smartwatches" show other brands under "I found close matches after broadening a few optional filters". The user is never told the brand isn't stocked (`test_live` #5, #7). | `RELAXATION_ORDER` relaxes `brand` before giving up, so `respond_no_results`' three-way brand reply (`649dfb8`, `c7de56a`) only runs when the whole subcategory is empty. The WIP snapshot also replaced "I relaxed: brand" with a generic sentence, so nothing says the brand was dropped. | `app/agents/product_agent.py:181-186`, `:589-645`, `:660` |
| B5 | 2 unit tests fail. | The WIP snapshot removed `"subcategory"` from `RELAXATION_ORDER` and reworded the relaxed-results header; the tests still expect the old behaviour. | `tests/test_agents_deep.py:280`, `tests/test_product_agent_nodes.py:419` |
| B6 | "I have an issue with my order" opens a P2 ticket with no order attached instead of asking which order. | `_LEGAL_THREAT_KEYWORDS` uses substring matching and contains `"sue"`, which is inside "is**sue**". A legal threat skips the ask-for-order step and escalates. Same pattern: "court" matches "courtesy". | `app/agents/support_agent.py:338-347`, `:356`, `:594-597` |
| B7 | "amazon fire tv stick" (a catalog product) gets the emergency reply and a **critical** safety ticket. | Main-app safety gate: keyword `"fire"` followed by a space matches. The word-boundary fix in `b258205` only excluded hyphenated "Fire-Boltt". | `app/main.py:30-72`, `:371-387` |
| B8 | Reply "ORD-2004" to "Which order is this about? … reply with the order number to open a support ticket" shows the **order status**; no ticket is opened. | `_is_bare_order_lookup` treats any short message without a complaint word as an order lookup and reroutes support to the order agent. `main.py` then runs a second graph invocation. | `app/agents/support_agent.py:243-251`, `:291-295`; `app/main.py:425-439` |
| B9 | Live eval `tc_008` asks `eval-test-user` about ORD-9901, which they don't own. | `seed.py` gives `eval-test-user` ORD-9901, but the README backup already has ORD-9901 owned by `test-user-99`; the seeder skips existing IDs. | `app/db/seed.py:153-160` |
| B10 | Live DeepEval silently stopped using the LLM judge. | The WIP inserted an early `return` of the rule-based metrics in `_make_metrics`, leaving the `gpt-4o-mini` GEval code unreachable. `answer_relevancy` is substring matching ("checks for expected phrases"). `tc_001` expects `⭐`, which the product reply has never printed. | `eval/run_deepeval.py:66-71`, `eval/config.yaml:6-9`, `eval/dataset.json` tc_001 |

Latent problems found while reading, not user-visible in the runs above:

- The LLM-callable `cancel_order` tool is still bound in `draft_resolution`. Its `user_id` argument is
  copied by the model from the prompt, so ownership depends on the model, and so does "has the user
  confirmed". The deterministic `/cancel-order` endpoint (UI button) already does the job safely.
  `app/agents/support_agent.py:391-405, 457`.
- Any number in a support message becomes an order ID (`"I paid 2000"` → `ORD-2000`): `support_agent.py:283-285`.
  The order agent's regex accepts only 4 digits: `order_agent.py:45`.
- `assess_severity` never returns `critical`, so the P0/P1 branches in the escalation subgraph are dead except
  for the main-app safety gate: `support_agent.py:350-373`, `support_agent_subgraph.py:44-51`.
- The `specs` table has 0 rows, so `fetch_specs` and `WEIGHT_SPEC_MATCH` do nothing: `product_agent_subgraph.py:53-77, 121-130`.
- `prompt_loader` does not cache failures: with LangSmith unreachable, every LLM call first retries the hub pull.
- Per-session preferences live in a process-global dict (`main.py:28`): lost on restart, not shared between workers.

## Guardrail inventory

"Exact" = protects security, money or user data and must stay deterministic. "Steer" = changes what the
model said or where a message goes, for one conversation that went wrong.

| # | Rule | Where | Added in → conversation it fixed | Kind |
|---|---|---|---|---|
| 1 | Sign-in required for order and support intents | `router.py:270-287` | initial; `5735d22` → anonymous support looped forever (orders belong to real users) | **Exact** |
| 2 | Order fetched only with `order_id AND user_id` | `order_tools.py:19` | initial | **Exact** |
| 3 | Cancel only if `processing` and owned by the user | `order_tools.py:68-72` | `362733d` → bot said "cancelled" without touching the DB | **Exact** |
| 4 | `/cancel-order` rejects anonymous users | `main.py:531-533` | `bc1ccff` | **Exact** |
| 5 | Cancel needs the UI "Yes" (status check + `action_required`) | `support_agent.py:561-583` | `bc1ccff` / `111c7f0` | **Exact** |
| 6 | Medium/critical issues → ticket for a human | `support_agent.py:606-608`, escalation subgraph | `7480087`, `575ec89` | **Exact** (escalation) |
| 7 | Safety keywords → critical ticket + fixed reply, before any LLM | `main.py:30-72, 371-387` | `df77937`, `bdc8310`, `b258205` → hazard reports | **Exact** intent, keyword detection misfires (B7) |
| 8 | Duplicate open ticket for the same order suppressed | `support_agent_subgraph.py:73-86` | `be61b3a` → second complaint made a second ticket | Exact-ish (protects the human queue) |
| 9 | Smartphone/laptop/tablet rows never returned | `product_tools.py:94-98` | `18f4155` → "redmi charger" showed phones | Exact (catalog scope) |
| 10 | LLM `cancel_order` tool with model-supplied `user_id` | `support_agent.py:391-405` | `362733d` | Risky duplicate of #3/#5 |
| 11 | `_GREETINGS` | `router.py:206-219` | `dcabe13` → "hi" mid-session got "I didn't quite understand" | Steer |
| 12 | `_NAVIGATION_PHRASES` + unclear→product override | `router.py:166-190` | `1abeddf` → "blanket"/"milk" after products classed unclear; `bc1ccff`/`fa02a59` → "resolve support issues" | Steer |
| 13 | Confidence < 0.7 → clarify | `router.py:261-267` | `96a68d9` (0.8 → 0.7) | Steer |
| 14 | `"null"` string → `None` | `product_agent.py:289` | `39755b5` | Steer (parsing) |
| 15 | Un-flag `unavailable_request` when brand + previous subcategory | `product_agent.py:300-307` | `1abeddf` → "what about Bajaj" after mixer grinder = "don't carry" | Steer |
| 16 | `_subcategory_in_message` un-flags `unavailable_request` | `product_agent.py:169-175, 312-317` | `5fbf09f` → "4K monitor", "usb hub with ethernet" = "don't carry" | Steer |
| 17 | Force previous subcategory when only the brand changed | `product_agent.py:330-339` | `a9c3683` → "Samsung" after TVs became earphones; `c7de56a` → but not for "bajaj smartwatches" | Steer |
| 18 | `vague_browse` wipes all filters | `product_agent.py:353-392` | `b258205`/`fb2dfd2` → extreme price filter bled into "show me something"; reverted by `130af1a`, restored by `b46591c` | Steer |
| 19 | `_price_down_words` → previous max × 0.7 | `product_agent.py:367-374` | `72aaf94` → eval tc_012 "show me something cheaper" | Steer |
| 20 | `new_specific_product` reset | `product_agent.py:378, 393-406` | `1abeddf` → "with calling feature" then "calculator" | Steer |
| 21 | Subcategory/category change resets filters | `product_agent.py:343-348, 393-406` | `a9c3683` → ₹2000 cap carried from headphones to monitors | Steer |
| 22 | Word-overlap test before inheriting subcategory | `product_agent.py:419-432` | `1abeddf` → headphones bled into "blanket" | Steer |
| 23 | Inherit keywords on pure price refinement | `product_agent.py:436-440` | `916d676` → "under 2000" after "smartwatch with calling" lost context | Steer |
| 24 | Type word copied into keywords | `product_agent.py:446-447` | `e7e95d7` → "gaming ones" with empty `type` column | Steer |
| 25 | Field-by-field `or previous` merge | `product_agent.py:448-458` | `a9c3683` → "above 4 rating" dropped brand | Steer |
| 26 | Phone/laptop/tablet keyword redirects | `product_agent.py:493-504` | `83a5e90` → unavailable reply dumped the whole catalog | Steer |
| 27 | `BLURB_EXCLUDED_SUBCATEGORIES` | `product_agent.py:30-42` | `83a5e90` → blurb advertised smartphones | Steer |
| 28 | `RELAXATION_ORDER` + price ×1.25 | `product_agent.py:181-186, 544-586` | `cfc57ec`, `b258205`, WIP removed `subcategory` | Steer |
| 29 | `has_specificity` stop | `product_agent.py:571-579` | `39755b5`; `ca2081f` → "something to make my chai" | Steer |
| 30 | Post-rank broaden (ranker rejects all → relax) | `product_agent.py:801-803` | `180e93e` → "4K monitor" said "don't carry 4K" | Steer |
| 31 | `keyword_recovery` cross-catalog search | `product_agent.py:806-832` | `0adef08` → "usb hub with ethernet" | Steer |
| 32 | Three-way brand no-results reply + context restore | `product_agent.py:589-645` | `2303234`, `649dfb8`, `c7de56a`, `5c72a38`, `130af1a` → Bose, Bajaj smartwatches, follow-up lost context | Steer (unreachable, B4) |
| 33 | `all_maybe` "related options" header | `product_agent.py:656-664` | `180e93e`, `0adef08` | Steer |
| 34 | 8 hand-tuned ranking weights + price bands | `product_agent_subgraph.py:11-18, 103-119` | initial, `f4621c7`, `87d0a3f` ("17/21 → 25/30 tests") | Steer |
| 35 | Fuzzy brand resolver (cutoff 80, exact first) | `product_tools.py:51-64` | `95987fb` → "Sonny"; `2303234` → Bose → StyleHouse | Steer |
| 36 | Brand: first word > 3 chars | `product_tools.py:123-125` | `95987fb` | Steer |
| 37 | Order-ID regex `ORD-?\d{4}` | `order_agent.py:43-53` | initial | Steer |
| 38 | "assistant asked for an ID" phrases + bare 4-digit number | `order_agent.py:77-100` | initial; `b340d7b` → "9905 status" | Steer |
| 39 | Auto-select a single order; product-name word match | `order_agent.py:112-124` | initial; `b340d7b` → "boAt Rockerz 450 status" | Steer |
| 40 | Delivered orders answered without the LLM | `order_agent.py:218-225` | `a73f6b5` → LLM said "check your account" | Steer (exact data) |
| 41 | Order ID only if typed in the current message | `support_agent.py:197-200` | `0b7d4f2` → history order ID bled into a new complaint | Steer |
| 42 | `_POLICY_QUESTION_PHRASES` → canned policy | `support_agent.py:99-125, 207-208` | `c8390c7` → "return policy" asked for an order | Steer |
| 43 | `_COMPLAINT_KEYWORDS` + bare-lookup reroute | `support_agent.py:218-251, 291-295` | `80b0397` | Steer (causes B8) |
| 44 | Product-name match beats order ID | `support_agent.py:268-276` | `111c7f0` → "cancel logitech m2" after ORD-4002 | Steer |
| 45 | Any number → `ORD-<n>` | `support_agent.py:280-285` | `bdc8310` | Steer |
| 46 | `_LEGAL_THREAT_KEYWORDS` → medium + skip order ask | `support_agent.py:338-347, 356, 594-597` | `c8390c7`, `a4b7972` → legal escalation test | Steer (causes B6) |
| 47 | Category → severity map | `support_agent.py:358-366` | `c8390c7` → refund made no ticket | Steer |
| 48 | Priority P0–P3 from history | `support_agent_subgraph.py:38-55` | `575ec89` | Steer (P0/P1 unreachable) |

Counted the same way for the before/after table: **38 steering rules** (rows 11–48) and **10 exact or
escalation rules** (rows 1–10). They include **12 keyword/phrase lists**: `_GREETINGS`,
`_NAVIGATION_PHRASES`, `_price_down_words`, the phone/laptop/tablet redirect lists (3),
`BLURB_EXCLUDED_SUBCATEGORIES`, the "assistant asked" phrases, `_POLICY_QUESTION_PHRASES`,
`_COMPLAINT_KEYWORDS`, `_LEGAL_THREAT_KEYWORDS`, `_SAFETY_KEYWORDS`. On top of those come the catalog-substring
matcher `_subcategory_in_message` and two order-ID regexes.

## Prompt inventory

| Prompt | Lives in | Runs from | Lines (code / hub) | Same? |
|---|---|---|---|---|
| Router classification | `router.py:26` + hub `router-classification-prompt` | **code** (hub bypassed in `bc1ccff`) | 70 / 106 | No: hub says "cancel → order", code says "cancel → support" |
| Clarify reply `_CLARIFY_SYSTEM` | `router.py:222` | code | 3 / – | – |
| Product extraction | `product_agent.py:189` + hub `product-extraction-prompt` | **hub**, code only if LangSmith fails | 46 (+ live catalog) / 44 (frozen catalog) | No: 68% similar, catalog differs, 4 rules missing in hub |
| Unavailable suggestion | `product_agent.py:476` | code | 12 / – | – |
| Ranking (inline) | `product_agent.py:720-735` | code | 15 / – | – |
| Order response | `order_agent.py:27` + hub `order-response-prompt` | **hub** | 11 / 17 | No: hub still has the pre-`bc1ccff` cancellation rules |
| Support classification | `support_agent.py:28` + hub `support-classification-prompt` | **code** | 37 / 36 | No (93% similar) |
| Support resolution | `support_agent.py:67` + hub `support-resolution-prompt` | **hub** in `draft_resolution`, **code** in `finalize_draft` | 30 / 27 | No: hub lacks the "cancel only after confirmation" rules while the `cancel_order` tool is bound |

Code copies total **224 lines** of system-prompt text across 8 prompts. Seven `push_*.py` scripts (957 lines)
hold further versions: `push_product_extraction_prompt.py` alone has 6 versions, 75 rule lines and 8 "NEVER"s.
`prompt_loader.py` pulls `latest` at startup and silently falls back to the code copy on any error, so
behaviour depends on the network and on whatever was pushed last.

## Cost per turn

LLM calls per user message, by path (from the code, confirmed by the call meter in `eval/run_baseline.py`):

| Path | Calls | Which |
|---|---|---|
| Safety gate | 0 | — |
| Sign-in required | 1 | router |
| Clarify (greeting, off-topic, low confidence) | 2 | router + clarify |
| Product, results | 3 (4–5 if the ranker rejects everything and relaxation reruns it) | router + extraction + ranking |
| Product, unavailable | 3 | router + extraction + suggestion (0 for phone/laptop/tablet) |
| Product, vague | 2 | router + extraction |
| Order: list / not found / delivered | 1 | router |
| Order: other status | 2–3 | router + response (+ tracking tool round-trip) |
| Support: policy / ask for order / cancel / ticket | 2 | router + classify |
| Support: low severity | 3–4 | router + classify + draft (+ policy tool round-trip) |

Tokens per call, from the app log during `run_20_tests.py`: router 1,461, extraction 1,665, ranking 523.
Unthrottled latency: 0.3–0.7 s per call (~1.5 s per product turn). Under the token limit: 10–14 s per call
(~30 s per product turn). The per-route averages over the whole baseline are in `SIMPLIFY_REPORT.md` and
`eval/baseline_runs/before_summary.json`.
