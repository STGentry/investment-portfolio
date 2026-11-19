"""Temporary end-to-end verification for the portfolio app (deleted after use)."""

import json
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:8000"

passed = 0
failed = 0


def check(name, condition, detail=""):
    global passed, failed
    if condition:
        passed += 1
        print(f"PASS  {name}")
    else:
        failed += 1
        print(f"FAIL  {name} {detail}")


def request(method, path, payload=None):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method)
    if data:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = resp.read().decode()
            content_type = resp.headers.get("Content-Type", "")
            if "application/json" in content_type:
                return resp.status, json.loads(body)
            return resp.status, body
    except urllib.error.HTTPError as exc:
        body = exc.read().decode()
        try:
            parsed = json.loads(body)
        except json.JSONDecodeError:
            parsed = {"raw": body}
        return exc.code, parsed


# --- Static frontend -------------------------------------------------------
status, index_html = request("GET", "/")
check("GET / serves dashboard", status == 200 and "Investment Portfolio" in index_html)
status, trades_html = request("GET", "/trades.html")
check("GET /trades.html serves trade form", status == 200 and "Log Trade" in trades_html)
status, editor_html = request("GET", "/holdings_edit.html")
check("GET /holdings_edit.html serves editor", status == 200 and "Holdings Editor" in editor_html)
status, css = request("GET", "/css/style.css")
check("GET /css/style.css serves stylesheet", status == 200 and "body" in css)

# --- Owners ----------------------------------------------------------------
status, owners = request("GET", "/api/v1/owners")
check("GET /owners returns 200", status == 200)
check("GET /owners returns 2 owners", isinstance(owners, list) and len(owners) == 2, str(owners))
check("Owner names are Dad and Emmett",
      sorted(o["name"] for o in owners) == ["Dad", "Emmett"], str(owners))

status, dad = request("GET", "/api/v1/owners/1")
check("GET /owners/1 returns Dad", status == 200 and dad["name"] == "Dad", str(dad))
status, _ = request("GET", "/api/v1/owners/999")
check("GET /owners/999 returns 404", status == 404)

# --- Holdings --------------------------------------------------------------
status, holdings = request("GET", "/api/v1/holdings")
check("GET /holdings returns 200", status == 200)
check("GET /holdings returns 15 positions", len(holdings) == 15, f"got {len(holdings)}")
symbols = sorted(h["symbol"] for h in holdings)
check("15 unique symbols", len(set(symbols)) == 15, str(symbols))
check("Holdings include computed valuation fields",
      all("current_value" in h and "unrealized_pl" in h and "current_price" in h for h in holdings))
check("Holdings no longer expose entry_price",
      all("entry_price" not in h for h in holdings))
check("Holdings include splits", all(len(h["splits"]) >= 1 for h in holdings))

status, dad_holdings = request("GET", "/api/v1/holdings?owner_id=1")
check("GET /holdings?owner_id=1 returns Dad's 14 positions", len(dad_holdings) == 14, f"got {len(dad_holdings)}")
status, emmett_holdings = request("GET", "/api/v1/holdings?owner_id=2")
check("GET /holdings?owner_id=2 returns Emmett's 4 positions", len(emmett_holdings) == 4, f"got {len(emmett_holdings)}")
status, re_holdings = request("GET", "/api/v1/holdings?sector=Real%20Estate")
check("GET /holdings?sector=Real Estate returns 8 positions", len(re_holdings) == 8, f"got {len(re_holdings)}")
status, sorted_holdings = request("GET", "/api/v1/holdings?sort_by=current_value")
values = [h["current_value"] for h in sorted_holdings]
check("sort_by=current_value sorts ascending", values == sorted(values))
status, _ = request("GET", "/api/v1/holdings?sort_by=bogus")
check("Invalid sort_by returns 400", status == 400)

status, sgi = request("GET", "/api/v1/holdings/SGI")
check("GET /holdings/SGI returns the position", status == 200 and sgi["symbol"] == "SGI")
check("SGI quantity is 30", abs(sgi["quantity"] - 30.0) < 1e-9, str(sgi["quantity"]))
status, _ = request("GET", "/api/v1/holdings/ZZZ")
check("GET /holdings/ZZZ returns 404", status == 404)

