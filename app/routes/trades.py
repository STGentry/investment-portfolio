"""Trade endpoints (audit trail + atomic position updates)."""

from datetime import date

from fastapi import APIRouter, HTTPException

from database import db
from models import TradeCreate, TradeRead, TradeUpdate
from .holdings import _recalculate_splits

router = APIRouter()


def _serialize_trade(conn, row) -> TradeRead:
    owner = conn.execute(
        "SELECT name FROM owners WHERE owner_id = ?", (row["owner_id"],)
    ).fetchone()
    return TradeRead(
        trade_id=row["trade_id"],
        owner_id=row["owner_id"],
        owner_name=owner["name"] if owner else "",
        symbol=row["symbol"],
        trade_type=row["trade_type"],
        quantity=float(row["quantity"]),
        price=float(row["price"]),
        trade_date=row["trade_date"],
        notes=row["notes"],
        created_at=row["created_at"],
    )


def _list_trades(conn, owner_id=None, symbol=None, trade_type=None,
                 start_date=None, end_date=None) -> list[TradeRead]:
    clauses = []
    params = []
    if owner_id is not None:
        clauses.append("t.owner_id = ?")
        params.append(owner_id)
    if symbol is not None:
        clauses.append("t.symbol = ?")
        params.append(symbol)
    if trade_type is not None:
        clauses.append("t.trade_type = ?")
        params.append(trade_type)
    if start_date is not None:
        clauses.append("t.trade_date >= ?")
        params.append(start_date)
    if end_date is not None:
        clauses.append("t.trade_date <= ?")
        params.append(end_date)

    sql = "SELECT t.* FROM trades t"
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY t.trade_date DESC, t.trade_id DESC"

    rows = conn.execute(sql, params).fetchall()
    return [_serialize_trade(conn, row) for row in rows]


def _trade_deltas(trade_type: str, quantity: float, price: float) -> tuple[float, float]:
    """Return the (quantity, cost basis) deltas a trade applies to its holding."""
    quantity = float(quantity)
    price = float(price)
    if trade_type == "buy":
        return quantity, quantity * price
    if trade_type == "sell":
        return -quantity, -quantity * price
    # Dividends add income to the cost basis without changing the share count.
    return 0.0, quantity * price


def _apply_trade_delta(
    conn, symbol: str, quantity_delta: float, cost_basis_delta: float
) -> None:
    """Apply a trade's effect to a holding and refresh its ownership splits."""
    holding = conn.execute(
        "SELECT holding_id, quantity, cost_basis FROM holdings WHERE symbol = ?", (symbol,)
    ).fetchone()
    if holding is None:
        raise HTTPException(status_code=404, detail=f"Holding {symbol} not found")

    new_quantity = float(holding["quantity"]) + quantity_delta
    new_cost_basis = float(holding["cost_basis"] or 0.0) + cost_basis_delta
    if new_quantity <= 0:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Trade would leave {symbol} with {new_quantity} shares; "
                "the holding must stay above zero."
            ),
        )

    conn.execute(
        """
        UPDATE holdings SET quantity = ?, cost_basis = ?, last_updated = datetime('now')
        WHERE holding_id = ?
        """,
        (new_quantity, new_cost_basis, holding["holding_id"]),
    )
    _recalculate_splits(conn, symbol)


@router.get("/trades")
def list_trades(
    owner_id: int | None = None,
    symbol: str | None = None,
    type: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
) -> list[TradeRead]:
    """List trades with optional owner/symbol/type/date filters."""
    with db() as conn:
        return _list_trades(
            conn, owner_id=owner_id, symbol=symbol, trade_type=type,
            start_date=start_date, end_date=end_date,
        )


