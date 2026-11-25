# 0020. A reply claims only what code checked, and the evals check the claims
- **Status:** Accepted, implemented (Phase 5, PR #6)
- **Date:** 2026-11-25

## Context
- **The user found it on the live site.** "hdmi cables" showed three HDMI cables under "These don't match everything you asked for, but they're the closest options we have".
- **Where the header came from.** The ranker answers `same_kind` and `exact`. The header appeared whenever no shown product was in `exact`. gpt-oss-20b leaves `exact` empty in 65% of its recorded answers, matching results included:
  - 60 of 92 in the conversation cassette;
  - 119 of 185 in retrieval;
  - gpt-oss-120b: 26%.
- **The evals never read that sentence.** They scored routes, filters, the products shown and database effects. In final run 2, 25 of 43 product replies carried the header, 13 of them certainly false. Runs 1 and 2 scored 48/51 each; with the sentence checked, they score 38/51.
- **A second model flag was flaky in the same way.** The router's `about_shown` missed "does the first one come with a warranty?" in 1 of 5 calls, and that turn searched again.

## Decision
- **The default header claims nothing:** "Here's what I found:" (the user's wording).
- **Only notes that code computed say something is missing:**
  - the brand note (the asked brand isn't among the results);
  - "I widened …" (the search loop relaxed a filter).
- **The ranker's `exact` list only orders results.** It never reaches the shopper's text.
- **The evals check claims in the text.** `false_mismatch_claim` in `eval/run_baseline.py` fails a product reply whose first line claims a mismatch while every shown product meets the kind, brand, price and rating asked for. Requests with features are skipped, because the harness can't check them.
- **A model flag that decides a route gets a code backstop.** `asks_about_shown` takes the router's `about_shown` or a message that points at the list ("the first one", "which of these"). Either way, a brand, budget or product word means a search (`names_a_search`).
- **Runs of code that changed don't count toward the release criterion** (the user's choice, 2026-11-25). Runs 1 and 2 stay in the plan with both scores. The 3-run average uses three live runs of the fixed code.

## Consequences
- A shopper never reads a doubt the code can't back. When the results really are near misses and the filters weren't widened, the reply doesn't say so.
- Attribute and feature mismatches ("with ANC") are still unchecked by the harness.
- A wording change in a reply changes the next turn's router input (the last 4 messages), so it re-records router calls: 27 here, 36.5K tokens.
- Three new live runs cost about 590K tokens over two days.

## Alternatives considered
- **A prompt rule such as "HDMI cables exist, don't say there's no match":** a one-off rule (0010), and it fixes one product, not the cause.
- **Prompt the ranker to fill `exact` better:** it still depends on the model, and every ranker call would need re-recording.
- **Decide `exact` in code from the typed catalog** (0005): possible later; it would let a header say "close but not exact" truthfully. Not needed for the release.
- **Re-record q04 until it passed:** hides a 1-in-5 failure instead of fixing it.
- **Count runs 1 and 2 as scored at the time:** they measured a reply the shopper shouldn't see.
