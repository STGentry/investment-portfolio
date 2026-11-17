"""SQLite database connection helpers and schema initialization."""

import sqlite3
from contextlib import contextmanager

from config import settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS owners (
    owner_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS holdings (
    holding_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol          TEXT NOT NULL UNIQUE,
    quantity        REAL NOT NULL CHECK (quantity > 0),
    entry_price     REAL,
    cost_basis      REAL,
    dividend_amount REAL DEFAULT 0,
    dividend_frequency TEXT,
    sector          TEXT,
    industry        TEXT,
    last_updated    TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS holding_owners (
    holding_id  INTEGER NOT NULL,
    owner_id    INTEGER NOT NULL,
    percentage  REAL NOT NULL CHECK (percentage > 0 AND percentage <= 100),
    shares      REAL NOT NULL,
    cost_basis  REAL NOT NULL,
    PRIMARY KEY (holding_id, owner_id),
    FOREIGN KEY (holding_id) REFERENCES holdings(holding_id) ON DELETE CASCADE,
    FOREIGN KEY (owner_id)   REFERENCES owners(owner_id)   ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS trades (
    trade_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    owner_id    INTEGER NOT NULL,
    symbol      TEXT NOT NULL,
    trade_type  TEXT NOT NULL CHECK (trade_type IN ('buy', 'sell', 'dividend')),
    quantity    REAL NOT NULL,
    price       REAL NOT NULL,
    trade_date  TEXT NOT NULL,
    notes       TEXT,
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (owner_id) REFERENCES owners(owner_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS prices (
    price_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol      TEXT NOT NULL,
    price_date  TEXT NOT NULL,
    close_price REAL NOT NULL,
    UNIQUE (symbol, price_date)
);

CREATE INDEX IF NOT EXISTS idx_holdings_symbol ON holdings(symbol);
CREATE INDEX IF NOT EXISTS idx_holding_owners_owner ON holding_owners(owner_id);
CREATE INDEX IF NOT EXISTS idx_trades_owner_date ON trades(owner_id, trade_date DESC);
CREATE INDEX IF NOT EXISTS idx_trades_symbol ON trades(symbol);
CREATE INDEX IF NOT EXISTS idx_prices_symbol_date ON prices(symbol, price_date);
"""


def get_connection(db_path: str | None = None):
    """Open a SQLite connection with row access by name and FK enforcement."""
    path = db_path or settings.DB_PATH
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def db(db_path: str | None = None):
    """Context manager yielding a connection; commits on success, rolls back on error."""
    conn = get_connection(db_path)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db(db_path: str | None = None) -> None:
    """Create tables and indexes if they do not already exist."""
    conn = get_connection(db_path)
    try:
        conn.executescript(SCHEMA)
        conn.commit()
    finally:
        conn.close()


def is_migration_done(db_path: str | None = None) -> bool:
    """Migration is considered done once at least one owner exists."""
    conn = get_connection(db_path)
    try:
        row = conn.execute("SELECT COUNT(*) AS count FROM owners").fetchone()
        return row["count"] > 0
    finally:
        conn.close()