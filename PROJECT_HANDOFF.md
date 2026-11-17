Investment Portfolio Web App - Implementation Handoff



1\. Project Overview



Build a local web application for tracking an investment portfolio. The app runs on a single machine (the "app server") and connects to a separate Ollama server on the local network for future ML analysis. Current scope: portfolio dashboard, trade entry, and ownership reallocation.



Key requirements:











Single brokerage account with multiple owners (Dad, Emmett) sharing positions by percentage







Fractional share quantities (e.g., 91.65996)







Full audit trail of all buy/sell trades







Data migration from existing Google Sheets export







No DRIP transaction tracking







Bare-metal install (no Docker, no virtual environments)



2\. Architecture



┌─────────────────────────────────────────────────────────┐

│                    APP SERVER (this machine)            │

│  ┌────────────┐    ┌──────────────┐    ┌───────────────┐│

│  │  FastAPI   │    │   SQLite     │    │  Static HTML  ││

│  │  Backend   │───▶│  Database    │    │  Frontend     ││

│  │  (single   │    │  (portfolio  │    │  (dashboard,  ││

│  │   process) │    │   data)      │    │   trade form, ││

│  └────────────┘    └──────────────┘    │   holdings    ││

│                                        │   editor)     ││

│                                        └───────────────┘│

└───────────────────────────┬─────────────────────────────┘

&#x20;                           │ HTTP (future: Ollama API)

&#x20;                           ▼

&#x20;                ┌───────────────────────┐

&#x20;                │   OLLAMA SERVER       │

&#x20;                │   (separate hardware) │

&#x20;                └───────────────────────┘





Design decisions:











Single FastAPI process serves both API and static HTML (simplest deployment)







SQLite for persistence (no external DB server needed)







Ollama integration deferred to future phase (do not implement now)







Synchronous request/response model throughout



3\. Technology Stack











Language: Python 3.11+







Web framework: FastAPI + Uvicorn







Database: SQLite (stdlib sqlite3 or SQLAlchemy)







Config: python-dotenv for .env variables







Frontend: Static HTML/CSS served by FastAPI (no build step, no JS framework required)







Dependencies (requirements.txt):



fastapi

uvicorn\[standard]

python-dotenv





&#x20;Add pandas only if needed for migration script.



4\. Project Structure



investment-portfolio/

├── .env                          # OLLAMA\_API\_URL (future), DB\_PATH

├── requirements.txt

├── config.py                     # Configuration loader

├── database.py                   # DB connection + schema init

├── models.py                     # Data classes / Pydantic schemas

├── migrate.py                    # Data migration script (Section 8)

├── app/

│   ├── \_\_init\_\_.py

│   ├── main.py                   # FastAPI app bootstrap

│   ├── routes/

│   │   ├── \_\_init\_\_.py

│   │   ├── owners.py             # Owner endpoints

│   │   ├── holdings.py           # Holding + split endpoints

│   │   └── trades.py             # Trade endpoints

│   ├── services/

│   │   ├── \_\_init\_\_.py

│   │   └── analytics.py          # Summary calculations

│   └── static/

│       ├── index.html            # Dashboard (Section 7.1)

│       ├── trades.html           # Trade entry form (Section 7.2)

│       ├── holdings\_edit.html    # Holdings editor (Section 7.3)

│       └── css/style.css

└── data/

&#x20;   └── seed\_portfolio.csv        # Migration source data (Section 8)





5\. Database Schema (SQLite)



5.1 owners



CREATE TABLE owners (

&#x20;   owner\_id   INTEGER PRIMARY KEY AUTOINCREMENT,

&#x20;   name       TEXT NOT NULL UNIQUE,

&#x20;   created\_at TEXT NOT NULL DEFAULT (datetime('now'))

);





5.2 holdings (account-level positions - one row per symbol)



CREATE TABLE holdings (

&#x20;   holding\_id      INTEGER PRIMARY KEY AUTOINCREMENT,

&#x20;   symbol          TEXT NOT NULL UNIQUE,

&#x20;   quantity        REAL NOT NULL CHECK (quantity > 0),

&#x20;   entry\_price     REAL,

&#x20;   cost\_basis      REAL,

&#x20;   dividend\_amount REAL DEFAULT 0,

&#x20;   dividend\_frequency TEXT,        -- 'quarterly' | 'annually' | 'monthly' | 'none'

&#x20;   sector          TEXT,

&#x20;   industry        TEXT,

&#x20;   last\_updated    TEXT NOT NULL DEFAULT (datetime('now'))

);





5.3 holding\_owners (ownership splits per position)



