# Architecture decision records

One file per decision that would be costly to reverse, or easy to undo by accident. Read the relevant ADR before changing what it covers. To change a decision, write a new ADR that supersedes it, and update only the old one's Status line.

| # | Decision | Status |
|---|---|---|
| [0001](0001-keep-router-and-agents.md) | Keep the router and three agents; rebuild only the product layer | Accepted |
| [0002](0002-guardrails-in-python.md) | Guardrails live in Python, not in prompts or model tools | Accepted, implemented |
| [0003](0003-prompts-in-repo.md) | Prompts live in the repo; no runtime hub pull | Accepted, implemented |
| [0004](0004-measure-before-changing.md) | Evals gate every change to prompts, search, data or models | Accepted |
| [0005](0005-structured-product-catalog.md) | Typed product catalog: types, brands and attributes as data | Accepted |
| [0006](0006-hybrid-search-pgvector.md) | Hybrid search with pgvector in the existing Postgres | Accepted, conditional on Phase 2 results |
| [0007](0007-search-state-in-postgres.md) | Search state in Postgres; refinements as patches | Accepted |
| [0008](0008-safety-floor.md) | Safety: model risk flag plus an escalate-only pattern | Accepted |

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
