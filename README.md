# Investment Portfolio Web App

A local web application for tracking an investment portfolio. It runs on a single
machine (the "app server") and stores data in SQLite. 

## Features

- Single brokerage account with multiple owners sharing positions by percentage
- Fractional share quantities
- Full audit trail of all buy/sell/dividend trades
- Dashboard, trade entry form, ownership split editor, and visualizations (static HTML/CSS, no build step)

## Requirements

- Python 3.11+
- `pip` (standard library `sqlite3` is used for the database)

## Setup

Install dependencies (system-wide, no virtual environment):

```bash
pip install -r requirements.txt
```

> If `python` on your PATH points at a different interpreter, use the Python 3.11
> launcher explicitly: `py -3.11 -m pip install -r requirements.txt`.

## Initialize the database (first run only)

```bash
python -m data.migrate
python -m data.migrate_trades
```

This imports `data/seed_portfolio.csv` and creates the owners, holdings, ownership
splits, and today's price snapshots, then imports `data/trans_history.csv` and
recomputes each holding's cost basis from the trade prices. Both scripts are
idempotent: they skip when their data is already present.

## Run the app

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```
```powershell
PS C:...\investment-portfolio> Start-Process -FilePath "py" -ArgumentList "-3.11","-m","uvicorn","app.main:app","--host","0.0.0.0","--port","8000" -WorkingDirectory (Get-Location) -RedirectStandardOutput "server.log" -RedirectStandardError "server.err.log" -NoNewWindow; Start-Sleep -Seconds 4; echo "=== server.err.log ==="; Get-Content server.err.log -Tail 20; echo "=== server.log ==="; Get-Content server.log -Tail 10
```

Open <http://localhost:8000> for the dashboard.

## Configuration

`.env` (loaded by `config.py`):

```env
# Local database path
DB_PATH=portfolio.db
```

## API

Base URL: `http://localhost:8000/api/v1`

| Method | Route | Description |
| --- | --- | --- |
| GET | `/owners` | List all owners |
| GET | `/owners/{owner_id}` | Get owner details |
| GET | `/holdings` | List positions (`?owner_id=`, `?sector=` (repeatable), `?industry=` (repeatable), `?sort_by=`, `?order=asc\|desc`) |
| GET | `/holdings/{symbol}` | Get one position |
| POST | `/holdings` | Create/upsert position |
| PUT | `/holdings/{symbol}` | Update position fields |
| DELETE | `/holdings/{symbol}` | Remove position (splits cascade) |
| GET | `/holdings/{symbol}/owners` | All splits for a symbol |
| POST | `/holdings/{symbol}/owners` | Add/update one split |
| PUT | `/holdings/{symbol}/owners` | Apply splits and recalculate all splits for a symbol |
| GET | `/trades` | List trades (`?owner_id=`, `?symbol=`, `?type=`, `?start_date=`, `?end_date=`) |
| GET | `/trades/{trade_id}` | Get one trade |
| POST | `/trades` | Log a trade (atomically updates holdings + splits) |
| GET | `/owners/{owner_id}/trades` | Trades by owner |
| GET | `/holdings/{symbol}/trades` | Trades by symbol |
| GET | `/analytics/summary` | Portfolio summary (all owners) |
| GET | `/analytics/summary?owner_id=1` | Summary for one owner |
| GET | `/analytics/summary?sector=&industry=` | Summary filtered by sector and/or industry (repeatable params match any selection) |
| POST | `/prices/update` | Refresh latest close prices and dividend amount/frequency for all holdings via Yahoo Finance (yfinance) |


## Project Structure

```
investment-portfolio/
├── .env
├── requirements.txt
├── config.py                  # Configuration loader
├── database.py                # DB connection + schema init
├── models.py                  # Pydantic request/response schemas
├── recompute_cost_basis.py    # Recalculate cost basis from the trades table
├── tests/
│   └── verify_app.py          # End-to-end API verification script
├── app/
│   ├── __init__.py
│   ├── main.py                # FastAPI app bootstrap
│   ├── routes/
│   │   ├── __init__.py
│   │   ├── owners.py
│   │   ├── holdings.py
│   │   └── trades.py
│   ├── services/
│   │   ├── __init__.py
│   │   └── analytics.py       # Summary calculations
│   └── static/
│       ├── index.html         # Dashboard
│       ├── trades.html        # Trade entry form
│       ├── holdings_edit.html # Holdings editor
│       ├── visualizations.html # Charts (bought/sold vs current quantity)
│       └── css/style.css
└── data/
    └── seed_portfolio.csv     # Migration source data
    └── migrate.py             # Data migration script
    └── migrate_trades.py      # data migration script
    └── trans_history.csv      # migration source data
```
