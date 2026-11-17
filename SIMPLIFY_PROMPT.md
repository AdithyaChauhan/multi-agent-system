# Prompt: find out why the Multi-Agent chatbot is broken, then simplify it

You are working unattended in `C:\Users\Chauhan\OneDrive\Desktop\All-projects\multi-agent-system-ci-fix-cicd`. This is Adithya's multi-agent e-commerce chatbot: FastAPI with LangGraph; a router plus product, order and support agents; Groq through `langchain-groq`; PostgreSQL; prompts in LangSmith; DeepEval in CI; Helm. It is not live and is "being repaired".

Adithya thinks it is over-engineered: too many guardrails and too many hand-written system prompts. Your job has two parts:
1. Find out what actually breaks it.
2. Make it simpler without making it worse, and prove that with before/after measurements.

Work in this order and finish each phase before starting the next.

## Ground rules

- **Never** print, log, copy or commit secrets. That covers `.env`, `helm/templates/secret.yaml` and any API key. Read keys only through the environment.
- Do not push, deploy (`render.yaml`, Helm) or touch LangSmith hub prompts remotely. Everything stays local.
- Do not modify `dump.sql`, `backups/` or `ecommerce.db`.
- The working tree has uncommitted changes in about 17 files. Before changing anything:
  1. Run `git checkout -b simplify-agents`.
  2. Commit the existing changes as `wip: snapshot before simplification`. Check `git status` first so `.env` is not staged; it is gitignored, so confirm that.
     - `helm/templates/secret.yaml` and `helm/values.yaml` are among the modified files. Check whether their changes contain real key values rather than template references or placeholders, without echoing the values.
     - If they contain real values, leave those two files out of the commit and say so in the report.
  3. Commit after each phase from then on.
- Use the repo's `venv/` if it works; otherwise create a new venv under `%TEMP%`. OneDrive syncs this folder, so don't create large files in it.
- If a step needs something you don't have, record it in the report and continue with the rest. For example, an OpenAI key for the `gpt-4o-mini` judge in `eval/config.yaml`.

## What a first look already found (verify each one; don't assume)

1. **Patch on patch.** The last ~15 commits are almost all one-off fixes: "brand subcategory guard", "restore context after respond_no_results", "keyword recovery fallback", "three-way brand no-results response", and so on. Each fix targets one conversation and adds a rule that overrides the model.
   - `extract_preferences` in `app/agents/product_agent.py` is about 235 lines, with 17 if/elif branches that rewrite the model's output after the fact. Examples: un-flagging `unavailable_request`, forcing the previous subcategory back, and merging preferences across turns.
2. **Prompts live in two places.** Hard-coded prompts sit in the agent files (`ROUTER_SYSTEM_PROMPT`, `CLASSIFICATION_SYSTEM_PROMPT`, `RESOLUTION_SYSTEM_PROMPT`, `RESPONSE_SYSTEM_PROMPT`, `_CLARIFY_SYSTEM`, `_UNAVAILABLE_SYSTEM_PROMPT`).
   - Seven `push_*.py` scripts push other versions to the LangSmith hub.
   - `app/core/prompt_loader.py` pulls `latest` at runtime and silently falls back to the hard-coded copy if LangSmith fails.
   - So the prompt that runs depends on the network and on whatever was last pushed, not on the code.
   - `push_product_extraction_prompt.py` alone is 307 lines, with roughly 75 rule lines and 8 "NEVER"s.
3. **Keyword lists override the model's understanding:** `_GREETINGS`, `_POLICY_QUESTION_PHRASES`, `_COMPLAINT_KEYWORDS`, `_LEGAL_THREAT_KEYWORDS`, `_subcategory_in_message`, `_is_bare_order_lookup`, and the order-ID regex.
4. **The product graph has three overlapping fallback paths:** search → rank → broaden → retry_search → keyword_recovery → no_results, plus `RELAXATION_ORDER`. Ranking adds 8 hand-tuned weights in `product_agent_subgraph.py`.
5. **Each agent creates its own `ChatGroq`** with the model `qwen/qwen3.8-27b`. Groq retires models. A retired or wrong ID would break every agent at once, so check it first.
6. **The eval is weaker than its name.** `answer_relevancy` in `eval/config.yaml` "checks for expected phrases", and live eval uses `gpt-4o-mini`, a different provider from the app.

## Phase 1: Diagnose (no code changes)

