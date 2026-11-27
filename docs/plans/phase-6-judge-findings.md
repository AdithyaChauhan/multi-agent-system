# Phase 6: What the judge found

- **Status:** In progress. PR A's code is done (2026-11-28; see Results); PR B not started.
- **Reviews (2026-11-26), folded in below:**
  - the Phase 5 session reviewed it against the code;
  - the judge reviewed it from the shopper's side. It expects the score to move from 6 to about 7.5 if causes 1, 2 and 4 hold in its retest.
- **Source:** an AI judge used only the live site on 2026-11-26: 33 messages, as a demo shopper and as a guest, no source code. Score **6/10**. No crashes, no data leaks, no busy replies.
- **Approach:** the judge listed 14 problems. Traced to the code, they come from six causes. This plan fixes the causes, so the same kind of bug is fixed where the judge didn't look too. The evals test the causes, not the 33 turns.
- **Two PRs with green CI** (ADR 0019), each squashed to one commit. `main` is live, and smaller PRs keep CI readable.
  - **PR A** (`phase-6a-honest-replies`): causes 6, 1 and 3, plus the smaller fixes. Most of what a judge sees.
  - **PR B** (`phase-6b-state-and-data`): causes 2, 4 and 5.

## The judge's findings, by cause
| Finding | Judge's severity | Cause |
|---|---|---|
| The old product filter leaks into later turns | High | 2 |
| False promises: carrier, email updates, human follow-up | High | 1 |
| "My Orders" leaves out an order | Medium | 3 |
| Ignores "yes" to its own offer | Medium | 2 |
| Direct questions get a template | Medium | 4 |
| Stale demo dates go unnoticed | Low | 5 |
| Text typed during a Yes/No question is lost | Low | 2 |
| A returning session opens a blank chat | Low | 2 (reproduce first) |
| Duplicate products in results | Low | 5 |
| Tickets store the raw message, link no order, and don't ask first | Low | 6 and 4 |
| Off-topic gets a greeting; a swelling battery gets no advice | in the scores | 4 |
| A "widened the price" note that changed nothing | in the scores | 1 |
| "Good news! … delivered" right after the shopper reported that item damaged | judge's review | 4 |
| A typed message during a Yes/No question that isn't yes or no ("which mouse?") must be answered | judge's review | 2 |
| A ticket or cancel that fails in the background must say so | judge's review | 1 |
| "Multi-Agent System" on the login page; a tip that outlives its action; cards below the fold; the Amazon link; the guest message names only Google sign-in | in the scores | smaller fixes |

## The six causes

### 1. Replies say more than the code knows or did
**Evidence:**
- "I'll contact the carrier right away… within the next 48 hours": `draft_resolution`, the only model-written support reply. Its prompt asks it to "say what we will do" ([support_resolution.md](../../app/prompts/support_resolution.md)). No code contacts a carrier.
- "You'll receive email updates at your registered address": fixed text in `ticket_reply`. No email is ever sent.
- "A human team member will follow up": the fixed `SAFETY_RESPONSE`. A ticket and a Discord alert exist; a follow-up doesn't.
- "I widened the price limit (+25%)" under kettles: the note lists every step the search loop took, not how the shown products differ from the request.
- ADR 0020 made product headers honest, but only for search results. Actions, dates and support replies were never covered.

**Fix** (extends ADR 0020 to every reply):
- A reply states only facts read this turn and actions code completed this turn. Each turn records its actions (`ticket_opened`, `alert_sent`, `order_cancelled`), and every sentence about an action is rendered from that record.
- **A ticket reply says only what happened:** "Ticket TKT-… opened for ORD-70408 (damaged delivery). Our support team has been alerted." It promises no refund and no response time, because nothing in the code backs either. This was the judge's condition for opening tickets at once; it will test it in the retest. Today's `ticket_reply` prints a response time, and that line goes.
- **An action is recorded only when it succeeded:** the ticket row committed, the webhook answered 2xx, the cancel updated one row. When one fails, the reply says what didn't happen ("I saved ticket TKT-… but couldn't alert the team; they'll see it in the queue"). Unit tests force each failure.
- `draft_resolution` becomes a fixed reply that applies the policy to the order (cause 4). One prompt and one model call fewer.
- Search notes come from comparing the shown products with the shopper's filters: "these are over your ₹2,000 budget", "none of these is Sony", "the details don't confirm noise cancelling". They are true by construction, and they replace `_brand_note` and `RELAXED_WORDS`.
- **A new eval check** fails a claim of an action ("I'll contact…", "you'll receive an email", "refund approved", "I've cancelled", "ticket") unless that turn's action record has it.
  - It runs on every set, the Q&A set included, because Q&A replies are model-written.
  - The Q&A prompt changes only if the check finds a promise there.

