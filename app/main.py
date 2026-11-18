"""FastAPI application bootstrap: static frontend + API routers."""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.staticfiles import StaticFiles

from database import init_db
from models import Summary
from .routes import holdings, owners, prices, trades
from .services import analytics

STATIC_DIR = Path(__file__).resolve().parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(
    title="Investment Portfolio API",
    description="Local portfolio tracker with owner-level position splits.",
    version="1.0.0",
    lifespan=lifespan,
)

# API routers are registered before the catch-all static mount so that
# /api/v1/* requests are handled by the API.
app.include_router(owners.router, prefix="/api/v1", tags=["owners"])
app.include_router(holdings.router, prefix="/api/v1", tags=["holdings"])
app.include_router(trades.router, prefix="/api/v1", tags=["trades"])
app.include_router(prices.router, prefix="/api/v1", tags=["prices"])


@app.get("/api/v1/analytics/summary", response_model=Summary)
def portfolio_summary(
    owner_id: int | None = None,
    sector: list[str] | None = Query(None),
    industry: list[str] | None = Query(None),
):
    """Portfolio summary for all owners, or for a single owner."""
    if owner_id is None:
        return analytics.get_portfolio_summary(sector=sector, industry=industry)
    summary = analytics.get_owner_summary(owner_id, sector=sector, industry=industry)
    if not summary:
        raise HTTPException(status_code=404, detail=f"Owner {owner_id} not found")
    return summary


app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")