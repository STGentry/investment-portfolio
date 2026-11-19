"""Price refresh endpoints backed by Yahoo Finance (yfinance)."""

from datetime import datetime

from fastapi import APIRouter, HTTPException

from database import db

try:
    import yfinance as yf
except ImportError:  # pragma: no cover - depends on the environment
    yf = None

router = APIRouter()

# Payments per year for the frequency labels used across the app.
PAYMENTS_PER_FREQUENCY = {
    "monthly": 12,
    "quarterly": 4,
    "semi-annual": 2,
    "semiannual": 2,
    "semi annual": 2,
    "annual": 1,
}

FREQUENCY_LABELS = {
    12: "Monthly",
    4: "Quarterly",
    2: "Semi-Annual",
    1: "Annual",
}


def _as_float(value) -> float | None:
    """Best-effort conversion that tolerates missing or non-numeric values."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _latest_close(symbol: str) -> tuple[str, float] | None:
    """Return (price_date, close) for the most recent trading day, if any."""
    history = yf.Ticker(symbol).history(period="1d", interval="1d")
    close = history["Close"].dropna()
    if close.empty:
        return None
    price_date = close.index[-1].date().isoformat()
    return price_date, float(close.iloc[-1])


def _payment_dates(ticker) -> list[datetime]:
    """Payment timestamps from a ticker's dividend history, if available."""
    dividends = getattr(ticker, "dividends", None)
    if dividends is None:
        return []
    dates = []
    for stamp in getattr(dividends, "index", []):
        if hasattr(stamp, "to_pydatetime"):
            stamp = stamp.to_pydatetime()
        if isinstance(stamp, datetime):
            dates.append(stamp)
    return dates


def _payments_per_year(info, ticker) -> int | None:
    """How many dividend payments a symbol makes per year, if determinable."""
    frequency = info.get("dividendFrequency")
    if isinstance(frequency, str) and frequency.strip():
        payments = PAYMENTS_PER_FREQUENCY.get(frequency.strip().lower())
        if payments:
            return payments

    rate = _as_float(info.get("dividendRate"))
    last = _as_float(info.get("lastDividendValue"))
    if rate and last and last > 0:
        return max(1, min(12, round(rate / last)))

    try:
        dates = sorted(_payment_dates(ticker))
    except Exception:
        dates = []
    if len(dates) >= 2:
        gaps = sorted(
            (dates[index + 1] - dates[index]).days for index in range(len(dates) - 1)
        )
        gaps = [gap for gap in gaps if gap > 0]
        if gaps:
            median = gaps[len(gaps) // 2]
            if median > 0:
                return max(1, min(12, round(365 / median)))
    return None


def _latest_dividend(symbol: str) -> tuple[float, str]:
    """Return (dividend_amount, dividend_frequency) for a symbol via yfinance.

    ``dividend_amount`` is the amount paid per share for one dividend period,
    and ``dividend_frequency`` describes how often that period occurs.
    """
    ticker = yf.Ticker(symbol)
    info = getattr(ticker, "info", None) or {}
    rate = _as_float(info.get("dividendRate"))
    if rate is None or rate <= 0:
        return 0.0, "none"

    payments = _payments_per_year(info, ticker) or 1
    return rate / payments, FREQUENCY_LABELS.get(payments, "none")


@router.post("/prices/update")
def update_prices() -> dict:
    """Refresh latest close prices and dividend details for every holding."""
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
            price = None
            dividend = None
            try:
                price = _latest_close(symbol)
            except Exception:
                price = None
            try:
                dividend = _latest_dividend(symbol)
            except Exception:
                dividend = None

            entry = {"symbol": symbol}
            if price is not None:
                price_date, close_price = price
                conn.execute(
                    """
                    INSERT OR REPLACE INTO prices (symbol, price_date, close_price)
                    VALUES (?, ?, ?)
                    """,
                    (symbol, price_date, close_price),
                )
                entry["price_date"] = price_date
                entry["close_price"] = round(close_price, 2)
            if dividend is not None:
                amount, frequency = dividend
                conn.execute(
                    """
                    UPDATE holdings
                    SET dividend_amount = ?, dividend_frequency = ?,
                        last_updated = datetime('now')
                    WHERE symbol = ?
                    """,
                    (amount, frequency, symbol),
                )
                entry["dividend_amount"] = amount
                entry["dividend_frequency"] = frequency

            if price is None and dividend is None:
                skipped.append(symbol)
                continue
            updated.append(entry)

    return {
        "message": f"Updated {len(updated)} of {len(symbols)} prices",
        "updated": updated,
        "skipped": skipped,
    }