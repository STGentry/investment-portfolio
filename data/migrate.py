"""One-shot migration from the Google Sheets export into SQLite.

Run with: python -m data.migrate
"""

import argparse
import csv
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import settings
from database import db, init_db, is_migration_done

BASE_DIR = Path(__file__).resolve().parent
SEED_CSV = BASE_DIR / "seed_portfolio.csv"


def load_rows(csv_path: str) -> list[dict]:
    with open(csv_path, newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def cost_basis_from_trades(conn, symbol: str) -> float:
    """Total cost basis for a symbol, derived from its trade history."""
    row = conn.execute(
        """
        SELECT COALESCE(SUM(
            CASE trade_type
                WHEN 'buy' THEN quantity * price
                WHEN 'sell' THEN -quantity * price
                ELSE quantity * price
            END
        ), 0.0)
        FROM trades
        WHERE symbol = ?
        """,
        (symbol,),
    ).fetchone()
    return float(row[0] or 0.0)


def migrate(csv_path: str = str(SEED_CSV), db_path: str | None = None) -> dict:
    """Import seed rows into the database. Idempotent: skips if owners exist."""
    if is_migration_done(db_path):
        print("Migration already ran (owners table is not empty). Skipping.")
        return {"status": "skipped"}

    rows = load_rows(csv_path)
    if not rows:
        raise SystemExit(f"No rows found in {csv_path}")

    owner_names: list[str] = []
    holdings: dict[str, dict] = {}
    splits: list[dict] = []

    for row in rows:
        owner = (row.get("owner") or "").strip()
        symbol = (row.get("symbol") or "").strip()
        if not owner or not symbol:
            continue
        quantity = float(row["qty"])
        pct_raw = (row.get("pct") or "").strip()
        last_close = float(row["last_close"])
        sector = (row.get("sector") or "").strip() or None
        industry = (row.get("industry") or "").strip() or None

        if owner not in owner_names:
            owner_names.append(owner)

        holding = holdings.setdefault(
            symbol,
            {"quantity": 0.0, "sector": None, "industry": None, "last_close": last_close},
        )
        holding["quantity"] += quantity
        if holding["sector"] is None:
            holding["sector"] = sector
        if holding["industry"] is None:
            holding["industry"] = industry

        splits.append(
            {
                "owner": owner,
                "symbol": symbol,
                "quantity": quantity,
                "percentage": float(pct_raw) if pct_raw else None,
                "last_close": last_close,
            }
        )

    with db(db_path) as conn:
        owner_ids: dict[str, int] = {}
        for name in owner_names:
            conn.execute("INSERT OR IGNORE INTO owners (name) VALUES (?)", (name,))
            owner_ids[name] = conn.execute(
                "SELECT owner_id FROM owners WHERE name = ?", (name,)
            ).fetchone()["owner_id"]

        holding_ids: dict[str, int] = {}
        for symbol, holding in holdings.items():
            cursor = conn.execute(
                """
                INSERT INTO holdings
                    (symbol, quantity, cost_basis, dividend_amount,
                     dividend_frequency, sector, industry)
                VALUES (?, ?, ?, 0, 'none', ?, ?)
                """,
                (
                    symbol,
                    holding["quantity"],
                    cost_basis_from_trades(conn, symbol),
                    holding["sector"],
                    holding["industry"],
                ),
            )
            holding_ids[symbol] = cursor.lastrowid

        split_count = 0
        for split in splits:
            holding = holdings[split["symbol"]]
            percentage = (
                split["percentage"]
                if split["percentage"] is not None
                else split["quantity"] / holding["quantity"] * 100.0
            )
            conn.execute(
                """
                INSERT INTO holding_owners
                    (holding_id, owner_id, percentage, shares, cost_basis)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    holding_ids[split["symbol"]],
                    owner_ids[split["owner"]],
                    percentage,
                    split["quantity"],
                    split["quantity"] * split["last_close"],
                ),
            )
            split_count += 1

        today = date.today().isoformat()
        for symbol, holding in holdings.items():
            conn.execute(
                "INSERT OR IGNORE INTO prices (symbol, price_date, close_price) VALUES (?, ?, ?)",
                (symbol, today, holding["last_close"]),
            )

    result = {
        "status": "migrated",
        "owners": len(owner_names),
        "holdings": len(holdings),
        "splits": split_count,
        "prices": len(holdings),
    }
    print(
        "Migration complete: "
        f"{result['owners']} owners, {result['holdings']} holdings, "
        f"{result['splits']} splits, {result['prices']} prices."
    )
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Migrate seed portfolio data into SQLite.")
    parser.add_argument("--csv", default=str(SEED_CSV), help="Path to the seed CSV file")
    parser.add_argument("--db", default=None, help="Override database path")
    args = parser.parse_args()

    init_db(args.db)
    migrate(args.csv, args.db)


if __name__ == "__main__":
    main()