@router.get("/trades/{trade_id}", response_model=TradeRead)
def get_trade(trade_id: int) -> TradeRead:
    """Get one trade by id."""
    with db() as conn:
        row = conn.execute("SELECT t.* FROM trades t WHERE t.trade_id = ?", (trade_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail=f"Trade {trade_id} not found")
    with db() as conn:
        return _serialize_trade(conn, row)


@router.post("/trades", response_model=TradeRead, status_code=201)
def log_trade(data: TradeCreate) -> TradeRead:
    """Log a trade and atomically update holdings + splits."""
    trade_date = data.trade_date or date.today()

    with db() as conn:
        owner = conn.execute(
            "SELECT owner_id FROM owners WHERE owner_id = ?", (data.owner_id,)
        ).fetchone()
        if owner is None:
            raise HTTPException(status_code=404, detail=f"Owner {data.owner_id} not found")

        holding = conn.execute(
            "SELECT holding_id, quantity, cost_basis FROM holdings WHERE symbol = ?",
            (data.symbol,),
        ).fetchone()
        if holding is None:
            raise HTTPException(status_code=404, detail=f"Holding {data.symbol} not found")

        cursor = conn.execute(
            """
            INSERT INTO trades (owner_id, symbol, trade_type, quantity, price,
                                trade_date, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                data.owner_id,
                data.symbol,
                data.trade_type,
                data.quantity,
                data.price,
                trade_date.isoformat(),
                data.notes,
            ),
        )
        trade_id = cursor.lastrowid

        quantity = float(holding["quantity"])
        cost_basis = float(holding["cost_basis"] or 0.0)

        if data.trade_type == "buy":
            quantity += data.quantity
            cost_basis += data.quantity * data.price
        elif data.trade_type == "sell":
            if data.quantity >= quantity:
                raise HTTPException(
                    status_code=400,
                    detail=f"Insufficient shares: holding has {quantity} {data.symbol}",
                )
            quantity -= data.quantity
            cost_basis -= data.quantity * data.price
        else:  # dividend
            cost_basis += data.quantity * data.price

        conn.execute(
            """
            UPDATE holdings SET quantity = ?, cost_basis = ?, last_updated = datetime('now')
            WHERE holding_id = ?
            """,
            (quantity, cost_basis, holding["holding_id"]),
        )
        _recalculate_splits(conn, data.symbol)

        row = conn.execute("SELECT t.* FROM trades t WHERE t.trade_id = ?", (trade_id,)).fetchone()
        return _serialize_trade(conn, row)


@router.put("/trades/{trade_id}", response_model=TradeRead)
@router.patch("/trades/{trade_id}", response_model=TradeRead)
def update_trade(trade_id: int, data: TradeUpdate) -> TradeRead:
    """Update an existing trade and refresh every holding it affects.

    Only the fields present in the request body are changed; the owner of the
    trade is fixed. The previous trade is reversed and the new values applied so
    holdings quantity, cost basis, and ownership splits stay in sync.
    """
    with db() as conn:
        row = conn.execute(
            "SELECT t.* FROM trades t WHERE t.trade_id = ?", (trade_id,)
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail=f"Trade {trade_id} not found")

        owner = conn.execute(
            "SELECT owner_id FROM owners WHERE owner_id = ?", (row["owner_id"],)
        ).fetchone()
        if owner is None:
            raise HTTPException(status_code=404, detail=f"Owner {row['owner_id']} not found")

        provided = data.model_fields_set
        symbol = data.symbol if "symbol" in provided else row["symbol"]
        trade_type = data.trade_type if "trade_type" in provided else row["trade_type"]
        quantity = float(data.quantity) if "quantity" in provided else float(row["quantity"])
        price = float(data.price) if "price" in provided else float(row["price"])
        if "trade_date" in provided:
            trade_date = data.trade_date or date.today()
        else:
            trade_date = date.fromisoformat(row["trade_date"])
        notes = data.notes if "notes" in provided else row["notes"]

        new_holding = conn.execute(
            "SELECT holding_id FROM holdings WHERE symbol = ?", (symbol,)
        ).fetchone()
        if new_holding is None:
            raise HTTPException(status_code=404, detail=f"Holding {symbol} not found")

        old_symbol = row["symbol"]
        if old_symbol == symbol:
            old_qty, old_cost = _trade_deltas(row["trade_type"], row["quantity"], row["price"])
            new_qty, new_cost = _trade_deltas(trade_type, quantity, price)
            _apply_trade_delta(conn, symbol, new_qty - old_qty, new_cost - old_cost)
        else:
            # The trade moved to another symbol: reverse it from the old
            # holding first, then apply it to the new one.
            old_qty, old_cost = _trade_deltas(row["trade_type"], row["quantity"], row["price"])
            _apply_trade_delta(conn, old_symbol, -old_qty, -old_cost)
            new_qty, new_cost = _trade_deltas(trade_type, quantity, price)
            _apply_trade_delta(conn, symbol, new_qty, new_cost)

        conn.execute(
            """
            UPDATE trades SET symbol = ?, trade_type = ?, quantity = ?, price = ?,
                              trade_date = ?, notes = ?
            WHERE trade_id = ?
            """,
            (symbol, trade_type, quantity, price, trade_date.isoformat(), notes, trade_id),
        )

        row = conn.execute("SELECT t.* FROM trades t WHERE t.trade_id = ?", (trade_id,)).fetchone()
        return _serialize_trade(conn, row)


@router.delete("/trades/{trade_id}")
def delete_trade(trade_id: int) -> dict:
    """Delete a trade and reverse its effect on the holding."""
    with db() as conn:
        row = conn.execute(
            "SELECT t.* FROM trades t WHERE t.trade_id = ?", (trade_id,)
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail=f"Trade {trade_id} not found")

        quantity_delta, cost_basis_delta = _trade_deltas(
            row["trade_type"], row["quantity"], row["price"]
        )
        holding = conn.execute(
            "SELECT holding_id, quantity, cost_basis FROM holdings WHERE symbol = ?",
            (row["symbol"],),
        ).fetchone()

        if holding is not None:
            new_quantity = float(holding["quantity"]) - quantity_delta
            new_cost_basis = float(holding["cost_basis"] or 0.0) - cost_basis_delta
            if new_quantity <= 0:
                # The position is fully closed: remove the holding (splits cascade).
                conn.execute("DELETE FROM holdings WHERE holding_id = ?", (holding["holding_id"],))
            else:
                conn.execute(
                    """
                    UPDATE holdings SET quantity = ?, cost_basis = ?,
                                        last_updated = datetime('now')
                    WHERE holding_id = ?
                    """,
                    (new_quantity, new_cost_basis, holding["holding_id"]),
                )
                _recalculate_splits(conn, row["symbol"])

        conn.execute("DELETE FROM trades WHERE trade_id = ?", (trade_id,))
        return {"message": f"Trade {trade_id} deleted", "trade_id": trade_id}


@router.get("/owners/{owner_id}/trades")
def list_owner_trades(owner_id: int) -> list[TradeRead]:
    """Trades by owner."""
    with db() as conn:
        return _list_trades(conn, owner_id=owner_id)


@router.get("/holdings/{symbol}/trades")
def list_symbol_trades(symbol: str) -> list[TradeRead]:
    """Trades by symbol."""
    with db() as conn:
        return _list_trades(conn, symbol=symbol)