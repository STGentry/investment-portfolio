"""Trade endpoints (audit trail + atomic position updates)."""

from datetime import date

from fastapi import APIRouter, HTTPException

from database import db
from models import TradeCreate, TradeRead
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