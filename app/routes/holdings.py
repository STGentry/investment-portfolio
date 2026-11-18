"""Holding, owner-split, and valuation endpoints."""

from fastapi import APIRouter, HTTPException

from database import db
from models import HoldingCreate, HoldingOwnerCreate, HoldingRead, HoldingUpdate
from ..services.analytics import get_holding, get_splits, latest_price

router = APIRouter()

SORTABLE_FIELDS = {
    "symbol": "symbol",
    "quantity": "quantity",
    "cost_basis": "cost_basis",
    "current_value": "current_value",
    "unrealized_pl": "unrealized_pl",
    "pl_percent": "unrealized_pl_percent",
}


def _require_holding(conn, symbol: str) -> None:
    row = conn.execute("SELECT holding_id FROM holdings WHERE symbol = ?", (symbol,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail=f"Holding {symbol} not found")


def _require_owner(conn, owner_id: int) -> None:
    row = conn.execute("SELECT owner_id FROM owners WHERE owner_id = ?", (owner_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail=f"Owner {owner_id} not found")


def _recalculate_splits(conn, symbol: str) -> None:
    """Recompute derived shares and cost basis for every split of a symbol."""
    _require_holding(conn, symbol)
    holding = conn.execute(
        "SELECT holding_id, quantity, cost_basis FROM holdings WHERE symbol = ?", (symbol,)
    ).fetchone()
    quantity = float(holding["quantity"])
    cost_basis = float(holding["cost_basis"] or 0.0)
    rows = conn.execute(
        "SELECT owner_id, percentage FROM holding_owners WHERE holding_id = ?",
        (holding["holding_id"],),
    ).fetchall()
    for row in rows:
        pct = float(row["percentage"]) / 100.0
        conn.execute(
            "UPDATE holding_owners SET shares = ?, cost_basis = ? WHERE holding_id = ? AND owner_id = ?",
            (quantity * pct, cost_basis * pct, holding["holding_id"], row["owner_id"]),
        )


def _serialize_splits(conn, symbol: str) -> list[dict]:
    _require_holding(conn, symbol)
    holding = conn.execute("SELECT holding_id FROM holdings WHERE symbol = ?", (symbol,)).fetchone()
    return get_splits(conn, holding["holding_id"])


@router.get("/holdings", response_model=list[HoldingRead])
def list_holdings(
    owner_id: int | None = None,
    sector: str | None = None,
    industry: str | None = None,
    sort_by: str = "symbol",
) -> list[HoldingRead]:
    """List positions with optional owner/sector/industry filters and sorting."""
    if sort_by not in SORTABLE_FIELDS:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid sort_by '{sort_by}'. Allowed: {', '.join(sorted(SORTABLE_FIELDS))}",
        )
    with db() as conn:
        conditions = []
        params = []
        if owner_id is not None:
            conditions.append(
                "h.symbol IN (SELECT DISTINCT h2.symbol FROM holdings h2 "
                "JOIN holding_owners ho ON ho.holding_id = h2.holding_id "
                "WHERE ho.owner_id = ?)"
            )
            params.append(owner_id)
        if sector is not None:
            conditions.append("LOWER(h.sector) = LOWER(?)")
            params.append(sector)
        if industry is not None:
            conditions.append("LOWER(h.industry) = LOWER(?)")
            params.append(industry)
        sql = "SELECT symbol FROM holdings h"
        if conditions:
            sql += " WHERE " + " AND ".join(conditions)
        symbols = conn.execute(sql, params).fetchall()

        records = [get_holding(conn, row["symbol"]) for row in symbols]
        key = SORTABLE_FIELDS[sort_by]
        records.sort(key=lambda r: (r[key] is None, r[key]))
    return records


@router.get("/holdings/{symbol}", response_model=HoldingRead)
def get_holding_by_symbol(symbol: str) -> HoldingRead:
    """Get one position with its splits and current valuation."""
    with db() as conn:
        record = get_holding(conn, symbol)
    if not record:
        raise HTTPException(status_code=404, detail=f"Holding {symbol} not found")
    return record


@router.post("/holdings", response_model=HoldingRead, status_code=201)
def upsert_holding(data: HoldingCreate) -> HoldingRead:
    """Create or update a position."""
    entry_price = data.entry_price
    cost_basis = data.cost_basis
    if entry_price is None and cost_basis is not None:
        entry_price = cost_basis / data.quantity
    if cost_basis is None and entry_price is not None:
        cost_basis = data.quantity * entry_price

    with db() as conn:
        existing = conn.execute(
            "SELECT holding_id FROM holdings WHERE symbol = ?", (data.symbol,)
        ).fetchone()
        if existing is None:
            conn.execute(
                """
                INSERT INTO holdings (symbol, quantity, entry_price, cost_basis,
                                      dividend_amount, dividend_frequency, sector, industry)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    data.symbol,
                    data.quantity,
                    entry_price,
                    cost_basis,
                    data.dividend_amount,
                    data.dividend_frequency or "none",
                    data.sector,
                    data.industry,
                ),
            )
        else:
            fields = data.model_dump(exclude_unset=True)
            assignments = []
            params = []
            for field in ("quantity", "entry_price", "cost_basis", "dividend_amount",
                          "dividend_frequency", "sector", "industry"):
                if field in fields:
                    assignments.append(f"{field} = ?")
                    params.append(fields[field])
            assignments.append("last_updated = datetime('now')")
            params.append(data.symbol)
            conn.execute(
                f"UPDATE holdings SET {', '.join(assignments)} WHERE symbol = ?", params
            )
            if "quantity" in fields or "cost_basis" in fields:
                _recalculate_splits(conn, data.symbol)
        record = get_holding(conn, data.symbol)
    return record


@router.put("/holdings/{symbol}", response_model=HoldingRead)
def update_holding(symbol: str, data: HoldingUpdate) -> HoldingRead:
    """Partially update position fields."""
    updates = data.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(status_code=400, detail="No fields provided to update")

    with db() as conn:
        _require_holding(conn, symbol)
        assignments = []
        params = []
        for field, value in updates.items():
            assignments.append(f"{field} = ?")
            params.append(value)
        assignments.append("last_updated = datetime('now')")
        params.append(symbol)
        conn.execute(f"UPDATE holdings SET {', '.join(assignments)} WHERE symbol = ?", params)
        if "quantity" in updates or "cost_basis" in updates:
            _recalculate_splits(conn, symbol)
        record = get_holding(conn, symbol)
    return record


@router.delete("/holdings/{symbol}")
def delete_holding(symbol: str) -> dict:
    """Remove a position (splits cascade)."""
    with db() as conn:
        _require_holding(conn, symbol)
        conn.execute("DELETE FROM holdings WHERE symbol = ?", (symbol,))
    return {"message": f"Holding {symbol} deleted", "symbol": symbol}


@router.get("/holdings/{symbol}/owners")
def get_holding_splits(symbol: str) -> list[dict]:
    """All ownership splits for a symbol."""
    with db() as conn:
        return _serialize_splits(conn, symbol)


@router.post("/holdings/{symbol}/owners")
def add_or_update_split(symbol: str, split: HoldingOwnerCreate) -> list[dict]:
    """Add or update one ownership split, then recalculate derived values."""
    with db() as conn:
        _require_holding(conn, symbol)
        _require_owner(conn, split.owner_id)
        holding = conn.execute(
            "SELECT holding_id FROM holdings WHERE symbol = ?", (symbol,)
        ).fetchone()
        conn.execute(
            """
            INSERT INTO holding_owners (holding_id, owner_id, percentage, shares, cost_basis)
            VALUES (?, ?, ?, 0, 0)
            ON CONFLICT(holding_id, owner_id)
            DO UPDATE SET percentage = excluded.percentage
            """,
            (holding["holding_id"], split.owner_id, split.percentage),
        )
        _recalculate_splits(conn, symbol)
        return _serialize_splits(conn, symbol)


@router.put("/holdings/{symbol}/owners")
def recalculate_splits(
    symbol: str, splits: list[HoldingOwnerCreate] | HoldingOwnerCreate | None = None
) -> list[dict]:
    """Apply new split percentages (optional) and recalculate all splits for a symbol."""
    with db() as conn:
        _require_holding(conn, symbol)
        holding = conn.execute(
            "SELECT holding_id FROM holdings WHERE symbol = ?", (symbol,)
        ).fetchone()

        if splits is not None:
            updates = splits if isinstance(splits, list) else [splits]
            for split in updates:
                _require_owner(conn, split.owner_id)
                conn.execute(
                    """
                    INSERT INTO holding_owners (holding_id, owner_id, percentage, shares, cost_basis)
                    VALUES (?, ?, ?, 0, 0)
                    ON CONFLICT(holding_id, owner_id)
                    DO UPDATE SET percentage = excluded.percentage
                    """,
                    (holding["holding_id"], split.owner_id, split.percentage),
                )
            if isinstance(splits, list):
                total = conn.execute(
                    "SELECT SUM(percentage) AS total FROM holding_owners WHERE holding_id = ?",
                    (holding["holding_id"],),
                ).fetchone()["total"]
                if total is None or abs(float(total) - 100.0) > 0.05:
                    raise HTTPException(
                        status_code=422,
                        detail=f"Ownership percentages must sum to 100% (currently {total})",
                    )

        _recalculate_splits(conn, symbol)
        return _serialize_splits(conn, symbol)