CREATE TABLE holding\_owners (

&#x20;   holding\_id  INTEGER NOT NULL,

&#x20;   owner\_id    INTEGER NOT NULL,

&#x20;   percentage  REAL NOT NULL CHECK (percentage > 0 AND percentage <= 100),

&#x20;   shares      REAL NOT NULL,      -- derived: holdings.quantity \* percentage/100

&#x20;   cost\_basis  REAL NOT NULL,      -- derived: holdings.cost\_basis \* percentage/100

&#x20;   PRIMARY KEY (holding\_id, owner\_id),

&#x20;   FOREIGN KEY (holding\_id) REFERENCES holdings(holding\_id) ON DELETE CASCADE,

&#x20;   FOREIGN KEY (owner\_id)   REFERENCES owners(owner\_id)   ON DELETE CASCADE

);





5.4 trades (audit trail - owner-attributed)



CREATE TABLE trades (

&#x20;   trade\_id    INTEGER PRIMARY KEY AUTOINCREMENT,

&#x20;   owner\_id    INTEGER NOT NULL,

&#x20;   symbol      TEXT NOT NULL,

&#x20;   trade\_type  TEXT NOT NULL CHECK (trade\_type IN ('buy', 'sell', 'dividend')),

&#x20;   quantity    REAL NOT NULL,

&#x20;   price       REAL NOT NULL,

&#x20;   trade\_date  TEXT NOT NULL,      -- YYYY-MM-DD

&#x20;   notes       TEXT,

&#x20;   created\_at  TEXT NOT NULL DEFAULT (datetime('now')),

&#x20;   FOREIGN KEY (owner\_id) REFERENCES owners(owner\_id) ON DELETE CASCADE

);





5.5 prices (historical price snapshots)



CREATE TABLE prices (

&#x20;   price\_id    INTEGER PRIMARY KEY AUTOINCREMENT,

&#x20;   symbol      TEXT NOT NULL,

&#x20;   price\_date  TEXT NOT NULL,      -- YYYY-MM-DD

&#x20;   close\_price REAL NOT NULL,

&#x20;   UNIQUE (symbol, price\_date)

);





5.6 Indexes



CREATE INDEX idx\_holdings\_symbol ON holdings(symbol);

CREATE INDEX idx\_holding\_owners\_owner ON holding\_owners(owner\_id);

CREATE INDEX idx\_trades\_owner\_date ON trades(owner\_id, trade\_date DESC);

CREATE INDEX idx\_trades\_symbol ON trades(symbol);

CREATE INDEX idx\_prices\_symbol\_date ON prices(symbol, price\_date);





Calculated fields (computed at query time, NOT stored):











current\_value = quantity \* current\_price







unrealized\_pl = (current\_price - entry\_price) \* quantity







allocation\_pct = current\_value / owner\_total\_value \* 100







Owner shares = holdings.quantity \* holding\_owners.percentage / 100



6\. API Endpoints (FastAPI)



Base URL: http://localhost:8000/api/v1



6.1 Owners















Method







Route







Description











GET







/owners







List all owners











GET







/owners/{owner\_id}







Get owner details



6.2 Holdings















Method







Route







Description











GET







/holdings







List all positions (?owner\_id=1, ?sector=, ?sort\_by=)











GET







/holdings/{symbol}







Get one position











POST







/holdings







Create/upsert position











PUT







/holdings/{symbol}







Update position fields











DELETE







/holdings/{symbol}







Remove position (cascade splits)



6.3 Owner Splits















Method







Route







Description











GET







/holdings/{symbol}/owners







All splits for a symbol











GET







/owners/{owner\_id}/holdings







All positions for an owner











POST







/holdings/{symbol}/owners







Add/update split ({"owner\_id": 2, "percentage": 44.0})











PUT







/holdings/{symbol}/owners







Recalculate all splits for symbol



6.4 Trades















Method







Route







Description











GET







/trades







List trades (?owner\_id=, ?symbol=, ?type=, ?start\_date=, ?end\_date=)











GET







/trades/{trade\_id}







Get one trade











POST







/trades







Log trade (owner\_id, symbol, trade\_type, quantity, price, trade\_date, notes)











GET







/owners/{owner\_id}/trades







Trades by owner











GET







/holdings/{symbol}/trades







Trades by symbol



Critical behavior: POST /trades must atomically:











Insert trade record







Update holdings.quantity and cost\_basis (account totals)







Recalculate all holding\_owners rows for that symbol



6.5 Analytics















Method







Route







Description











GET







/analytics/summary







Portfolio summary (all owners)











GET







/analytics/summary?owner\_id=1







Summary for one owner



Summary response includes: total positions, cost basis, current value, unrealized P\&L, P\&L %, top holdings.



7\. Frontend Screens (Static HTML + CSS)



Serve via FastAPI StaticFiles mount at / with API at /api/v1.



7.1 Dashboard (index.html)











Owner selector dropdown (Dad / Emmett / All)







Summary cards: total cost basis, current value, unrealized P\&L, P\&L %







Holdings table: symbol, quantity, owner split %, cost basis, current price, current value, unrealized P\&L, sector







Price data sourced from /api/v1/holdings and /api/v1/holdings/{symbol}/owners







