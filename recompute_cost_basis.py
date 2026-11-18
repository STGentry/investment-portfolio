"""Recompute cost basis from the trades table.

Run with: python recompute_cost_basis.py

Holdings quantity and holding_owners shares are left untouched: the seeded
quantity also reflects dividend reinvestments that are not in the trade log.
For every symbol that has trades, cost basis is recalculated as:

    sum(buy qty * price) - sum(sell qty * price) + sum(dividend qty * price)

and each ownership split is set to its percentage share of the new basis.
The operation is idempotent: running it again produces the same values.
"""

import argparse

from database import db, init_db


COST_BASIS_SQL = """
UPDATE holdings
SET cost_basis = (
    SELECT
        SUM(CASE WHEN t.trade_type = 'buy' THEN t.quantity * t.price ELSE 0 END)
      - SUM(CASE WHEN t.trade_type = 'sell' THEN t.quantity * t.price ELSE 0 END)
      + SUM(CASE WHEN t.trade_type = 'dividend' THEN t.quantity * t.price ELSE 0 END)
    FROM trades t
    WHERE t.symbol = holdings.symbol
),
last_updated = datetime('now')
WHERE symbol IN (SELECT DISTINCT symbol FROM trades)
"""

SPLITS_SQL = """
UPDATE holding_owners
SET cost_basis = (
    SELECT h.cost_basis * holding_owners.percentage / 100.0
    FROM holdings h
    WHERE h.holding_id = holding_owners.holding_id
)
WHERE holding_id IN (
    SELECT holding_id FROM holdings
    WHERE symbol IN (SELECT DISTINCT symbol FROM trades)
)
"""


def recompute(db_path: str | None = None) -> dict:
    """Recompute cost basis for every symbol that has trades. Idempotent."""
    with db(db_path) as conn:
        before = {
            row["symbol"]: float(row["cost_basis"] or 0.0)
            for row in conn.execute("SELECT symbol, cost_basis FROM holdings")
        }

        conn.execute(COST_BASIS_SQL)
        conn.execute(SPLITS_SQL)

        after = {
            row["symbol"]: float(row["cost_basis"] or 0.0)
            for row in conn.execute("SELECT symbol, cost_basis FROM holdings")
        }

    changed = [
        (symbol, before.get(symbol, 0.0), after[symbol])
        for symbol in sorted(after)
        if abs(after[symbol] - before.get(symbol, 0.0)) > 1e-9
    ]
    for symbol, old, new in changed:
        print(f"  {symbol:6} cost basis {old:>10.2f} -> {new:>10.2f}")
    print(f"Recomputed cost basis for {len(changed)} symbols with trades.")

    return {"status": "recomputed", "symbols": len(changed)}


def main() -> None:
    parser = argparse.ArgumentParser(description="Recompute cost basis from the trades table.")
    parser.add_argument("--db", default=None, help="Override database path")
    args = parser.parse_args()

    init_db(args.db)
    recompute(args.db)


if __name__ == "__main__":
    main()