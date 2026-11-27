# 0021. A reply claims only what code did; the page draws from data; session ids answer to their owner
- **Status:** Accepted, implemented (Phase 6, PR A)
- **Date:** 2026-11-28
- **Extends:** [0020](0020-replies-claim-only-what-code-checked.md), which covered search results only.

## Context
- **An AI judge used only the live site** (2026-11-26, 33 messages) and scored it 6/10; honesty scored lowest (4/10). The sources, traced in the code:
  - "I'll contact the carrier right away… within the next 48 hours" came from `draft_resolution`, the only model-written support reply. Its prompt asked it to "say what we will do".
  - "You'll receive email updates at your registered address" and a response time were fixed text in every ticket reply.
  - "A human team member will follow up" was the fixed safety reply.
  - "I widened the price limit (+25%)" listed the search loop's steps, not how the shown products differed from the request.
- **The page dropped an order.** chat.html rebuilt order cards with a regex over the reply text. The regex didn't know "in transit", and a second regex deleted every order line, so My Orders showed 4 of 5.
- **Boundaries were open:**
  - the Discord alert carried the shopper's words without `allowed_mentions`, so "@everyone" would ping the channel;
  - `get_or_create_session` and `GET /messages/{id}` served any session to anyone with its id.
- **Measured before any fix** (gpt-oss-20b, replay, `multi_agent_baseline`), with the new checks below:
  - baseline 37/51 (48/51 under the old checks);
  - attack set 12/15;
  - Q&A 5/6;
  - the judge's session as an eval set 1/14 (recorded live on `dda22a6`, about 75K tokens).

## Decision
- **A reply states only facts read this turn and actions that succeeded this turn.**
  - The escalation subgraph records whether the alert went out (`ticket.alerted`). Ticket and safety replies say "alerted" only then, and otherwise say the ticket is in the queue.
  - Ticket replies name the ticket, its order and its kind. They give no response time, no refund and no email.
  - `draft_resolution` and `support_resolution.md` are removed. A request no code can carry out as asked is explained by a fixed reply (`explain`). A refund for an order that hasn't arrived says why, and how to ask for a ticket. A problem the policy covers opens a ticket at once; cancelling still asks first, because it can't be undone.
  - Search notes come from the shown products (`differences`): over budget, rated lower, features the search had to drop. The brand note is kept.
  - The router's model-written `reply` is ignored. Fixed replies answer a greeting or say what the assistant can't help with. The schema keeps the field, so the recorded router answers stay valid.
  - The safety reply starts with immediate steps (call 112, stop using it, unplug it, don't charge it).
- **Tickets keep the shopper's words apart:** a summary built by code, then the words quoted and cut to 300 characters.
- **The server sends listed orders as data** (`orders` in the chat response). The page draws cards from it, removes only the text lines naming those exact ids, and shows an unknown status as a plain badge.
- **Session ids answer to their owner.** A signed-in shopper's conversation, its history included, is refused to anyone else (403). A guest gets a new id on every request, so a guest's conversation answers to whoever holds its id. A guest who signs in takes the conversation with them.
- **Discord payloads set `allowed_mentions: {"parse": []}`.**
- **New checks on every turn of every set** (`eval/run_baseline.py`):
  - a promise nothing keeps (contacting the carrier, emails, follow-ups, response times, refund approvals), skipped when negated;
  - a ticket id that doesn't exist;
  - a cancel the database doesn't show;
  - the same product twice;
  - a product chip that matches no card;
  - orders the page would hide.
- **The judge's session is an eval set** (`eval/judge_conversations.json`, 14 conversations) that CI replays.
- **The CI gate** keeps its bars, adds `MIN_JUDGE = 10`, and gates on the promise checks at once. The two checks of what the screen shows are printed but don't gate until PR B fixes their cause (variant groups; chips that follow the cards). PR B removes `SCREEN_ONLY`.

## Consequences
- **Measured after PR A** (gpt-oss-20b, replay, `multi_agent_baseline`, about 13K tokens to record the 11 changed router calls):
  - baseline **45/51**: p03, p10 and s16 as before, plus p13, p21 and p22, which show duplicate cards;
  - attack set **13/15**: a12 routing as before; a13 shows smartwatches under a "tv accessory" chip (screen only);
  - Q&A **5/6**: q05 shows a duplicate (screen only);
  - judge set **8/14**; the rest is PR B's: "Noise" read as a brand, "yes" to an offer, a typed answer during Yes/No, dates, duplicates.
- **Fewer model calls:** a support request no longer calls the model.
- **Old 48/51 runs aren't comparable** with these checks; the release numbers come from new live runs.

## Alternatives considered
- **A prompt rule against promises:** ADR 0010. It asks for honesty but can't enforce it; removing the model-written text does.
- **Fixing the page's regex:** the next new status would break it again.
- **Lowering the gate's bars:** the failures are real and scheduled, so they're reported instead, and only until PR B.