status, sgi_splits = request("GET", "/api/v1/holdings/SGI/owners")
check("SGI has one 100% split", len(sgi_splits) == 1 and abs(sgi_splits[0]["percentage"] - 100) < 1e-9, str(sgi_splits))
status, ohi_splits = request("GET", "/api/v1/holdings/OHI/owners")
pcts = sorted(s["percentage"] for s in ohi_splits)
check("OHI splits are 56/44", pcts == [44.0, 56.0], str(pcts))
check("OHI split shares match CSV",
      abs(ohi_splits[0]["shares"] - 91.65996) < 1e-6 and abs(ohi_splits[1]["shares"] - 72.01854) < 1e-6,
      str(ohi_splits))

# --- Trades ----------------------------------------------------------------
status, trades = request("GET", "/api/v1/trades")
check("GET /trades returns 200", status == 200 and isinstance(trades, list), str(trades))

# Buy 1 share of SGI for Dad at 61.00
status, trade = request("POST", "/api/v1/trades", {
    "owner_id": 1, "symbol": "SGI", "trade_type": "buy", "quantity": 1,
    "price": 61.00, "trade_date": "2026-11-16", "notes": "test buy",
})
check("POST /trades buy returns 201", status == 201, str(trade))
check("Buy trade echoes owner name", trade and trade.get("owner_name") == "Dad", str(trade))

status, sgi = request("GET", "/api/v1/holdings/SGI")
check("Buy updates quantity to 31", abs(sgi["quantity"] - 31.0) < 1e-9, str(sgi["quantity"]))
check("Buy updates cost basis to 1918.85", abs(sgi["cost_basis"] - 1918.85) < 1e-6, str(sgi["cost_basis"]))
check("Buy updates split shares", abs(sgi["splits"][0]["shares"] - 31.0) < 1e-9, str(sgi["splits"]))

# Sell 0.5 shares at 62.00
status, _ = request("POST", "/api/v1/trades", {
    "owner_id": 1, "symbol": "SGI", "trade_type": "sell", "quantity": 0.5,
    "price": 62.00, "trade_date": "2026-11-17",
})
status, sgi = request("GET", "/api/v1/holdings/SGI")
check("Sell decreases quantity to 30.5", abs(sgi["quantity"] - 30.5) < 1e-9, str(sgi["quantity"]))
check("Sell decreases cost basis to 1887.85", abs(sgi["cost_basis"] - 1887.85) < 1e-6, str(sgi["cost_basis"]))

# Dividend: 1 share at 0.25, quantity unchanged, cost basis +0.25
status, _ = request("POST", "/api/v1/trades", {
    "owner_id": 1, "symbol": "SGI", "trade_type": "dividend", "quantity": 1,
    "price": 0.25, "trade_date": "2026-11-18",
})
status, sgi = request("GET", "/api/v1/holdings/SGI")
check("Dividend leaves quantity unchanged", abs(sgi["quantity"] - 30.5) < 1e-9, str(sgi["quantity"]))
check("Dividend adds to cost basis", abs(sgi["cost_basis"] - 1888.10) < 1e-6, str(sgi["cost_basis"]))

status, trades = request("GET", "/api/v1/trades")
check("GET /trades lists new trades", len(trades) >= 3, f"got {len(trades)}")
status, trade = request("GET", f"/api/v1/trades/{trade['trade_id']}")
check("GET /trades/{id} returns the trade", status == 200 and trade["trade_id"] == trade["trade_id"])
status, owner_trades = request("GET", "/api/v1/owners/1/trades")
check("GET /owners/1/trades filters by owner", len(owner_trades) >= 3, f"got {len(owner_trades)}")
status, symbol_trades = request("GET", "/api/v1/holdings/SGI/trades")
check("GET /holdings/SGI/trades filters by symbol", len(symbol_trades) >= 3, f"got {len(symbol_trades)}")

# Trade validation
status, _ = request("POST", "/api/v1/trades", {
    "owner_id": 1, "symbol": "SGI", "trade_type": "sell", "quantity": 1000,
    "price": 10, "trade_date": "2026-11-19",
})
check("Oversell returns 400", status == 400, str(status))
status, _ = request("POST", "/api/v1/trades", {
    "owner_id": 1, "symbol": "NOPE", "trade_type": "buy", "quantity": 1,
    "price": 10, "trade_date": "2026-11-19",
})
check("Unknown symbol returns 404", status == 404, str(status))
status, _ = request("POST", "/api/v1/trades", {
    "owner_id": 1, "symbol": "SGI", "trade_type": "bogus", "quantity": 1,
    "price": 10, "trade_date": "2026-11-19",
})
check("Invalid trade type returns 422", status == 422, str(status))

