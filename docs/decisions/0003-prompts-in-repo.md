# 0003. Prompts live in the repo; no runtime hub pull
- **Status:** Accepted, implemented on `simplify-agents`
- **Date:** 2026-11-18 (records the design of that branch)

## Context
The earlier work pulled prompts from the LangSmith hub at runtime and silently fell back to copies in code. Three of the prompts that actually ran were older hub copies that differed from git. One of them carried a frozen catalog list that put calculators in the wrong category.

## Decision
- Every prompt is a Markdown file in `app/prompts/`, loaded by `app/core/prompt_loader.py`. The file in git is the prompt that runs.
- No hub pull, no fallback, no push scripts.
- Keep each prompt short (under ~40 lines) and free of product facts, which belong in the database (0005).

## Consequences
- A prompt change is a reviewed diff, measured like any code change (0004).
- LangSmith is used for traces only.