Simple, clean styling (no external dependencies required)



7.2 Trade Entry Form (trades.html)











Fields: owner (dropdown), symbol (text), trade type (buy/sell), quantity (decimal), price (decimal), trade date (date), notes (optional)







Submit via fetch() POST to /api/v1/trades







Show success/error message; refresh holdings table after submit







No DRIP/dividend reinvestment transaction option



7.3 Holdings Editor (holdings\_edit.html)











Table of all holdings with ownership splits per owner







Editable percentage inputs per owner per holding







Validate: percentages for a holding must sum to 100%







Submit via PUT to /api/v1/holdings/{symbol}/owners







Show recalculated shares and cost basis per owner after save



8\. Data Migration (migrate.py)



8.1 Source Data



Create data/seed\_portfolio.csv with this exact content (from current Google Sheet export):



owner,symbol,qty,pct,sector,industry,last\_close

Dad,SGI,30,,Consumer Discretionary,Mattress Manufacturing \& Retail,60.76

Dad,OHI,91.65996,56,Real Estate,Skilled Nursing Facilities,47.05

Dad,CODI,122.1893,,Financials,Middle-Market Private Equity,11.64

Dad,SBRA,116.0973,,Real Estate,Senior Housing \& Care,20.44

Dad,DOC,190.431,,Real Estate,Medical Offices \& Life Science,19.98

Dad,OKE,53.475534,63,Energy,Midstream Pipelines \& Processing,89.75

Dad,LTC,146.8732,,Real Estate,Senior Housing Assets,43.28

Dad,STAG,55.45655,50,Real Estate,Warehouses \& Logistics,36.97

Dad,VTR,77.8826,,Real Estate,Broad Medical \& Senior Living,88.92

Dad,O,61.2594,,Real Estate,Retail Commercial Leases,58.82

Dad,BIPC,47.596,,Utilities,Global Infrastructure \& Data,39.56

Dad,FLNG,136.2929,,Energy,Liquefied Natural Gas Shipping,25.48

Dad,VICI,42.8555,,Real Estate,Casino \& Entertainment,25.01

Dad,DUK,33,,Utilities,Public Electric Supplier,129.16

Emmett,STAG,55.45655,50,Real Estate,Warehouses \& Logistics,36.97

Emmett,MO,30.4508,,Consumer Staples,Tobacco \& Smoke-Free Nicotine,78.64

Emmett,OKE,31.406266,37,Energy,Midstream Pipelines \& Processing,89.75

Emmett,OHI,72.01854,44,Real Estate,Skilled Nursing Facilities,47.05





8.2 Migration Logic











Create owners: Insert "Dad" and "Emmett" into owners table.







Aggregate holdings: Group CSV rows by symbol, sum quantities into holdings.quantity. Set sector, industry, entry\_price = last\_close, cost\_basis = quantity \* entry\_price, dividend\_amount = 0, dividend\_frequency = 'none'.







Create splits: For each (owner, symbol), insert into holding\_owners with percentage from CSV (if blank, calculate as owner\_qty / total\_qty \* 100), shares = owner\_qty, cost\_basis = owner\_qty \* last\_close.







Seed prices: Insert one prices row per symbol with today's date and last\_close value.







Idempotency: Check if migration already ran (e.g., owners table non-empty); skip if so.



Run with: python migrate.py



9\. Configuration (.env)



\# Future Ollama integration (not used yet)

OLLAMA\_API\_URL=http://<ollama-server-ip>:11434



\# Local database path

DB\_PATH=portfolio.db





10\. Implementation Steps (for coding agent)











Create project structure per Section 4







Write requirements.txt per Section 3







Implement database.py with schema from Section 5 (init on startup)







Implement config.py and .env loading







Implement app/main.py with StaticFiles mount + API router







Implement routes per Section 6 (owners, holdings, splits, trades, analytics)







Create static HTML files per Section 7 (dashboard, trade form, holdings editor)







Create migrate.py per Section 8 with seed CSV







Test end-to-end: run migration, start server, verify all 3 screens work







Document run instructions in README.md



11\. Testing Checklist











Migration creates 2 owners, 15 unique symbols, correct split percentages







Dashboard loads and shows correct totals for each owner







Trade entry: log a buy, verify holdings quantity and cost basis update







Trade entry: log a sell, verify quantity decreases correctly







Holdings editor: change ownership percentage, verify shares recalculate and sum to 100%







API returns proper JSON for all documented endpoints







App starts with uvicorn app.main:app --reload from project root



12\. Run Instructions



\# Install dependencies (system-wide, no virtualenv)

pip install -r requirements.txt



\# Initialize database (first run only)

python migrate.py



\# Start the app

uvicorn app.main:app --host 0.0.0.0 --port 8000



\# Access at http://localhost:8000





Known deferred items (do NOT implement now):











Ollama image analysis / candle processing







Authentication (local-only app)







DRIP transaction tracking







Docker/container deployment