# --- Split editing ---------------------------------------------------------
status, splits = request("PUT", "/api/v1/holdings/OHI/owners", [
    {"owner_id": 1, "percentage": 60.0}, {"owner_id": 2, "percentage": 40.0},
])
check("PUT splits with 60/40 returns 200", status == 200, str(splits))
pcts = sorted(s["percentage"] for s in splits)
check("PUT splits stores 60/40", pcts == [40.0, 60.0], str(pcts))
check("PUT splits recalculates shares",
      abs(splits[0]["shares"] - 163.6785 * 0.6) < 1e-6 and abs(splits[1]["shares"] - 163.6785 * 0.4) < 1e-6,
      str(splits))
status, _ = request("PUT", "/api/v1/holdings/OHI/owners", [
    {"owner_id": 1, "percentage": 60.0}, {"owner_id": 2, "percentage": 30.0},
])
check("PUT splits with sum != 100 returns 422", status == 422, str(status))

status, splits = request("POST", "/api/v1/holdings/OHI/owners", {"owner_id": 2, "percentage": 44.0})
check("POST single split returns 200", status == 200, str(splits))
pcts = sorted(s["percentage"] for s in splits)
check("POST split updates Emmett to 44%", pcts == [44.0, 60.0], str(pcts))

# Restore the seeded 56/44 split before the analytics checks
status, splits = request("PUT", "/api/v1/holdings/OHI/owners", [
    {"owner_id": 1, "percentage": 56.0}, {"owner_id": 2, "percentage": 44.0},
])
check("PUT restores OHI to 56/44", status == 200 and sorted(s["percentage"] for s in splits) == [44.0, 56.0], str(splits))

status, _ = request("PUT", "/api/v1/holdings/OHI/owners")
check("PUT recalculate with no body returns 200", status == 200, str(status))

# --- Analytics -------------------------------------------------------------
status, summary = request("GET", "/api/v1/analytics/summary")
check("GET /analytics/summary returns 200", status == 200)
check("Portfolio summary has all fields",
      all(k in summary for k in ("total_positions", "total_cost_basis", "total_current_value",
                                 "unrealized_pl", "pl_percent", "top_holdings")), str(summary))
check("Portfolio summary has 15 positions", summary["total_positions"] == 15, str(summary["total_positions"]))
status, fresh_holdings = request("GET", "/api/v1/holdings")
expected_cost = sum(h["cost_basis"] for h in fresh_holdings)
check("Portfolio cost basis equals sum of positions",
      abs(summary["total_cost_basis"] - expected_cost) < 1.0,
      f'{summary["total_cost_basis"]} vs {expected_cost}')

status, dad_summary = request("GET", "/api/v1/analytics/summary?owner_id=1")
check("Owner summary returns Dad", status == 200 and dad_summary["owner_name"] == "Dad", str(dad_summary))
check("Dad summary has 14 positions", dad_summary["total_positions"] == 14, str(dad_summary["total_positions"]))
status, emmett_summary = request("GET", "/api/v1/analytics/summary?owner_id=2")
check("Emmett summary has 4 positions", emmett_summary["total_positions"] == 4, str(emmett_summary["total_positions"]))
check("Dad + Emmett cost basis equals portfolio cost basis",
      abs(dad_summary["total_cost_basis"] + emmett_summary["total_cost_basis"] - summary["total_cost_basis"]) < 1.0,
      f'{dad_summary["total_cost_basis"]} + {emmett_summary["total_cost_basis"]} vs {summary["total_cost_basis"]}')
status, _ = request("GET", "/api/v1/analytics/summary?owner_id=999")
check("Unknown owner summary returns 404", status == 404, str(status))

# --- Holding CRUD ----------------------------------------------------------
status, created = request("POST", "/api/v1/holdings", {
    "symbol": "TEST", "quantity": 10, "sector": "Test",
    "industry": "Test Industry",
})
check("POST /holdings creates a position", status == 201 and created["symbol"] == "TEST", str(created))
status, updated = request("PUT", "/api/v1/holdings/TEST", {"quantity": 12})
check("PUT /holdings updates quantity", status == 200 and abs(updated["quantity"] - 12) < 1e-9, str(updated))
status, _ = request("DELETE", "/api/v1/holdings/TEST")
check("DELETE /holdings removes the position", status == 200)
status, _ = request("GET", "/api/v1/holdings/TEST")
check("Deleted holding returns 404", status == 404)
status, _ = request("DELETE", "/api/v1/holdings/TEST")
check("Deleting missing holding returns 404", status == 404)

# --- Summary ----------------------------------------------------------------
print()
print(f"Results: {passed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)