# Architecture decision records

One file per decision that would be costly to reverse, or easy to undo by accident. Read the relevant ADR before changing what it covers. To change a decision, write a new ADR that supersedes it, and update only the old one's Status line.

| # | Decision | Status |
|---|---|---|
| [0001](0001-keep-router-and-agents.md) | Keep the router and three agents; rebuild only the product layer | Accepted |
| [0002](0002-guardrails-in-python.md) | Guardrails live in Python, not in prompts or model tools | Accepted, implemented |
| [0003](0003-prompts-in-repo.md) | Prompts live in the repo; no runtime hub pull | Accepted, implemented |
| [0004](0004-measure-before-changing.md) | Evals gate every change to prompts, search, data or models | Accepted |
| [0005](0005-structured-product-catalog.md) | Typed product catalog: types, brands and attributes as data | Accepted |
| [0006](0006-hybrid-search-pgvector.md) | Hybrid search with pgvector in the existing Postgres | Accepted, implemented in Phase 3 (0014) |
| [0007](0007-search-state-in-postgres.md) | Search state in Postgres; refinements as patches | Accepted; storage superseded by 0009 |
| [0008](0008-safety-floor.md) | Safety: model risk flag plus an escalate-only pattern | Accepted, implemented (0015) |
| [0009](0009-langgraph-primitives.md) | Use LangGraph's built-in features instead of hand-written control flow | Accepted, implemented in Phase 2 (0012) |
| [0010](0010-prompt-budget.md) | Fix behaviour in code, data or tests, not with more prompt rules | Accepted |
| [0011](0011-catalog-words-resolved-in-code.md) | The model names the product; code resolves it against the catalog | Accepted, implemented |
| [0012](0012-phase-2-graph-contracts.md) | Phase 2 graph contracts: checkpointed state, cancel pause, chips, product grounding | Accepted, implemented |
| [0013](0013-judge-facing-priorities.md) | Order the remaining work by what a judge sees | Accepted |
| [0014](0014-hybrid-search-design.md) | Hybrid search: local embeddings, three fused lists, the catalog decides "we don't carry" | Accepted, implemented |
| [0015](0015-demo-never-breaks.md) | The demo never breaks: model fallback, answer cache, limits, identity, CI eval gate | Accepted, implemented |
| [0016](0016-product-qa-and-demo-shoppers.md) | Product questions through a read-only ToolNode loop; one-click demo shoppers; free single-service deploy | Accepted, implemented |
| [0017](0017-free-tier-capacity.md) | Free-tier capacity: fail fast, and report the share of real answers | Accepted (the user's choice) |
| [0018](0018-machine-independent-replays.md) | Replays depend on nothing machine-specific | Accepted, implemented |
| [0019](0019-main-is-live.md) | `main` is the live site: change it through a PR; every pool checks its connections | Accepted, implemented |

## Template
```markdown
# NNNN. Title
- **Status:** Proposed | Accepted | Superseded by NNNN
- **Date:** YYYY-MM-DD

## Context
What forced the decision, with evidence.

## Decision
What we do.

## Consequences
What gets easier, what gets harder, what it costs.

## Alternatives considered
What else was possible and why it lost.
```
