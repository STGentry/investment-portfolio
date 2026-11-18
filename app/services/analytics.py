"""Portfolio summary calculations shared by the API routes."""

from typing import Any

from database import db


def _to_float(value: Any, default: float = 0.0) -> float:
    return float(value) if value is not None else default


def _money(value: float) -> float:
    value = round(float(value), 2)
    return 0.0 if value == 0 else value


def _add_sector_industry_conditions(
    conditions: list, params: list, sector: str | None, industry: str | None
) -> None:
    """Append sector/industry filter conditions to an existing WHERE clause."""
    if sector is not None:
        conditions.append("LOWER(h.sector) = LOWER(?)")
        params.append(sector)
    if industry is not None:
        conditions.append("LOWER(h.industry) = LOWER(?)")
        params.append(industry)


def latest_price(conn, symbol: str, fallback: float | None = None) -> float | None:
    """Return the most recent close price for a symbol, or a fallback value."""
    row = conn.execute(
        "SELECT close_price FROM prices WHERE symbol = ? ORDER BY price_date DESC LIMIT 1",
        (symbol,),
    ).fetchone()
    if row is None:
        return fallback
    return float(row["close_price"])


def _holding_record(conn, row, splits: list[dict] | None = None) -> dict:
    """Build an API-ready holding record with derived valuation fields."""
    current_price = latest_price(conn, row["symbol"], fallback=row["entry_price"])
    quantity = float(row["quantity"])
    cost_basis = _to_float(row["cost_basis"])
    current_value = quantity * (current_price or 0.0)
    unrealized_pl = current_value - cost_basis
    pl_percent = (unrealized_pl / cost_basis * 100.0) if cost_basis else 0.0

    return {
        "holding_id": row["holding_id"],
        "symbol": row["symbol"],
        "quantity": quantity,
        "entry_price": row["entry_price"],
        "cost_basis": cost_basis,
        "dividend_amount": _to_float(row["dividend_amount"]),
        "dividend_frequency": row["dividend_frequency"],
        "sector": row["sector"],
        "industry": row["industry"],
        "last_updated": row["last_updated"],
        "current_price": current_price,
        "current_value": _money(current_value),
        "unrealized_pl": _money(unrealized_pl),
        "unrealized_pl_percent": _money(pl_percent),
        "splits": splits or [],
    }


def get_splits(conn, holding_id: int, owner_id: int | None = None) -> list[dict]:
    """Return split rows for a holding, optionally filtered by owner."""
    sql = """
        SELECT ho.owner_id, o.name AS owner_name, ho.percentage,
               ho.shares, ho.cost_basis
        FROM holding_owners ho
        JOIN owners o ON o.owner_id = ho.owner_id
        WHERE ho.holding_id = ?
    """
    params: list[Any] = [holding_id]
    if owner_id is not None:
        sql += " AND ho.owner_id = ?"
        params.append(owner_id)
    sql += " ORDER BY ho.owner_id"
    rows = conn.execute(sql, params).fetchall()
    return [
        {
            "owner_id": r["owner_id"],
            "owner_name": r["owner_name"],
            "percentage": float(r["percentage"]),
            "shares": float(r["shares"]),
            "cost_basis": float(r["cost_basis"]),
        }
        for r in rows
    ]


def get_holding(conn, symbol: str) -> dict:
    """Fetch a single holding with its splits and derived valuation fields."""
    row = conn.execute("SELECT * FROM holdings WHERE symbol = ?", (symbol,)).fetchone()
    if row is None:
        return {}
    return _holding_record(conn, row, get_splits(conn, row["holding_id"]))


