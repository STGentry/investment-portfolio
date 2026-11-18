"""One-shot migration of the historic trade log into SQLite.

Run with: python migrate_trades.py

The CSV has no owner column, so each trade is attributed to the owner with the
largest current split for that symbol (see _owner_for_symbol). Ties and symbols
without a split fall back to the lowest owner_id.
"""

import argparse
import csv
from datetime import datetime
from pathlib import Path

from database import db, init_db

BASE_DIR = Path(__file__).resolve().parent
TRADES_CSV = BASE_DIR / "data" / "trans_history.csv"
IMPORT_NOTES = "Historic import from trans_history.csv"


def load_rows(csv_path: str) -> list[dict]:
    with open(csv_path, newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _owner_for_symbol(conn, symbol: str) -> int:
    """Derive the owner for a symbol from its largest current split."""
    row = conn.execute(
        """
        SELECT owner_id, SUM(percentage) AS percentage
        FROM holding_owners
        WHERE holding_id = (SELECT holding_id FROM holdings WHERE symbol = ?)
        GROUP BY owner_id
        ORDER BY percentage DESC, owner_id ASC
        LIMIT 1
        """,
        (symbol,),
    ).fetchone()
    if row is not None:
        return row["owner_id"]

    # Fallback for symbols without a split: the primary account holder.
    fallback = conn.execute(
        "SELECT owner_id FROM owners ORDER BY owner_id LIMIT 1"
    ).fetchone()
    return fallback["owner_id"]


def migrate(csv_path: str = str(TRADES_CSV), db_path: str | None = None) -> dict:
    """Import historic trades into the trades table. Idempotent."""
    rows = load_rows(csv_path)
    if not rows:
        raise SystemExit(f"No rows found in {csv_path}")

    with db(db_path) as conn:
        existing = conn.execute(
            "SELECT COUNT(*) AS count FROM trades WHERE notes = ?", (IMPORT_NOTES,)
        ).fetchone()["count"]
        if existing:
            print(f"Historic trades already imported ({existing} rows). Skipping.")
            return {"status": "skipped", "trades": existing}

        inserted = 0
        for row in rows:
            trade_type = (row.get("Type") or "").strip().lower()
            symbol = (row.get("Symbol") or "").strip()
            if trade_type not in ("buy", "sell", "dividend") or not symbol:
                continue

            trade_date = datetime.strptime(
                row["Date"].strip(), "%m/%d/%Y"
            ).date().isoformat()
            owner_id = _owner_for_symbol(conn, symbol)

            conn.execute(
                """
                INSERT INTO trades (owner_id, symbol, trade_type, quantity, price,
                                    trade_date, notes)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    owner_id,
                    symbol,
                    trade_type,
                    float(row["Qty"]),
                    float(row["Price"]),
                    trade_date,
                    IMPORT_NOTES,
                ),
            )
            inserted += 1

    print(f"Historic trade import complete: {inserted} trades.")
    return {"status": "migrated", "trades": inserted}


def main() -> None:
    parser = argparse.ArgumentParser(description="Import the historic trade log into SQLite.")
    parser.add_argument("--csv", default=str(TRADES_CSV), help="Path to the trade history CSV file")
    parser.add_argument("--db", default=None, help="Override database path")
    args = parser.parse_args()

    init_db(args.db)
    migrate(args.csv, args.db)


if __name__ == "__main__":
    main()