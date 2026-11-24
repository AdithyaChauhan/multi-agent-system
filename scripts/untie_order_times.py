#!/usr/bin/env python3
"""Give orders that share a created_at distinct times, keeping the order they are listed in today.

Seeded orders were inserted with one timestamp per user (demo-user-1's five share one), so "newest
first" left their order to Postgres, which returns tied rows in storage order. That order shifts
after updates. It made the router prompt ("Their orders: ...") differ between runs, and CI's replay
missed its recordings on 2026-11-24.

Within each tied group this keeps the order Postgres returns now and sets each later row
1 microsecond older; the eval users' groups (PINNED) take the order their recordings saw. No date
or second shown anywhere changes. fetch_user_orders also breaks ties by id, so new ties can't drift.

    python scripts/untie_order_times.py                  # multi_agent_baseline
    python scripts/untie_order_times.py --dry-run
    python scripts/untie_order_times.py --database-url <url>

Then rebuild the CI fixture (scripts/make_ci_fixture.py).
"""

import argparse
import sys
from datetime import timedelta
from pathlib import Path

from sqlalchemy import create_engine, text

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
from eval.run_baseline import DEFAULT_DB  # noqa: E402

# The eval users' tied groups, in the order the recorded router prompts list them. Recovered on
# 2026-11-24 by trying each ordering against the recordings' keys (every recorded call matched one,
# the same one throughout). Positions past the prompt's 8-order cut aren't recorded; any order works.
PINNED = [
    ["ORD-2002", "ORD-2004", "ORD-2005", "ORD-2001", "ORD-2003"],
    ["ORD-1002", "ORD-1001"],
    ["ORD-T902", "ORD-T903", "ORD-T904", "ORD-T905", "ORD-T901"],
    ["ORD-9901", "ORD-9903", "ORD-9904", "ORD-9902", "ORD-9905"],
]
PINNED_IDS = {o for group in PINNED for o in group}

TIED = """
    SELECT user_id, created_at FROM orders
    WHERE created_at IS NOT NULL
    GROUP BY user_id, created_at HAVING count(*) > 1
"""
# The app's own query, without the tie-breaker: the order the recordings saw.
AS_LISTED = "SELECT id, order_id, created_at FROM orders WHERE user_id = :u ORDER BY created_at DESC"
MOVE = "UPDATE orders SET created_at = :t WHERE order_id = :o"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--database-url", default=DEFAULT_DB)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    engine = create_engine(args.database_url)
    with engine.begin() as conn:
        groups = conn.execute(text(TIED)).all()
        changed = 0
        for user_id, stamp in groups:
            rows = [r for r in conn.execute(text(AS_LISTED), {"u": user_id}).all() if r.created_at == stamp]
            if any(r.order_id in PINNED_IDS for r in rows):
                continue  # set below, in the recorded order
            for k, row in enumerate(rows[1:], start=1):
                changed += 1
                if not args.dry_run:
                    conn.execute(text(MOVE), {"t": stamp - timedelta(microseconds=k), "o": row.order_id})
        for group in PINNED:
            stamps = dict(
                conn.execute(
                    text("SELECT order_id, created_at FROM orders WHERE order_id = ANY(:g)"), {"g": group}
                ).all()
            )
            if len(stamps) != len(group):
                continue  # not this database's eval users
            newest = max(stamps.values())
            for k, order_id in enumerate(group):
                if stamps[order_id] != newest - timedelta(microseconds=k):
                    changed += 1
                    if not args.dry_run:
                        conn.execute(text(MOVE), {"t": newest - timedelta(microseconds=k), "o": order_id})
        left = conn.execute(text(TIED)).all()
    print(
        f"{len(groups)} tied groups, {changed} orders {'would be' if args.dry_run else ''} moved; ties left: {len(left)}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
