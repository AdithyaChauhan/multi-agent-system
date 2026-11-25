# 0017. Free-tier capacity: fail fast, and report the share of real answers
- **Status:** Accepted (the user's choice, 2026-11-24)
- **Date:** 2026-11-24

## Context
- **The first 20-user load test** (3 minutes, local Docker, gpt-oss-20b first, fallback chain and cache on):
  - 0 HTTP errors in 216 requests;
  - p95 22 s;
  - 51 of 175 chat replies were real answers; the other 124 were the "busy" reply.
- **The latency came from the Groq SDK.** It retried each 429 after sleeping for `retry-after` (9 s in a traced turn) before our fallback chain could try the next model.
- **The busy replies came from the free tier's ceiling.** Every rate limit was per minute: about 7K tokens a minute for each of gpt-oss-20b and -120b, plus qwen's input-token limit. That's about 22K tokens a minute for the whole chain, roughly 5 product turns. 20 users asking every 5–15 s want about ten times that.
- **The release check also found a rejected key** (revoked or mistyped) returning HTTP 500 on every turn, because the chain re-raised it.

## Decision
- **Stay on Groq's free tier** (the user's choice). A few judges at a time get full answers. Beyond that, the site answers fast with the busy reply instead of making people wait or showing errors.
- **Fail fast:**
  - `ChatGroq(max_retries=0)`: the chain's cooldowns handle 429s, so a rate-limited model is skipped at once;
  - a rejected key (`AuthenticationError`) ends the turn with the busy reply right away, because every model shares the key, and logs `LLM_KEY_REJECTED`.
- **Report honestly.** The load test reports the share of real answers next to p95 and the error rate (`eval/loadtest/summarize.py`). The README and the case study state the ceiling plainly.

## Consequences
- A p95 measured over all replies includes fast busy replies, so it must never be quoted without the answered share.
- More capacity is a configuration change, not a code change: a paid Groq key, or more models in `GROQ_FALLBACK_MODELS`.
- Without SDK retries, a single transient 5xx also moves down the chain instead of retrying the same model. That's acceptable: the next model answers.

## Alternatives considered
- **A paid Groq tier:** real answers for 20 users, but it costs money and needs billing. Not chosen.
- **Trimming tokens per turn first:** about a third more capacity for about a day of work; still mostly busy replies at 20 users.
- **Queueing requests until quota frees up:** people would wait tens of seconds for an answer; a quick busy reply is a better experience.
