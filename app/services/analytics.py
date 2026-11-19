"""Portfolio summary calculations shared by the API routes."""

from typing import Any

from database import db


def _to_float(value: Any, default: float = 0.0) -> float:
    return float(value) if value is not None else default


def _money(value: float) -> float:
    value = round(float(value), 2)
    return 0.0 if value == 0 else value


# Months between dividend payments for the frequency labels used by the app.
DIVIDEND_MONTHS_PER_PAYMENT = {
    "monthly": 1,
    "quarterly": 3,
    "semi-annual": 6,
    "semiannual": 6,
    "semi annual": 6,
    "annual": 12,
}


def monthly_dividend_amount(records: list[dict]) -> float:
    """Estimated monthly dividend income for a list of holding records.

    ``dividend_amount`` is the amount paid per share for one period, so the
    total is prorated by how many months sit between dividend payments.
    """
    total = 0.0
    for record in records:
        amount = _to_float(record.get("dividend_amount"))
        quantity = _to_float(record.get("quantity"))
        frequency = str(record.get("dividend_frequency") or "none").strip().lower()
        months = DIVIDEND_MONTHS_PER_PAYMENT.get(frequency)
        if not months:
            continue
        total += amount * quantity / months
    return _money(total)


def _normalize_filter(values) -> list[str] | None:
    """Normalize repeated query values into a lowercase list, or None if empty."""
    if not values:
        return None
    cleaned = [str(value).strip().lower() for value in values if str(value).strip()]
    return cleaned or None


def add_sector_industry_conditions(
    conditions: list, params: list, sector, industry
) -> None:
    """Append sector/industry filter conditions to an existing WHERE clause.

    ``sector`` and ``industry`` may each be a single value or a list of values;
    any of the selected values matches (case-insensitive).
    """
    sectors = _normalize_filter(sector)
    if sectors:
        conditions.append("LOWER(h.sector) IN (" + ", ".join("?" for _ in sectors) + ")")
        params.extend(sectors)
    industries = _normalize_filter(industry)
    if industries:
        conditions.append("LOWER(h.industry) IN (" + ", ".join("?" for _ in industries) + ")")
        params.extend(industries)


def latest_price(conn, symbol: str, fallback: float | None = None) -> float | None:
    """Return the most recent close price for a symbol, or a fallback value."""
    row = conn.execute(
        "SELECT close_price FROM prices WHERE symbol = ? ORDER BY price_date DESC LIMIT 1",
        (symbol,),
    ).fetchone()
    if row is None:
        return fallback
    return float(row["close_price"])


def cost_basis_from_trades(conn, symbol: str) -> float:
    """Total cost basis for a symbol, derived from its trade history.

    Buys and dividends add to the basis, sells subtract from it.
    """
    row = conn.execute(
        """
        SELECT COALESCE(SUM(
            CASE trade_type
                WHEN 'buy' THEN quantity * price
                WHEN 'sell' THEN -quantity * price
                ELSE quantity * price
            END
        ), 0.0) AS cost_basis
        FROM trades
        WHERE symbol = ?
        """,
        (symbol,),
    ).fetchone()
    return float(row["cost_basis"] or 0.0)


def _holding_record(conn, row, splits: list[dict] | None = None) -> dict:
    """Build an API-ready holding record with derived valuation fields."""
    quantity = float(row["quantity"])
    cost_basis = _to_float(row["cost_basis"])
    fallback_price = (cost_basis / quantity) if quantity else None
    current_price = latest_price(conn, row["symbol"], fallback=fallback_price)
    current_value = quantity * (current_price or 0.0)
    unrealized_pl = current_value - cost_basis
    pl_percent = (unrealized_pl / cost_basis * 100.0) if cost_basis else 0.0

    return {
        "holding_id": row["holding_id"],
        "symbol": row["symbol"],
        "quantity": quantity,
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
    conn, owner_id: int, sector=None, industry=None
) -> list[dict]:
    """Account-level holdings with the owner's attributed share of each position."""
    conditions = ["ho.owner_id = ?"]
    params = [owner_id]
    add_sector_industry_conditions(conditions, params, sector, industry)
    sql = """
        SELECT h.holding_id, h.symbol, h.quantity, h.cost_basis,
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
        shares = float(row["shares"])
        split_cost_basis = _to_float(row["split_cost_basis"])
        fallback_price = (split_cost_basis / shares) if shares else None
        current_price = latest_price(conn, row["symbol"], fallback=fallback_price)
        current_value = shares * (current_price or 0.0)
        unrealized_pl = current_value - split_cost_basis
        pl_percent = (unrealized_pl / split_cost_basis * 100.0) if split_cost_basis else 0.0
        records.append(
            {
                "symbol": row["symbol"],
                "quantity": shares,
                "cost_basis": split_cost_basis,
                "current_price": current_price,
                "current_value": current_value,
                "unrealized_pl": unrealized_pl,
                "unrealized_pl_percent": pl_percent,
                "percentage": float(row["percentage"]),
                "sector": row["sector"],
                "industry": row["industry"],
                "dividend_amount": _to_float(row["dividend_amount"]),
                "dividend_frequency": row["dividend_frequency"],
            }
        )
    return records


def summarize(records: list[dict]) -> dict:
    """Aggregate a list of holding records into portfolio totals."""
    total_cost_basis = sum(_to_float(r.get("cost_basis")) for r in records)
    total_current_value = sum(_to_float(r.get("current_value")) for r in records)
    unrealized_pl = total_current_value - total_cost_basis
    pl_percent = (unrealized_pl / total_cost_basis * 100.0) if total_cost_basis else 0.0

    monthly_dividend = monthly_dividend_amount(records)
    top = sorted(records, key=lambda r: _to_float(r.get("current_value")), reverse=True)[:5]
    return {
        "total_positions": len(records),
        "total_cost_basis": _money(total_cost_basis),
        "total_current_value": _money(total_current_value),
        "unrealized_pl": _money(unrealized_pl),
        "pl_percent": _money(pl_percent),
        "monthly_dividend": monthly_dividend,
        "monthly_dividend_amount": monthly_dividend,
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
    sector=None, industry=None
) -> dict:
    """Portfolio-wide summary across all account holdings (no double counting)."""
    with db() as conn:
        conditions = []
        params = []
        add_sector_industry_conditions(conditions, params, sector, industry)
        sql = """
            SELECT h.holding_id, h.symbol, h.quantity, h.cost_basis,
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
    owner_id: int, sector=None, industry=None
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