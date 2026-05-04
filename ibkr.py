# /// script
# requires-python = ">=3.10"
# dependencies = ["requests"]
# ///
"""
Interactive Brokers Client Portal Gateway integration.

Connects to the locally-running IBKR Client Portal Gateway (default https://localhost:5000)
to fetch account data, positions, and recent trades.

The gateway must be running and authenticated via browser before calling these functions.
See: https://ibkrcampus.com/ibkr-api-page/cpapi-v1/#client-portal-gateway
"""

import json
import os
import urllib3

import requests

# Suppress InsecureRequestWarning — CP Gateway uses self-signed certs
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
CONFIG_PATH = os.path.join(DATA_DIR, "config.json")


def _read_config():
    """Read data/config.json."""
    try:
        with open(CONFIG_PATH, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _get_base_url():
    """Return IBKR gateway base URL from config (default https://localhost:5001)."""
    cfg = _read_config()
    ibkr = cfg.get("ibkr", {})
    return ibkr.get("gateway_url", "https://localhost:5001").rstrip("/")


def _get_account_id():
    """Return configured IBKR account ID (or None to auto-detect)."""
    cfg = _read_config()
    ibkr = cfg.get("ibkr", {})
    return ibkr.get("account_id")


def _session():
    """Create a requests session with SSL verification disabled (self-signed cert)."""
    s = requests.Session()
    s.verify = False
    return s


# ---------------------------------------------------------------------------
# Session / Auth
# ---------------------------------------------------------------------------

def check_auth():
    """Check if the gateway session is authenticated.

    Returns dict with keys:
        connected (bool), authenticated (bool), competing (bool), message (str), error (str|None)
    """
    base = _get_base_url()
    try:
        r = _session().post(f"{base}/v1/api/iserver/auth/status", json={}, timeout=5)
        # 401 means gateway is up but session not authenticated yet
        if r.status_code == 401:
            return {
                "connected": True,
                "authenticated": False,
                "competing": False,
                "message": "Gateway reachable — authentication required",
                "error": None,
            }
        r.raise_for_status()
        data = r.json()
        return {
            "connected": data.get("connected", False) or True,
            "authenticated": data.get("authenticated", False),
            "competing": data.get("competing", False),
            "message": data.get("message", ""),
            "error": None,
        }
    except requests.ConnectionError:
        return {
            "connected": False,
            "authenticated": False,
            "competing": False,
            "message": "",
            "error": "Cannot connect to IBKR Gateway. Is it running?",
        }
    except Exception as e:
        return {
            "connected": False,
            "authenticated": False,
            "competing": False,
            "message": "",
            "error": str(e),
        }


def tickle():
    """Keep the session alive (call every ~1 min to prevent timeout)."""
    base = _get_base_url()
    try:
        r = _session().post(f"{base}/v1/api/tickle", timeout=5)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        return {"error": str(e)}


# ---------------------------------------------------------------------------
# Accounts
# ---------------------------------------------------------------------------

def get_accounts():
    """Get list of portfolio accounts. Must be called before position/summary endpoints.

    Returns list of account dicts with keys: id, accountId, accountTitle, type, etc.
    """
    base = _get_base_url()
    r = _session().get(f"{base}/v1/api/portfolio/accounts", timeout=10)
    r.raise_for_status()
    return r.json()


def _resolve_account_id():
    """Resolve the account ID to use: from config, or auto-detect first account."""
    acct = _get_account_id()
    if acct:
        return acct
    accounts = get_accounts()
    if not accounts:
        raise ValueError("No accounts found. Check IBKR gateway authentication.")
    return accounts[0]["accountId"]


# ---------------------------------------------------------------------------
# Positions
# ---------------------------------------------------------------------------

def get_positions(account_id=None):
    """Fetch all positions for the account (paginated, returns flat list).

    Each position dict includes: contractDesc (ticker), position (shares),
    mktPrice, mktValue, avgCost, avgPrice, unrealizedPnl, assetClass, currency, conid, etc.
    """
    base = _get_base_url()
    if not account_id:
        account_id = _resolve_account_id()

    all_positions = []
    page = 0
    while True:
        r = _session().get(f"{base}/v1/api/portfolio/{account_id}/positions/{page}", timeout=15)
        r.raise_for_status()
        data = r.json()
        if not data:
            break
        all_positions.extend(data)
        if len(data) < 100:
            break
        page += 1

    return all_positions


# ---------------------------------------------------------------------------
# Account Summary / Ledger
# ---------------------------------------------------------------------------

def get_account_summary(account_id=None):
    """Fetch portfolio summary (net liquidation, cash, etc.).

    Returns dict of {key: {amount, currency, value, ...}}.
    """
    base = _get_base_url()
    if not account_id:
        account_id = _resolve_account_id()

    r = _session().get(f"{base}/v1/api/portfolio/{account_id}/summary", timeout=10)
    r.raise_for_status()
    return r.json()


def get_ledger(account_id=None):
    """Fetch account ledger (cash balances by currency).

    Returns dict keyed by currency with balance details.
    """
    base = _get_base_url()
    if not account_id:
        account_id = _resolve_account_id()

    r = _session().get(f"{base}/v1/api/portfolio/{account_id}/ledger", timeout=10)
    r.raise_for_status()
    return r.json()


# ---------------------------------------------------------------------------
# Trades / Executions
# ---------------------------------------------------------------------------

def get_trades(days=7):
    """Fetch recent trade executions (up to 7 days).

    Returns list of trade dicts with keys: symbol, side (B/S), size, price,
    trade_time, commission, net_amount, sec_type, conid, etc.
    """
    base = _get_base_url()
    r = _session().get(f"{base}/v1/api/iserver/account/trades", params={"days": days}, timeout=15)
    r.raise_for_status()
    return r.json()


# ---------------------------------------------------------------------------
# Sync: Convert IBKR data → portfolio.json format
# ---------------------------------------------------------------------------

def sync_positions_to_portfolio(portfolio, bucket_map=None):
    """Fetch IBKR positions and update portfolio holdings in-place.

    Args:
        portfolio: The current portfolio dict (will be mutated).
        bucket_map: Optional dict {ticker: bucket_key} to assign tickers to buckets.
                    Tickers not in this map go to "unassigned" bucket (created if needed).

    Returns:
        dict with keys:
            updated_tickers (list), new_tickers (list), removed_tickers (list),
            total_value (float), cash (float), account_id (str)
    """
    if bucket_map is None:
        bucket_map = {}

    # Build existing ticker→bucket map from portfolio
    existing_map = {}
    for bucket_key, bucket_data in portfolio.get("buckets", {}).items():
        for h in bucket_data.get("holdings", []):
            existing_map[h["ticker"]] = bucket_key

    # Merge: use existing assignment, then user-provided map
    def resolve_bucket(ticker):
        if ticker in existing_map:
            return existing_map[ticker]
        if ticker in bucket_map:
            return bucket_map[ticker]
        return "unassigned"

    # Fetch from IBKR
    # First call get_accounts to initialize backend cache
    get_accounts()
    positions = get_positions()
    account_id = _resolve_account_id()

    # Get cash balance
    cash = 0.0
    try:
        ledger = get_ledger(account_id)
        base_ledger = ledger.get("BASE", ledger.get("USD", {}))
        cash = base_ledger.get("cashbalance", 0.0)
    except Exception:
        pass

    # Filter to stocks/ETFs only (skip options, futures, forex, etc.)
    stock_positions = [
        p for p in positions
        if p.get("assetClass") in ("STK",) and p.get("position", 0) != 0
    ]

    # Build IBKR position data keyed by ticker
    ibkr_by_ticker = {}
    for pos in stock_positions:
        ticker = pos.get("contractDesc", pos.get("ticker", ""))
        if not ticker:
            continue
        ibkr_by_ticker[ticker] = {
            "shares": pos["position"],
            "avg_price": round(pos.get("avgPrice", pos.get("avgCost", 0)), 4),
        }

    # Track which IBKR tickers have been matched to existing holdings
    matched_tickers = set()
    updated_tickers = []
    new_tickers = []
    removed_tickers = []

    # Pass 1: Update existing holdings in-place (preserves target_amount etc.)
    for bucket_key, bucket_data in portfolio.get("buckets", {}).items():
        for h in bucket_data.get("holdings", []):
            ticker = h["ticker"]
            if ticker in ibkr_by_ticker:
                ibkr = ibkr_by_ticker[ticker]
                h["actual_shares"] = ibkr["shares"]
                h["avg_price"] = ibkr["avg_price"]
                matched_tickers.add(ticker)
                updated_tickers.append(ticker)
            else:
                # Ticker not in IBKR — zero out shares but keep in portfolio
                # (user may still want it as a watchlist / target placeholder)
                if h.get("actual_shares", 0) != 0:
                    h["actual_shares"] = 0
                    h["avg_price"] = 0
                    removed_tickers.append(ticker)

    # Pass 2: Add new IBKR tickers not already in any bucket
    for ticker, ibkr in ibkr_by_ticker.items():
        if ticker in matched_tickers:
            continue
        bucket = resolve_bucket(ticker)
        if bucket not in portfolio.get("buckets", {}):
            portfolio.setdefault("buckets", {})[bucket] = {
                "target_weight": 0,
                "target_amount": 0,
                "holdings": [],
            }
        portfolio["buckets"][bucket]["holdings"].append({
            "ticker": ticker,
            "actual_shares": ibkr["shares"],
            "avg_price": ibkr["avg_price"],
            "target_amount": 0,
        })
        new_tickers.append(ticker)

    # Get cash and compute total value
    total_value = sum(p.get("mktValue", 0) for p in stock_positions) + cash

    return {
        "updated_tickers": updated_tickers,
        "new_tickers": new_tickers,
        "removed_tickers": removed_tickers,
        "total_value": round(total_value, 2),
        "cash": round(cash, 2),
        "account_id": account_id,
        "positions_count": len(stock_positions),
    }


def sync_trades_to_portfolio(portfolio, days=7):
    """Fetch recent IBKR trades and append to portfolio trade log.

    Only adds trades not already present (deduped by execution_id stored in notes).
    Only includes stock trades (STK).

    Returns:
        dict with keys: added (int), skipped (int), trades (list of new trade dicts)
    """
    raw_trades = get_trades(days=days)

    # Filter to stocks only
    stock_trades = [t for t in raw_trades if t.get("sec_type") == "STK"]

    existing_exec_ids = set()
    for t in portfolio.get("trades", []):
        notes = t.get("notes", "")
        if notes.startswith("ibkr:"):
            existing_exec_ids.add(notes.split("ibkr:")[1])

    added = 0
    skipped = 0
    new_trades = []

    for t in stock_trades:
        exec_id = t.get("execution_id", "")
        if exec_id in existing_exec_ids:
            skipped += 1
            continue

        # Determine action
        side = t.get("side", "")
        action = "BUY" if side == "B" else "SELL"

        # Parse trade time
        trade_time = t.get("trade_time", "")
        # Format: "20231211-18:00:49" → "2023-12-11"
        date_str = ""
        if trade_time and len(trade_time) >= 8:
            date_str = f"{trade_time[0:4]}-{trade_time[4:6]}-{trade_time[6:8]}"

        price = float(t.get("price", 0))
        shares = abs(float(t.get("size", 0)))

        trade_entry = {
            "ticker": t.get("symbol", ""),
            "action": action,
            "shares": shares,
            "price": round(price, 4),
            "date": date_str,
            "notes": f"ibkr:{exec_id}",
        }

        portfolio.setdefault("trades", []).append(trade_entry)
        new_trades.append(trade_entry)
        added += 1

    return {"added": added, "skipped": skipped, "trades": new_trades}
