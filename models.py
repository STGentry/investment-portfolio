"""Pydantic request/response models for the portfolio API."""

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Owners
# ---------------------------------------------------------------------------

class OwnerCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)


class OwnerRead(BaseModel):
    owner_id: int
    name: str
    created_at: str


# ---------------------------------------------------------------------------
# Holdings
# ---------------------------------------------------------------------------

class HoldingCreate(BaseModel):
    symbol: str = Field(..., min_length=1, max_length=10)
    quantity: float = Field(..., gt=0)
    cost_basis: float | None = Field(default=None, ge=0)
    dividend_amount: float = Field(default=0.0, ge=0)
    dividend_frequency: str | None = Field(default=None)
    sector: str | None = Field(default=None, max_length=100)
    industry: str | None = Field(default=None, max_length=100)


class HoldingUpdate(BaseModel):
    quantity: float | None = Field(default=None, gt=0)
    cost_basis: float | None = Field(default=None, ge=0)
    dividend_amount: float | None = Field(default=None, ge=0)
    dividend_frequency: str | None = Field(default=None)
    sector: str | None = Field(default=None, max_length=100)
    industry: str | None = Field(default=None, max_length=100)


class HoldingOwnerSplit(BaseModel):
    owner_id: int
    owner_name: str
    percentage: float
    shares: float
    cost_basis: float


class HoldingRead(BaseModel):
    holding_id: int
    symbol: str
    quantity: float
    cost_basis: float | None
    dividend_amount: float
    dividend_frequency: str | None
    sector: str | None
    industry: str | None
    last_updated: str
    current_price: float | None
    current_value: float
    unrealized_pl: float
    unrealized_pl_percent: float
    splits: list[HoldingOwnerSplit]


class HoldingOwnerCreate(BaseModel):
    owner_id: int
    percentage: float = Field(..., gt=0, le=100)


# ---------------------------------------------------------------------------
# Trades
# ---------------------------------------------------------------------------

class TradeCreate(BaseModel):
    owner_id: int
    symbol: str = Field(..., min_length=1, max_length=10)
    trade_type: Literal["buy", "sell", "dividend"]
    quantity: float = Field(..., gt=0)
    price: float = Field(..., ge=0)
    trade_date: date | None = None
    notes: str | None = Field(default=None, max_length=500)


class TradeUpdate(BaseModel):
    """Partial update for an existing trade; omitted fields are left unchanged."""

    symbol: str | None = Field(default=None, min_length=1, max_length=10)
    trade_type: Literal["buy", "sell", "dividend"] | None = None
    quantity: float | None = Field(default=None, gt=0)
    price: float | None = Field(default=None, ge=0)
    trade_date: date | None = None
    notes: str | None = Field(default=None, max_length=500)


class TradeRead(BaseModel):
    trade_id: int
    owner_id: int
    owner_name: str
    symbol: str
    trade_type: str
    quantity: float
    price: float
    trade_date: str
    notes: str | None
    created_at: str


# ---------------------------------------------------------------------------
# Analytics
# ---------------------------------------------------------------------------

class HoldingSummary(BaseModel):
    symbol: str
    current_value: float
    unrealized_pl: float
    unrealized_pl_percent: float


class Summary(BaseModel):
    owner_id: int | None = None
    owner_name: str | None = None
    total_positions: int
    total_cost_basis: float
    total_current_value: float
    unrealized_pl: float
    pl_percent: float
    monthly_dividend: float = 0.0
    monthly_dividend_amount: float = 0.0
    top_holdings: list[HoldingSummary]