# 0015. The demo never breaks: model fallback, answer cache, limits, identity, CI eval gate
- **Status:** Accepted, implemented (Phase 4)
- **Date:** 2026-11-23

## Context
A judge tries the live demo once (0013). On 2026-11-23:
- **Every Groq failure became an HTTP 500,** "Something went wrong". The Phase 3 baseline hit a burst of these: 14 conversations in a row. A retired `GROQ_MODEL` would break every reply.
- **Nothing protected the shared free tier** (200K tokens a day per model) from one busy visitor.
- **The real app accepted `X-User-ID`, so anyone could act as any user.** The header was meant for tests. `/auth/demo-login` gave a token for any user id, including real Google accounts, and created new ones.
- **The escalate-only safety pattern of 0008 was never built.**
- **CI's eval job targeted a self-hosted runner that no longer exists,** so CI never measured anything and the image build waited on it forever.

## Decision
- **Fallback chain** (`app/core/llm.py`):
  - `GROQ_MODEL`, then `GROQ_FALLBACK_MODELS` (the other two of gpt-oss-20b, gpt-oss-120b and qwen3.8-27b). Same account only.
  - A 429, timeout, connection error, 5xx or retired model (404) moves to the next model. Any other error is raised as before.
  - A 429 cools that model down for its `retry-after` (10 minutes for a daily cap); a retired model is skipped for an hour.
  - When every model fails, `ModelsUnavailable` becomes a normal reply: "I'm getting a lot of questions right now… try again in a minute." Never a 500.
  - Evals pin one model (any cassette mode, or `LLM_FALLBACK=off`, which the harnesses set).
- **Answer cache:** identical calls (same model, messages and schema, temperature 0) within 30 minutes reuse the answer, in an in-process LRU of 512 entries. The key is the whole prompt, so it can't serve one user's order details to another.
- **Limits** (`app/core/limits.py`): 20 turns a minute and 150 a day per signed-in user, or per IP when anonymous, answered with a friendly message. These are turn counts rather than the planned token budget: turns can be checked before any model call and don't depend on threading the session into the model wrapper.
- **Identity:**
  - `X-User-ID` is honoured only with `ALLOW_X_USER_ID=true`, which only tests and eval harnesses set.
  - `/auth/demo-login` accepts only existing `demo-user-N` accounts.
- **Safety floor (0008):** `router.SAFETY_PATTERN` ("caught fire", "electric shock", "sparks coming", "exploded", "melted", "injured"…) can only raise `risk` to safety.
- **The catalog has a say on vague messages:** when the router says "unclear", or the extraction finds nothing, but a product scores ≥ 0.75 by meaning, the message is searched ("remove fuzz balls from my sweaters" finds lint removers).
- **After widening:** if the loop had to loosen the filters and the ranker rejects everything, products of the requested type are shown. The reply already says what was widened.
- **PII:** emails and Indian mobile numbers are masked in every app log line (`RedactingFilter`) and in LangSmith traces (an anonymizer on the shared client).
- **CI eval gate:** the `replay-evals` job runs on GitHub-hosted runners:
  - Postgres comes from `pgvector/pgvector:0.8.0-pg15`, restored from `eval/fixtures/ci_baseline.dump` (668 KB, built by `scripts/make_ci_fixture.py`: users scrubbed to `<id>@example.com`, chats, tickets and reviews emptied, embeddings recomputed in CI);
  - it replays the 100 product queries (ranker off), the 51 conversations and the 15 adversarial conversations at 0 tokens;
  - `eval/ci_gate.py` fails the build below the measured bars or on any cassette miss;
  - the image build now depends on it.

## Consequences
- **A retired model name** (live check, 2026-11-23): every call fell through to gpt-oss-20b and the shopper got a normal answer with product cards.
- **20 identical messages** in a minute: 20 replies (19 from the cache), then the friendly limit message.
- **The adversarial set passes 15/15:** injection, cross-user orders, an admin claim, someone else pressing Yes, a SQL-looking id, a prompt leak, and a safety report wrapped in "don't escalate".
- **The 51-conversation baseline is 48/51** (gpt-oss-20b; p19 fixed).
- **The CI job was simulated in a clean `python:3.12-slim` container:** the same numbers as on Windows (recall@5 0.979, precision@3 0.933) and 0 cassette misses, so the replay holds across machines. It also showed `alembic` was missing from `requirements.txt`.
- **Limits and the cache live in one process's memory.** Several instances would each allow the full amount (Phase 5 runs one instance).
- **The gate's bars are today's numbers,** so any drop fails CI. Raising them needs a measurement; lowering them needs an ADR.

## Alternatives considered
- **A second Groq account as a fallback:** that's quota evasion across organisations (0013). Rejected.
- **A token budget per session:** the token count is only known inside the model wrapper, which runs in worker threads during streaming. Turn limits give the same protection more simply.
- **Recording query embeddings for CI:** not needed. Recomputed vectors gave identical results on Linux.
- **Refusing unknown product words with low similarity (p03 "table"):** "pointing device" (a renamed type) scores lower than "table", so it would break the renamed-catalog robustness. p03 stays a known failure.
