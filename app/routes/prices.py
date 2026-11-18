"""Price refresh endpoints backed by Yahoo Finance (yfinance)."""

from fastapi import APIRouter, HTTPException

from database import db

try:
    import yfinance as yf
except ImportError:  # pragma: no cover - depends on the environment
    yf = None

router = APIRouter()


def _latest_close(symbol: str) -> tuple[str, float] | None:
    """Return (price_date, close) for the most recent trading day, if any."""
    history = yf.Ticker(symbol).history(period="1d", interval="1d")
    close = history["Close"].dropna()
    if close.empty:
        return None
    price_date = close.index[-1].date().isoformat()
    return price_date, float(close.iloc[-1])


@router.post("/prices/update")
def update_prices() -> dict:
    """Refresh the latest close price for every tracked symbol via yfinance."""
    if yf is None:
        raise HTTPException(
            status_code=503,
            detail="yfinance is not installed; run 'pip install -r requirements.txt'",
        )

    with db() as conn:
        rows = conn.execute("SELECT symbol FROM holdings ORDER BY symbol").fetchall()
        symbols = [row["symbol"] for row in rows]
        if not symbols:
            return {"message": "No holdings to update", "updated": [], "skipped": []}

        updated = []
        skipped = []
        for symbol in symbols:
            try:
                result = _latest_close(symbol)
            except Exception:
                result = None
            if result is None:
                skipped.append(symbol)
                continue
            price_date, close_price = result
            conn.execute(
                """
                INSERT OR REPLACE INTO prices (symbol, price_date, close_price)
                VALUES (?, ?, ?)
                """,
                (symbol, price_date, close_price),
            )
            updated.append(
                {
                    "symbol": symbol,
                    "price_date": price_date,
                    "close_price": round(close_price, 2),
                }
            )

    return {
        "message": f"Updated {len(updated)} of {len(symbols)} prices",
        "updated": updated,
        "skipped": skipped,
    }