1. Check the model ID against Groq's live list: GET `https://api.groq.com/openai/v1/models` with `GROQ_API_KEY` from `.env`. If it is gone, pick the closest current model and note it. Put the model name in one config value (`app/core/config.py`) that all agents use.
2. Run `pytest`. Then bring the stack up the way `README.md` describes (docker compose, database restore and migrations) and run `scripts/run_20_tests.py` and `test_live.py` against it. The last saved run (`test_suite_results.txt`) was 33/34.
3. Write `DIAGNOSIS.md` covering:
   - **What breaks:** each error or failing conversation, with its root cause and the file and line responsible.
   - **Guardrail inventory:** a table of every rule that overrides or steers the model, whether a code branch, keyword list or prompt rule. For each one:
     - where it is;
     - which commit added it and the conversation it was fixing (`git log -S`, `git blame`);
     - whether it protects something that must be exact (security, money, user data) or only steers behaviour.
   - **Prompt inventory:** every system prompt, where it lives (code, hub or both), its length, and whether the code and hub copies differ.
   - **Cost per turn:** how many LLM calls one user message makes on each path, and the average time per turn.

## Phase 2: Freeze a baseline before simplifying

Build `eval/baseline_conversations.json` with 40 to 60 multi-turn conversations:
- everything in `eval/dataset.json` and the 34 from `run_20_tests.py`/`test_suite_results.txt`;
- one conversation for each bug fixed in the git history, rebuilt from the commit message and diff. These are the cases the guards were added for, so they must keep passing.

Write `eval/run_baseline.py`, which:
- sends each conversation through the real graph;
- checks it with plain, explicit assertions: right agent chosen; right category, subcategory and brand; product results not empty when the catalog has matches; order ID found; cancellation only after confirmation and only for the user's own order; no error text;
- records pass/fail, LLM calls and time per turn.

Run it three times (the model is not perfectly deterministic) and save the numbers. This is the bar: **after simplifying, the pass rate must be the same or higher.**

## Phase 3: Simplify, one step at a time

After each step, run `pytest` and `run_baseline.py`. If the pass rate drops, fix it the simple way or revert that step, and record which you did.

1. **One home for prompts.**
   - Move every system prompt into `app/prompts/<name>.md` and load it from disk.
   - Remove the runtime hub pull and the silent fallback. LangSmith stays for tracing only.
   - Replace the seven `push_*.py` scripts with one optional `scripts/push_prompts.py`, or delete them.
2. **Let structured output do the guards' job.**
   - Give the extraction call a Pydantic schema via `llm.with_structured_output(...)`, with `category`/`subcategory` as enums built from the database catalog.
   - Pass the previous turn's preferences into the call and have the model return the complete updated preferences. This replaces the hand-written merge.
   - Then delete each post-processing branch in `extract_preferences` that the baseline shows is no longer needed.
3. **Shorten the prompts.** Aim for under about 40 lines per prompt.
   - Replace long rule lists with a short role description, the schema, and 3 to 6 worked examples taken from the baseline.
   - Keep "NEVER" only for real limits.
4. **Replace keyword lists with the router.**
   - The router already classifies intent. Fold greetings, policy questions, complaints and legal threats into its output, e.g. as a `severity`/`escalate` field.
   - Delete those lists unless the baseline needs them.
5. **One search fallback, not three.** Use one loop that relaxes filters in `RELAXATION_ORDER` order, then answers "no results". Merge `broaden_search`, `retry_search` and `keyword_recovery` if the baseline allows it.
6. **Keep the real guardrails**, deterministic and in code:
   - sign-in before orders and support;
   - an order must belong to the signed-in user;
   - cancellation needs explicit confirmation;
   - high-severity tickets go to a human.
   These are not over-engineering.
7. **Ranking (optional, last).** If fewer weights (for example rating, price fit and match) score the same on the baseline, use them.

Do not add new frameworks, agents or services. Simpler means fewer moving parts.

## Phase 4: Make it run end to end

- `pytest` passes.
- CI's lint and coverage steps pass locally (`.github/workflows/ci.yml`).
- The DeepEval gate passes in fixture mode. If live mode needs an OpenAI key you don't have, say so instead of changing the judge silently.
- `docker compose up`, then the chat UI at `/` handles a product search, an order lookup and a support complaint in one session.
- Update `README.md` where the architecture changed. Commit.

## Phase 5: Report

Write `SIMPLIFY_REPORT.md` in plain language. Adithya will read it in the morning.

1. Why it was broken: the root cause in two or three sentences.
2. A before/after table:
   - lines of prompt text;
   - number of guard branches and keyword lists;
   - number of graph nodes;
   - LLM calls per turn;
   - average seconds per turn;
   - baseline pass rate (mean of three runs).
3. What was removed and why it was safe, citing baseline cases.
4. What was kept and why.
5. What still fails or needs Adithya: keys, a model choice, and anything you reverted.
6. **Numbers for the portfolio.** Give two or three measured, honestly labelled figures. For example, "baseline: 52/56 conversations pass (3 runs)" or "median 1.4 s per turn on Groq". The project has no real users, so never word anything as usage. Also list any sentences in the portfolio's Multi-Agent case study (`../Portfolio-main/preview.html`) that are no longer true after the simplification. Do not edit the portfolio.