### 2. The saved conversation drifts from what's on screen
**Evidence:**
- Only `preferences` carries between turns ([router.py `new_turn`](../../app/agents/router.py)), through any number of order and support turns. "Do you sell kettles", 14 turns after a laptop request, showed "laptop, under ₹60,000" chips.
- A refused search is saved anyway: "we don't carry laptop" hides the chips but stores `laptop` as the product ([product_agent.py `extract_preferences`](../../app/agents/product_agent.py)). "Show me something cheap" then answered "we don't carry laptop".
- Offers aren't remembered: "Would you like to see our laptop bag range instead?" is plain text, so "yes" was read as a new search.
- The Yes/No step disables the text box, so a typed "no, keep it" can't be sent.
- Reopening a chat restores only the reply text: cards, chips and a waiting Yes/No question are lost.

**Fix:** the saved state is what the shopper can see.
- **Filters stay until the shopper asks for a different kind of product,** and every product reply shows them as chips. A shopper comparing watches can ask "is my TV late?" and then "show cheaper ones" and still get watches (the judge's rule, which replaces "another topic ends the search").
- **Code decides that the product changed,** from the catalog words in the message. Today that depends on what the model returns.
- **A filter copied from the old search is dropped** when the product changes, unless the message states it again. This is the likely cause of the kettle case: "laptop" and "under ₹60,000" appeared under kettles. Step 1 replays that turn, and the logged `EXTRACTED` and `MERGED` filters confirm or refute it before anything is changed.
- **A refused search saves nothing.** Its offer becomes a waiting question.
- **One waiting question at a time.** Every question the assistant asks (cancel this order? laptop bags instead? which order?) is saved with its answers, and asking a new one drops the old.
  - The cancel pause (`interrupt()`) is one kind of waiting question.
  - Buttons answer it, and so does a typed yes or no (also "haan", "nahi"), matched in code from a short closed list.
  - For the cancel, a typed answer becomes the same resume as the button, through the same owner check (`check_resume`).
  - Anything else is answered as a new message ("which mouse?" gets the mouse order), and the reply says the question was dropped ("I haven't cancelled ORD-…").
- **Every stored reply keeps its structured parts** (cards, chips, order list, waiting question). Reopening a chat redraws from them.

### 3. Text is the interface between the server and the page
**Evidence:**
- "My Orders" showed 4 of 5 orders. The page rebuilds order cards with a regex over the reply text ([chat.html `parseOrderList`](../../app/static/chat.html)) that knows five statuses but not "in transit". A second regex strips every order line, so that order vanished.
- Status words differ by source: "in transit" (orders table), "In Transit" (carrier), `in_transit` (code).

**Fix:**
- The server sends orders as data, the way it already sends products. The page draws cards from the data and shows an unknown status as a plain badge, never drops it.
- One list of statuses, normalised where orders are read.

### 4. One fixed reply per route, whatever was asked
**Evidence:**
- "Does that one actually have active noise cancellation?" searched again. "Noise" is a brand in the catalog (so is "Boult"), and `names_a_search` lets a brand word outrank "that one".
- "Can I still return my steam iron?" got the generic policy text. "When was it delivered, am I inside the 30 days?" got "Good news! … has been delivered" with no date. Orders store no delivery date, and the policy is never applied to an order.
- Off-topic and injection messages got a model-written greeting, although the router prompt asks it to say what the assistant helps with.
- A swelling phone battery got the same fixed safety text as a fire: no "stop charging it".

**Fix:** complete answers from data, decided in code.
- **An order reply always carries what matters for that order**, computed in code:
  - its status and key date, and whether it's late;
  - what can be done now and until when ("returns open until 12 Dec, 16 days left", "can still be cancelled").
- **A policy question about an order applies the policy to that order.** The order can be named by its product ("my steam iron"). The router already matches products to the shopper's own orders.
- **Order replies are neutral.** They state facts without "Good news!", because code doesn't know how the shopper feels; the judge got "Good news! … delivered" right after reporting that item damaged.
- **When to act and when to ask:**
  - an action that can't be undone (cancelling) always asks first;
  - a problem the policy covers (damaged, wrong item, defective) opens a ticket at once, because that is what the report asks for, and the reply says exactly what was done;
  - a request the store can't meet as asked (a refund for an order still on its way) is explained, and a ticket is offered as a waiting question. This is the judge's "refund the TV" case.

  The judge suggested asking before every ticket. That would change 12 of the 51 baseline conversations and 2 attack conversations, which expect a ticket in the same turn, for no gain on reports the shopper made on purpose.
- **Tickets link the order the conversation is about.** Without one, the assistant first asks which order (a waiting question with the orders as buttons). Legal and account-data reports still open a ticket at once.
- **Brand names that are ordinary words are flagged in the catalog** (ADR 0005).
  - A script marks a brand whose name appears as an ordinary word in other brands' product titles ("noise" in "noise cancelling").
  - Such a word counts as a brand only when it isn't part of one of those phrases in the message.
  - "Does that one have active noise cancellation?" then reaches the Q&A loop, which answers yes or no from the product's facts. "What about Sony" still searches; its test in `tests/test_product_qa.py` stays.
  - A search for a feature the results don't confirm says so ("the details don't confirm noise cancelling", cause 1), instead of showing passive-isolation headphones as a match.
- **Fixed replies replace the router's free-text reply:** one for greetings, and one for everything outside the assistant's job ("I can only help with this store's products, your orders and support"). The schema keeps its unused `reply` field until the next router re-record.
- **The safety reply opens with immediate steps** for electrical hazards: stop using and charging it, unplug it, keep it away from anything flammable, call 112 if there's fire or injury. Then it names the ticket the code opened.

### 5. Demo data is frozen in time and duplicated
**Evidence:**
- Orders have no dates of their own. Tracking comes from the mock carrier's fixed May 2026 dates, shared by every demo shopper ([carrier_api.py](../../mock_services/carrier_api.py)).
- The catalog has 1,350 products but 1,309 distinct titles: 41 exact duplicates. Colour variants are separate products too (Fire-Boltt Ninja 3 in black, green and silver). The top 3 showed both kinds of duplicate.

**Fix, dates:**
- Orders get `ordered_at`, `delivered_at` and `expected_at` (Alembic migration).
  - The migration fills them for existing orders too: the `multi_agent_baseline` database, the CI fixture and Neon.
  - Demo shoppers get dates relative to when they were created, and the carrier mock reads them.
- **One clock** (`today()`), set by an environment variable in every eval mode (record, replay, fill, live) and in tests. Dates appear in reply text, and the router reads the last four messages, so without a fixed clock the recordings would stop matching the next day (ADR 0018).

**Fix, duplicates:**
- A variant group per product, computed by a script and stored in the database (ADR 0005).
- Results show one card per group ("also in green and silver").
- When no brand was asked for, the top 3 prefer different brands.
- **Metrics first:** before collapsing, the 100 search labels are scored by variant group (a hit on any colour counts) on the current code. So the metric change shown is the grouping's, not the label change's. Brand variety is tuned on the dev half only.

### 6. Shopper text and session ids cross boundaries unchecked
**Evidence:**
- A ticket's description is the shopper's raw message. The judge's whole manipulation attempt went into a ticket.
- The Discord alert posts that text without `allowed_mentions`, so "@everyone" in a message would ping the whole support channel.
- `GET /messages/{session_id}` returns a conversation to anyone who has its id.
- `get_or_create_session` resumes any existing session by id without checking its owner, so `/chat` would accept another user's session id.

**Fix:**
- Tickets hold structured fields (category, order, a summary built by code), with the shopper's words quoted and cut to length.
- The Discord payload sets `allowed_mentions: {"parse": []}`. It's tested in a unit test of the payload, never on the live channel.
- **Every endpoint that takes a session id checks its owner:** `/chat`, `/chat/stream` (the cancel resume included) and `GET /messages/{id}`. A signed-in user may take over an anonymous session, so the guest → sign-in flow keeps the chat. Never another user's.

### Smaller fixes (PR A)
- Scroll to the start of a new reply, so its cards don't land below the fold.
- Build the "things to try" tips from the shopper's own orders: no "cancel my mouse order" once it's cancelled.
- The blank chat on a returning session: reproduce it first. Redrawing from stored parts (cause 2) probably covers it.
- The sign-in message also names the demo shopper button, not only Google.
- **The store is called Wattnest** (the judge's pick).
  - A web search on 2026-11-26 found no shop, brand or product by that name. Of the alternatives, Ampora is an e-commerce platform's name and Socketly a software library's.
  - The name appears on the login page and in the header, which say "Multi-Agent System" today.
  - It also appears in the greeting ("Hi! I'm the Wattnest assistant…") and in the out-of-scope reply.
  - The router prompt doesn't change, so its recordings stay valid.
- **"View product":**
  - PR A labels the link "View on Amazon (opens new site)". Amazon's price may differ from the store's, and without the label that looks like the store got its price wrong.
  - PR B adds a "Details" view on each card, built from the same facts the Q&A tools read, with no model call. The shopper stays in the store (the judge's recommendation).
- Check the phone-width layout at 400 px.

## How it's measured (ADR 0004, 0010)
1. **Before any fix:** the judge's session as an eval set, `eval/judge_conversations.json`.
   - About 12 conversations covering the 33 turns. The checks test behaviour, not wording.
   - Recorded on `main` as it is now (`dda22a6`), from a worktree if fixes have started, to show the failures. About 80K tokens, one key.
2. **New checks on every set:**
   - action claims without a matching action;
   - chips that don't match the cards;
   - duplicate cards;
   - an order list that is missing an order.

   No prompt rule is added for any single turn.
3. **Re-recording is batched.** Reply text feeds the router: it reads the last four messages, 400 characters each. So every changed reply makes the next turn's router call miss. On 2026-11-25 the header change alone made 27 router calls miss (36.5K tokens to fill). Each PR changes its reply text in one batch and fills once: about 100–150K tokens per PR.
4. **The release numbers describe the live code:** three new live runs of the 51 conversations, about 200K tokens each, one per key per day (the ADR 0020 rule).
5. **Quota plan:** about 4–5 days of free quota on two keys. Each key's daily quota resets at about 05:30 IST.

## Retest probes
These are written now, before the fixes, so the fixes aren't taught to the test.
- **Who and when:** a fresh demo shopper on the live site after PR B is deployed, on a different day from the fixes.
- **One probe per cause:**
  1. Ask for a product, spend 10 or more turns on orders and support, then send a vague product request. No old chips.
  2. Answer "yes" to an offer the assistant makes.
  3. Type an answer while a Yes/No question waits.
  4. Refresh, then reopen the chat. Cards, chips and a waiting question come back.
  5. My Orders shows as many orders as the account has.
  6. A second account requests `/messages/{id}` for the first account's chat and posts to its session. Both are refused.
  7. Ask a return question about the delivered order. The reply gives the delivery date and the days left.
  8. Smartwatch top 3: no duplicates.
  9. The page at 400 px wide.
- **Categories the judge didn't touch:**
  1. Cancel an order that has already shipped.
  2. Report damage without naming an order.
  3. Sign in as a guest partway through a chat.
  4. A Hinglish refinement ("isse sasta dikhao", "show me cheaper than this").
- **The judge's own retest** (it agreed: same rules, website only, about 40 messages, the same log format):
  - its 33 original tests, repeated, so before and after compare fairly;
  - about 7 new tests:
    - an order question in the middle of a product search, then back to the search;
    - typing something other than yes or no during a Yes/No step;
    - an overdue order;
    - a duplicate product;
    - a product yes/no question;
    - an out-of-scope request;
    - what a ticket contains.
  - It repeats the earlier misuse tests instead of being told about the security holes.
  - **Before the retest:** reconnect the Chrome extension the judge runs in, and message it once the fixes are live.

## Order of work
**PR A**
1. [x] The judge set, the new checks and the probes; record the set on `dda22a6`.
2. [x] Cause 6 (boundaries and owner checks).
3. [x] Cause 1 (honesty): the action record, fixed support replies, notes from differences. The safety, out-of-scope, greeting and sign-in replies moved here from cause 4: they are reply text, and batching reply text means one re-record.
4. [x] Cause 3 (orders as data). The page normalises any status and never drops an order; a single status list in the database is PR B's (with the date migration).
5. [x] The smaller fixes: the store name, scroll to a reply's start, tips that can't go stale, the sign-in message naming the demo, "View on Amazon (opens new site)". Still open: the blank returning chat (not reproduced) and the 400 px check, both with PR B's stored structured parts.
6. [ ] Replay every set, fill once, the CI simulation from `git archive HEAD`, PR A.

**PR B**

7. [ ] Cause 5, dates: migration and backfill, one clock, demo shopper dates, the carrier mock.
8. [ ] Cause 4 (complete answers): order facts, policy applied, linked tickets, flagged brand words, fixed out-of-scope and safety replies.
9. [ ] Cause 2 (state = screen): the product thread, refused searches, waiting questions, typed answers, stored structured parts.
10. [ ] Cause 5, variants: labels by group first, then the grouping script, one card per group, brand variety.
11. [ ] Replay every set, fill once, the CI simulation, PR B.

**Release**

12. [ ] The retest probes and the judge prompt on the live site.
13. [ ] Three live runs; case study, README and explainer; the scorecard.
14. [ ] ADRs:
    - 0021: replies claim only what code checked or did (extends 0020);
    - 0022: state mirrors the screen, with one waiting question;
    - 0023: structured payloads between the server and the page, with owner checks on every session id.

## Results
### 2026-11-28: PR A's code
- **Before any fix** (gpt-oss-20b, replay, `multi_agent_baseline`, with the new checks):
  - baseline 37/51 (48/51 under the old checks);
  - attack set 12/15;
  - Q&A 5/6;
  - the judge set, recorded live on `dda22a6`: **1/14**, 23/38 turns (about 75K tokens, 0 rate limits).
- **Every new failure was real.**
  - 30 promises in ticket and safety replies.
  - Three replies with the same watch twice; in p21 all three cards were the same Fire-Boltt Phoenix.
  - a13 showed smartwatches under a "tv accessory" chip.
- **The kettle leak (j08) didn't reproduce**, so "the model copies the old filters" is unconfirmed. The laptop search survives through "yes" to the offer instead (j02): laptop chargers under a "laptop" chip.
- **After PR A** (replay; 11 router calls re-recorded, about 13K tokens, far fewer than the 100–150K feared):
  - baseline **45/51** (p03, p10, s16 as before; p13, p21, p22 duplicates);
  - attack set **13/15** (a12 routing; a13 screen only);
  - Q&A **5/6** (q05 duplicate);
  - judge set **8/14**. Left for PR B: "Noise" as a brand (j01), "yes" to an offer (j02), a typed answer during Yes/No (j04), dates (j11), duplicates (j12, j14).
- **Checks:**
  - one false positive found in my own check: "I can't contact the carrier" matched; negated phrases are skipped now, with a test;
  - 390 unit tests;
  - the CI gate passes locally on these results.
- **The gate:** the screen checks (duplicates, chip versus cards) are reported until PR B ([ADR 0021](../decisions/0021-replies-claim-only-what-code-did.md)); the promise checks gate now; `MIN_JUDGE = 10`.

## Acceptance criteria
- Judge set: every check passes. Retest probes: all pass.
- Across all sets:
  - 0 action claims without the action;
  - 0 duplicate cards;
  - order lists complete.
- Every endpoint that takes a session id refuses another user's session.
- No regressions:
  - 51 conversations ≥ 48/51;
  - adversarial safety cases all pass;
  - Q&A 6/6;
  - recall@5 and precision@3 unchanged, scored by variant group.
- One prompt fewer (`support_resolution.md` removed); every prompt under 40 lines.

## Questions for the user
None open.
- **The store's name:** Wattnest. The user forwarded the judge's pick, and the web check found it free. It's a quick search, not a trademark search.
- **"View product":** details inside the chat, plus the labelled Amazon link.

## Considered and not chosen
- **Filters that end when the topic changes** (this plan's first version): the judge showed it would break a shopper who checks an order in the middle of comparing products.
- **Asking before every ticket:** see cause 4. Only actions that can't be undone, and requests the store can't meet as asked, ask first.
- **Order tools for the Q&A loop:** complete order replies answer the judge's questions with no new model calls, and ADR 0016 keeps tools away from orders.
- **A list reference that outranks brand words:** it would send "is there a Sony one like these?" to Q&A and undo the 2026-11-25 fix. The ambiguity is in the data, so it's fixed there.
- **A prompt rule per failing turn:** ruled out by ADR 0010, and it fixes one sentence, not the cause.
- **A model that writes every reply:** honesty could then only be asked for, never enforced.
- **Patching each regex:** the `in transit` regex would be fixed, and the next new status would break it again.
- **One PR for everything:** too much to review on a live `main`.
