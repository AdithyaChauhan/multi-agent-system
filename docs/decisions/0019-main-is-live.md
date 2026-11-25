# 0019. `main` is the live site: change it through a PR; every pool checks its connections
- **Status:** Accepted, implemented (Phase 5)
- **Date:** 2026-11-24

## Context
- **Render deploys every push to `main` on its own** (`autoDeploy` in `render.yaml`) and doesn't wait for CI. The live site went up on 2026-11-24 from PR #3.
- **CI's ship stages** (push the image, Kubernetes) used to run for four branches, three of them old leftovers.
- **Neon's free plan suspends the database after 5 idle minutes** and closes every connection. The first live check returned HTTP 500 on the first turns after a quiet spell: the LangGraph checkpointer's psycopg pool handed out dead connections. Reproduced by suspending Neon through its API: 2 of 3 messages failed.
- **Neon offers a pooled (PgBouncer) address and a direct one.** The checkpointer prepares its statements (`prepare_threshold=0`), which transaction pooling breaks.
- **Render's free plan gives a workspace 750 instance-hours a month.** Keep-warm keeps one service awake around the clock, about 720 hours.

## Decision
- **`main` changes only through a PR with green CI.** Every change is a short branch; the user merges.
- **Publishing and deploying run only on a push to `main`** (the `push-image` and `deploy` jobs). Helm is pinned to the version the chart was checked with (v3.16.4).
- **Every Postgres pool checks its connections:**
  - SQLAlchemy: `pool_pre_ping` and a 300 s recycle (already in place);
  - the checkpointer: `check=ConnectionPool.check_connection` and `max_idle=240` s, under Neon's suspend.
- **Neon's direct (unpooled) connection string,** in the same region as Render (Singapore).
- **One free Render service only.** Old services and blueprints are deleted, not kept around.
- **Secrets live only in Render's dashboard and the git-ignored `.env.deploy`:** the database URL, the Groq key and the Discord webhook.

## Consequences
- A broken merge reaches users within minutes, so the PR's CI is the real gate.
- The first turn after an idle spell takes about 2 s longer while Neon wakes, and none fail.
- A second always-on service would exceed the free hours.
- The live checks are repeatable: the Neon suspend test and the judge path (`docs/plans/phase-5-ship-and-showcase.md`, Results).

## Alternatives considered
- **Render's own "wait for CI" option:** not checked on the free plan; the PR rule covers it.
- **Neon's pooled address:** breaks the checkpointer's prepared statements.
- **Render's free Postgres:** it expires after 30 days.
- **Keeping the old `ci-fix-cicd` services:** they used free hours and could clash with the new service's name.