def _owner_holding_rows(
    conn, owner_id: int, sector: str | None = None, industry: str | None = None
) -> list[dict]:
    """Account-level holdings with the owner's attributed share of each position."""
    conditions = ["ho.owner_id = ?"]
    params = [owner_id]
    _add_sector_industry_conditions(conditions, params, sector, industry)
    sql = """
        SELECT h.holding_id, h.symbol, h.quantity, h.entry_price, h.cost_basis,
               h.sector, h.industry, h.dividend_amount, h.dividend_frequency,
               h.last_updated, ho.percentage, ho.shares, ho.cost_basis AS split_cost_basis
        FROM holdings h
        JOIN holding_owners ho ON ho.holding_id = h.holding_id
        WHERE """ + " AND ".join(conditions) + """
        ORDER BY h.symbol
        """
    rows = conn.execute(sql, params).fetchall()

    records = []
    for row in rows:
        current_price = latest_price(conn, row["symbol"], fallback=row["entry_price"])
        shares = float(row["shares"])
        split_cost_basis = _to_float(row["split_cost_basis"])
        current_value = shares * (current_price or 0.0)
        unrealized_pl = current_value - split_cost_basis
        pl_percent = (unrealized_pl / split_cost_basis * 100.0) if split_cost_basis else 0.0
        records.append(
            {
                "symbol": row["symbol"],
                "quantity": shares,
                "entry_price": row["entry_price"],
                "cost_basis": split_cost_basis,
                "current_price": current_price,
                "current_value": current_value,
                "unrealized_pl": unrealized_pl,
                "unrealized_pl_percent": pl_percent,
                "percentage": float(row["percentage"]),
                "sector": row["sector"],
                "industry": row["industry"],
            }
        )
    return records


def summarize(records: list[dict]) -> dict:
    """Aggregate a list of holding records into portfolio totals."""
    total_cost_basis = sum(_to_float(r.get("cost_basis")) for r in records)
    total_current_value = sum(_to_float(r.get("current_value")) for r in records)
    unrealized_pl = total_current_value - total_cost_basis
    pl_percent = (unrealized_pl / total_cost_basis * 100.0) if total_cost_basis else 0.0

    top = sorted(records, key=lambda r: _to_float(r.get("current_value")), reverse=True)[:5]
    return {
        "total_positions": len(records),
        "total_cost_basis": _money(total_cost_basis),
        "total_current_value": _money(total_current_value),
        "unrealized_pl": _money(unrealized_pl),
        "pl_percent": _money(pl_percent),
        "top_holdings": [
            {
                "symbol": r["symbol"],
                "current_value": _money(r["current_value"]),
                "unrealized_pl": _money(r["unrealized_pl"]),
                "unrealized_pl_percent": _money(r["unrealized_pl_percent"]),
            }
            for r in top
        ],
    }


def get_portfolio_summary(
    sector: str | None = None, industry: str | None = None
) -> dict:
    """Portfolio-wide summary across all account holdings (no double counting)."""
    with db() as conn:
        conditions = []
        params = []
        _add_sector_industry_conditions(conditions, params, sector, industry)
        sql = """
            SELECT h.holding_id, h.symbol, h.quantity, h.entry_price, h.cost_basis,
                   h.sector, h.industry, h.dividend_amount, h.dividend_frequency,
                   h.last_updated
            FROM holdings h
        """
        if conditions:
            sql += " WHERE " + " AND ".join(conditions)
        sql += " ORDER BY h.symbol"
        rows = conn.execute(sql, params).fetchall()
        records = [_holding_record(conn, row) for row in rows]
        return summarize(records)


def get_owner_summary(
    owner_id: int, sector: str | None = None, industry: str | None = None
) -> dict:
    """Summary for a single owner using their attributed share of each position."""
    with db() as conn:
        owner = conn.execute(
            "SELECT owner_id, name FROM owners WHERE owner_id = ?", (owner_id,)
        ).fetchone()
        if owner is None:
            return {}
        records = _owner_holding_rows(conn, owner_id, sector, industry)
        summary = summarize(records)
        summary["owner_id"] = owner_id
        summary["owner_name"] = owner["name"]
        return summary