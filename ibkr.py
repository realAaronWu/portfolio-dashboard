# /// script
# requires-python = ">=3.10"
# dependencies = ["ib_insync"]
# ///
"""
Interactive Brokers TWS API integration via ib_insync.

Connects to IB Gateway or TWS running locally (default 127.0.0.1:4001)
to fetch account data, positions, and recent trades.

IB Gateway must be running and authenticated before calling these functions.
"""

import json
import os
import datetime

from ib_insync import IB, util

# Patch asyncio so ib_insync works in sync/threaded contexts (Flask)
util.patchAsyncio()

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
CONFIG_PATH = os.path.join(DATA_DIR, "config.json")

# Module-level persistent connection
_ib: IB | None = None


def _read_config():
    """Read data/config.json."""
    try:
        with open(CONFIG_PATH, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _get_host():
    """Return IBKR gateway host from config (default 127.0.0.1)."""
    cfg = _read_config()
    return cfg.get("ibkr", {}).get("host", "127.0.0.1")


def _get_port():
    """Return IBKR gateway port from config (default 4001)."""
    cfg = _read_config()
    return int(cfg.get("ibkr", {}).get("port", 4001))


def _get_client_id():
    """Return client ID from config (default 1)."""
    cfg = _read_config()
    return int(cfg.get("ibkr", {}).get("client_id", 1))


def _get_account_id():
    """Return configured IBKR account ID (or empty string for auto-detect)."""
    cfg = _read_config()
    return cfg.get("ibkr", {}).get("account_id", "")


# ---------------------------------------------------------------------------
# Connection Management
# ---------------------------------------------------------------------------

def connect():
    """Connect to IB Gateway / TWS. Returns the IB instance.

    Reuses existing connection if still alive.
    """
    global _ib
    if _ib and _ib.isConnected():
        return _ib

    _ib = IB()
    host = _get_host()
    port = _get_port()
    client_id = _get_client_id()
    account = _get_account_id()

    _ib.connect(host, port, clientId=client_id, readonly=True, account=account or "")
    return _ib


def disconnect():
    """Disconnect from IB Gateway / TWS."""
    global _ib
    if _ib and _ib.isConnected():
        _ib.disconnect()
    _ib = None


def check_auth():
    """Check if we can connect to IB Gateway / TWS.

    Returns dict with keys:
        connected (bool), authenticated (bool), message (str), error (str|None)
    """
    try:
        ib = connect()
        accounts = ib.managedAccounts()
        return {
            "connected": True,
            "authenticated": True,
            "competing": False,
            "message": f"Connected — accounts: {', '.join(accounts)}",
            "error": None,
        }
    except ConnectionRefusedError:
        return {
            "connected": False,
            "authenticated": False,
            "competing": False,
            "message": "",
            "error": "Cannot connect to IB Gateway. Is it running on port {}?".format(_get_port()),
        }
    except Exception as e:
        msg = str(e)
        # If already connected from another client
        if "clientId" in msg.lower() or "already connected" in msg.lower():
            return {
                "connected": True,
                "authenticated": False,
                "competing": True,
                "message": msg,
                "error": None,
            }
        return {
            "connected": False,
            "authenticated": False,
            "competing": False,
            "message": "",
            "error": msg,
        }


# ---------------------------------------------------------------------------
# Accounts
# ---------------------------------------------------------------------------

def get_accounts():
    """Get list of managed account IDs.

    Returns list of account ID strings.
    """
    ib = connect()
    return ib.managedAccounts()


def _resolve_account_id():
    """Resolve the account ID to use: from config, or auto-detect first account."""
    acct = _get_account_id()
    if acct:
        return acct
    accounts = get_accounts()
    if not accounts:
        raise ValueError("No accounts found. Check IB Gateway authentication.")
    return accounts[0]


# ---------------------------------------------------------------------------
# Positions
# ---------------------------------------------------------------------------

def get_positions():
    """Fetch all positions.

    Returns list of dicts with keys: ticker, shares, avg_price, mkt_value, asset_class, conid
    """
    ib = connect()
    positions = ib.positions()

    result = []
    for pos in positions:
        contract = pos.contract
        result.append({
            "ticker": contract.symbol,
            "shares": float(pos.position),
            "avg_price": round(float(pos.avgCost) / (float(contract.multiplier) if contract.multiplier else 1), 4),
            "asset_class": contract.secType,  # STK, OPT, FUT, etc.
            "conid": contract.conId,
            "currency": contract.currency,
            "account": pos.account,
        })
    return result


# ---------------------------------------------------------------------------
# Account Summary
# ---------------------------------------------------------------------------

def get_account_summary(account_id=None):
    """Fetch account summary (net liquidation, cash, etc.).

    Uses accountValues() which returns cached data from the TWS subscription
    (non-blocking), rather than accountSummary() which can hang.

    Returns dict of {tag: {value, currency}}.
    """
    ib = connect()
    if not account_id:
        account_id = _resolve_account_id()

    # accountValues() returns the already-subscribed account data
    values = ib.accountValues(account=account_id)

    tags_of_interest = {
        "NetLiquidation", "TotalCashValue", "GrossPositionValue",
        "AvailableFunds", "BuyingPower",
    }
    result = {}
    for item in values:
        if item.tag in tags_of_interest and item.currency in ("USD", "BASE"):
            result[item.tag] = {
                "value": float(item.value) if item.value else 0,
                "currency": item.currency,
            }
    return result


# ---------------------------------------------------------------------------
# Trades / Executions
# ---------------------------------------------------------------------------

def get_trades():
    """Fetch today's trade executions.

    Returns list of trade dicts with keys: symbol, side, size, price,
    trade_time, commission, exec_id, sec_type
    """
    ib = connect()
    fills = ib.fills()

    result = []
    for fill in fills:
        execution = fill.execution
        contract = fill.contract
        commission = fill.commissionReport

        result.append({
            "symbol": contract.symbol,
            "sec_type": contract.secType,
            "side": execution.side,  # "BOT" or "SLD"
            "size": abs(float(execution.shares)),
            "price": round(float(execution.price), 4),
            "trade_time": execution.time.strftime("%Y-%m-%d") if isinstance(execution.time, datetime.datetime) else str(execution.time)[:10],
            "execution_id": execution.execId,
            "commission": round(float(commission.commission), 4) if commission and commission.commission != 1.7976931348623157e+308 else 0,
        })
    return result


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
    positions = get_positions()
    account_id = _resolve_account_id()

    # Get cash balance
    cash = 0.0
    try:
        summary = get_account_summary(account_id)
        cash = summary.get("TotalCashValue", {}).get("value", 0.0)
    except Exception:
        pass

    # Filter to stocks/ETFs only (skip options, futures, forex, etc.)
    stock_positions = [p for p in positions if p["asset_class"] == "STK" and p["shares"] != 0]

    # Build IBKR position data keyed by ticker
    ibkr_by_ticker = {}
    for pos in stock_positions:
        ticker = pos["ticker"]
        if not ticker:
            continue
        ibkr_by_ticker[ticker] = {
            "shares": pos["shares"],
            "avg_price": pos["avg_price"],
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

    # Compute total value from positions
    total_value = cash
    for pos in stock_positions:
        # shares * avg_price as approximation (mktValue not available from positions())
        total_value += abs(pos["shares"]) * pos["avg_price"]

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
    """Fetch IBKR trades and append to portfolio trade log.

    Only adds trades not already present (deduped by execution_id stored in notes).
    Only includes stock trades (STK).

    Returns:
        dict with keys: added (int), skipped (int), trades (list of new trade dicts)
    """
    raw_trades = get_trades()

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

        side = t.get("side", "")
        action = "BUY" if side == "BOT" else "SELL"

        trade_entry = {
            "ticker": t.get("symbol", ""),
            "action": action,
            "shares": t["size"],
            "price": t["price"],
            "date": t.get("trade_time", ""),
            "notes": f"ibkr:{exec_id}",
        }

        portfolio.setdefault("trades", []).append(trade_entry)
        new_trades.append(trade_entry)
        added += 1

    return {"added": added, "skipped": skipped, "trades": new_trades}
