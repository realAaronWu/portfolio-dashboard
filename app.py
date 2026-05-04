# /// script
# requires-python = ">=3.10"
# dependencies = ["flask", "requests"]
# ///

import datetime
import glob
import json
import os
import random
import shutil
import string
import subprocess
import tempfile
import threading

from flask import Flask, jsonify, render_template, request

import ibkr
import market

app = Flask(__name__)

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
PORTFOLIO_PATH = os.path.join(DATA_DIR, "portfolio.json")
STRATEGY_PATH = os.path.join(DATA_DIR, "strategy.json")
STRATEGY_DEFAULTS_PATH = os.path.join(DATA_DIR, "strategy_defaults.json")
BACKUP_DIR = os.path.join(DATA_DIR, "backups")
MAX_BACKUPS = 50
_file_lock = threading.Lock()
_strategy_lock = threading.Lock()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _read_portfolio():
    """Read portfolio.json under the file lock."""
    with _file_lock:
        with open(PORTFOLIO_PATH, "r") as f:
            return json.load(f)


def _write_portfolio(data, commit_msg=None):
    """Write portfolio.json with atomic write, rolling backup, and git commit.

    1. Backup current file to data/backups/ (keep last MAX_BACKUPS)
    2. Atomic write: write to temp file, then os.replace() into place
    3. Git auto-commit with descriptive message
    """
    with _file_lock:
        # --- Rolling backup ---
        os.makedirs(BACKUP_DIR, exist_ok=True)
        if os.path.exists(PORTFOLIO_PATH):
            ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            backup_path = os.path.join(BACKUP_DIR, f"portfolio_{ts}.json")
            shutil.copy2(PORTFOLIO_PATH, backup_path)
            # Prune old backups beyond MAX_BACKUPS
            backups = sorted(glob.glob(os.path.join(BACKUP_DIR, "portfolio_*.json")))
            for old in backups[:-MAX_BACKUPS]:
                try:
                    os.remove(old)
                except OSError:
                    pass

        # --- Atomic write: temp file + rename ---
        fd, tmp_path = tempfile.mkstemp(
            suffix=".json", prefix="portfolio_", dir=DATA_DIR
        )
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(data, f, indent=2)
            os.replace(tmp_path, PORTFOLIO_PATH)
        except BaseException:
            # Clean up temp file on failure
            try:
                os.remove(tmp_path)
            except OSError:
                pass
            raise

        # --- Git auto-commit (fire and forget, non-blocking) ---
        if commit_msg:
            _git_commit_data(commit_msg, PORTFOLIO_PATH)


def _git_commit_data(message, *paths):
    """Stage and commit files inside the data/ repo, optionally auto-push.

    The data/ directory is expected to be its own git repository
    (e.g. cloned from a private remote).  If it isn't a git repo
    this silently does nothing.

    Auto-push is controlled by data/config.json:
        { "auto_push": true }
    """
    if not os.path.isdir(os.path.join(DATA_DIR, ".git")):
        return  # data/ is not a git repo — skip
    try:
        for p in paths:
            subprocess.run(
                ["git", "add", os.path.basename(p)],
                cwd=DATA_DIR, capture_output=True, timeout=5,
            )
        subprocess.run(
            ["git", "commit", "-m", message],
            cwd=DATA_DIR, capture_output=True, timeout=5,
        )
        # Auto-push if configured
        if _should_auto_push():
            subprocess.run(
                ["git", "push"],
                cwd=DATA_DIR, capture_output=True, timeout=15,
            )
    except Exception:
        pass  # git not available or push failed — that's fine


def _should_auto_push():
    """Check data/config.json for auto_push setting."""
    config_path = os.path.join(DATA_DIR, "config.json")
    try:
        with open(config_path, "r") as f:
            return json.load(f).get("auto_push", False)
    except (FileNotFoundError, json.JSONDecodeError):
        return False


def _collect_tickers(portfolio):
    """Collect all unique tickers from buckets and option underlyings."""
    tickers = set()
    for bucket in portfolio.get("buckets", {}).values():
        for holding in bucket.get("holdings", []):
            tickers.add(holding["ticker"])
    for option in portfolio.get("options", []):
        underlying = option.get("underlying")
        if underlying:
            tickers.add(underlying)
    return sorted(tickers)


def _read_strategy():
    """Read strategy.json (the active, user-tunable strategy).

    If strategy.json doesn't exist yet, bootstrap it from
    strategy_defaults.json so the app always has a working config
    without any hardcoded values in Python.
    """
    with _strategy_lock:
        if not os.path.exists(STRATEGY_PATH):
            # First run — seed from defaults file
            shutil.copy2(STRATEGY_DEFAULTS_PATH, STRATEGY_PATH)
        with open(STRATEGY_PATH, "r") as f:
            return json.load(f)


def _write_strategy(data, commit_msg=None):
    """Write strategy.json atomically with backup + git commit."""
    with _strategy_lock:
        os.makedirs(BACKUP_DIR, exist_ok=True)
        if os.path.exists(STRATEGY_PATH):
            ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            backup_path = os.path.join(BACKUP_DIR, f"strategy_{ts}.json")
            shutil.copy2(STRATEGY_PATH, backup_path)
            backups = sorted(glob.glob(os.path.join(BACKUP_DIR, "strategy_*.json")))
            for old in backups[:-MAX_BACKUPS]:
                try:
                    os.remove(old)
                except OSError:
                    pass

        fd, tmp_path = tempfile.mkstemp(
            suffix=".json", prefix="strategy_", dir=DATA_DIR
        )
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(data, f, indent=2)
            os.replace(tmp_path, STRATEGY_PATH)
        except BaseException:
            try:
                os.remove(tmp_path)
            except OSError:
                pass
            raise

        if commit_msg:
            _git_commit_data(commit_msg, STRATEGY_PATH)


def _read_strategy_defaults():
    """Read strategy_defaults.json (the immutable template for Reset)."""
    with open(STRATEGY_DEFAULTS_PATH, "r") as f:
        return json.load(f)


def _parse_thresholds(strategy):
    """Convert strategy JSON into the tuple format market.compute_signal expects.

    Always returns a valid thresholds map — no hardcoded fallback.
    """
    str_th = strategy.get("str_thresholds", {})
    btd_th = strategy.get("btd_thresholds", {})

    result = {}
    for bk in str_th.keys() | btd_th.keys():
        s_list = str_th.get(bk, [])
        b_list = btd_th.get(bk, [])
        str_tuples = [(t["div"], t["trim"] / 100, f"Tier {i+1}: Trim {t['trim']}%") for i, t in enumerate(s_list)]
        btd_tuples = [(t["dip"], f"Tier {i+1}: {'Buy' if i==0 else 'Buy More' if i==1 else 'Buy Aggressively'}") for i, t in enumerate(b_list)]
        result[bk] = {"str": str_tuples, "btd": btd_tuples}
    return result


# ---------------------------------------------------------------------------
# Page routes
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return render_template("dashboard.html")


@app.route("/portfolio")
def portfolio_page():
    portfolio = _read_portfolio()
    return render_template("portfolio.html", portfolio_json=json.dumps(portfolio))


@app.route("/history")
def history_page():
    ticker = request.args.get("ticker", "")
    portfolio = _read_portfolio()
    # Collect all tickers for the dropdown
    tickers = _collect_tickers(portfolio)
    return render_template("history.html", default_ticker=ticker, tickers=tickers)


@app.route("/strategy")
def strategy_page():
    return render_template("strategy.html")


@app.route("/summary")
def summary_page():
    return render_template("summary.html")


# ---------------------------------------------------------------------------
# API – Market data
# ---------------------------------------------------------------------------

@app.route("/api/market-data")
def api_market_data():
    portfolio = _read_portfolio()
    strategy = _read_strategy()
    thresholds_map = _parse_thresholds(strategy)
    tickers = _collect_tickers(portfolio)
    raw = market.fetch_all_tickers(tickers)

    # Build a ticker → bucket_type lookup so we can compute the right signal.
    ticker_bucket = {}
    for bucket_key, bucket in portfolio.get("buckets", {}).items():
        for holding in bucket.get("holdings", []):
            ticker_bucket[holding["ticker"]] = bucket_key

    # STR cooldown: find tickers with a SELL in the last 5 trading days (~7 calendar days)
    str_cooldown_tickers = _get_str_cooldown_tickers(portfolio)

    data = {}
    for ticker, info in raw.items():
        if "error" in info:
            data[ticker] = info
            continue

        bucket_type = ticker_bucket.get(ticker, "tech_stocks")
        signal = market.compute_signal(info.get("div_sma", 0), bucket_type, thresholds_map)

        # Suppress STR signal if ticker was trimmed recently
        if signal["action"] == "STR" and ticker in str_cooldown_tickers:
            days_ago = str_cooldown_tickers[ticker]
            signal = {
                "action": "HOLD",
                "label": f"Trimmed {days_ago}d ago — cooldown",
                "trim_pct": 0,
                "severity": "none",
            }

        data[ticker] = {
            "price": info.get("price"),
            "sma20": info.get("sma20"),
            "ema20": info.get("ema20"),
            "sma50": info.get("sma50"),
            "div_sma": info.get("div_sma"),
            "div_ema": info.get("div_ema"),
            "chg_1m": info.get("chg_1m"),
            "chg_month_open": info.get("chg_month_open"),
            "signal": signal,
        }

    return jsonify({"data": data})


def _get_str_cooldown_tickers(portfolio):
    """Return {ticker: days_ago} for tickers with a SELL in the last 5 trading days.

    Uses 7 calendar days as a conservative approximation of 5 trading days.
    Cooldown period is configurable via strategy.json "str_cooldown_days".
    """
    strategy = _read_strategy()
    cooldown_days = strategy.get("str_cooldown_days", 7)
    cutoff = datetime.datetime.now() - datetime.timedelta(days=cooldown_days)
    cooldown = {}
    for trade in portfolio.get("trades", []):
        if trade.get("action") != "SELL":
            continue
        trade_date_str = trade.get("date", "")
        if not trade_date_str:
            continue
        try:
            trade_date = datetime.datetime.strptime(trade_date_str, "%Y-%m-%d")
        except ValueError:
            continue
        if trade_date >= cutoff:
            ticker = trade.get("ticker", "")
            days_ago = (datetime.datetime.now() - trade_date).days
            # Keep the most recent sell per ticker
            if ticker not in cooldown or days_ago < cooldown[ticker]:
                cooldown[ticker] = days_ago
    return cooldown


# ---------------------------------------------------------------------------
# API – History (OHLC + trades for a ticker)
# ---------------------------------------------------------------------------

@app.route("/api/history/<ticker>")
def api_history(ticker):
    ticker = ticker.upper()
    range_str = request.args.get("range", "1y")
    candles = market.fetch_ohlc_history(ticker, range_str)
    if isinstance(candles, dict) and "error" in candles:
        return jsonify(candles), 500

    # Gather trades and holding info for this ticker
    portfolio = _read_portfolio()
    trades = [t for t in portfolio.get("trades", []) if t.get("ticker") == ticker]
    # Sort trades oldest-first for accumulated P&L calculation
    trades_sorted = sorted(trades, key=lambda t: t.get("date", ""))

    # Find the holding to get avg_price and shares
    holding_info = {}
    for bk, bd in portfolio.get("buckets", {}).items():
        for h in bd.get("holdings", []):
            if h["ticker"] == ticker:
                holding_info = {
                    "bucket": bk,
                    "shares": h.get("actual_shares", 0),
                    "avg_price": h.get("avg_price", 0),
                    "target_amount": h.get("target_amount", 0),
                }
                break

    # If no trades recorded but holding exists, synthesize an initial-position entry
    # so the chart shows the buy point
    if not trades_sorted and holding_info.get("shares", 0) > 0 and holding_info.get("avg_price", 0) > 0:
        today = datetime.datetime.now().strftime("%Y-%m-%d")
        trades_sorted = [{
            "id": "_initial",
            "date": today,
            "bucket": holding_info.get("bucket", ""),
            "ticker": ticker,
            "action": "BUY",
            "shares": holding_info["shares"],
            "price": holding_info["avg_price"],
            "fees": 0,
            "notes": "Initial position (from portfolio entry)",
            "resulting_shares": holding_info["shares"],
            "resulting_avg": holding_info["avg_price"],
        }]

    # Compute per-trade realized P&L for sells
    accumulated_pnl = 0
    trade_pnl_list = []
    for t in trades_sorted:
        entry = {**t, "realized_pnl": None, "accumulated_pnl": None}
        if t["action"] == "SELL":
            # Use the resulting_avg at time of sale as cost basis
            sell_avg = t.get("resulting_avg", 0)
            realized = (t["price"] - sell_avg) * t["shares"] - (t.get("fees", 0) or 0)
            accumulated_pnl += realized
            entry["realized_pnl"] = round(realized, 2)
            entry["accumulated_pnl"] = round(accumulated_pnl, 2)
        trade_pnl_list.append(entry)

    # Include last closing price for display
    last_close = candles[-1]["close"] if candles else None

    return jsonify({
        "ticker": ticker,
        "candles": candles,
        "trades": trade_pnl_list,
        "holding": holding_info,
        "accumulated_pnl": round(accumulated_pnl, 2),
        "last_close": last_close,
    })


# ---------------------------------------------------------------------------
# API – Portfolio CRUD
# ---------------------------------------------------------------------------

@app.route("/api/portfolio")
def api_portfolio():
    return jsonify(_read_portfolio())


@app.route("/api/portfolio/holding", methods=["PUT"])
def api_update_holding():
    body = request.get_json(force=True)
    bucket_key = body.get("bucket")
    ticker = body.get("ticker")

    portfolio = _read_portfolio()
    bucket = portfolio.get("buckets", {}).get(bucket_key)
    if not bucket:
        return jsonify({"error": f"Bucket '{bucket_key}' not found"}), 404

    for holding in bucket.get("holdings", []):
        if holding["ticker"] == ticker:
            if "actual_shares" in body:
                holding["actual_shares"] = body["actual_shares"]
            if "avg_price" in body:
                holding["avg_price"] = body["avg_price"]
            if "target_amount" in body:
                holding["target_amount"] = body["target_amount"]
            _write_portfolio(portfolio, f"Update {ticker} in {bucket_key}")
            return jsonify(portfolio)

    return jsonify({"error": f"Ticker '{ticker}' not found in bucket '{bucket_key}'"}), 404


@app.route("/api/portfolio/holding", methods=["POST"])
def api_add_holding():
    body = request.get_json(force=True)
    bucket_key = body.get("bucket")

    portfolio = _read_portfolio()
    bucket = portfolio.get("buckets", {}).get(bucket_key)
    if not bucket:
        return jsonify({"error": f"Bucket '{bucket_key}' not found"}), 404

    new_holding = {
        "ticker": body.get("ticker"),
        "target_amount": body.get("target_amount", 0),
        "actual_shares": body.get("actual_shares", 0),
        "avg_price": body.get("avg_price", 0),
    }
    bucket.setdefault("holdings", []).append(new_holding)
    _write_portfolio(portfolio, f"Add {new_holding['ticker']} to {bucket_key}")
    return jsonify(portfolio)


@app.route("/api/portfolio/holding", methods=["DELETE"])
def api_delete_holding():
    body = request.get_json(force=True)
    bucket_key = body.get("bucket")
    ticker = body.get("ticker")

    portfolio = _read_portfolio()
    bucket = portfolio.get("buckets", {}).get(bucket_key)
    if not bucket:
        return jsonify({"error": f"Bucket '{bucket_key}' not found"}), 404

    original_len = len(bucket.get("holdings", []))
    bucket["holdings"] = [
        h for h in bucket.get("holdings", []) if h["ticker"] != ticker
    ]
    if len(bucket["holdings"]) == original_len:
        return jsonify({"error": f"Ticker '{ticker}' not found in bucket '{bucket_key}'"}), 404

    _write_portfolio(portfolio, f"Delete {ticker} from {bucket_key}")
    return jsonify(portfolio)


@app.route("/api/portfolio/promote", methods=["POST"])
def api_promote_holding():
    """Move a holding from satellite → tech_stocks with target_amount=0."""
    body = request.get_json(force=True)
    ticker = body.get("ticker")
    if not ticker:
        return jsonify({"error": "ticker is required"}), 400

    portfolio = _read_portfolio()
    sat = portfolio.get("buckets", {}).get("satellite")
    tech = portfolio.get("buckets", {}).get("tech_stocks")
    if not sat or not tech:
        return jsonify({"error": "satellite or tech_stocks bucket not found"}), 404

    # Find and remove from satellite
    holding = None
    for h in sat.get("holdings", []):
        if h["ticker"] == ticker:
            holding = h
            break
    if not holding:
        return jsonify({"error": f"{ticker} not found in satellite"}), 404

    sat["holdings"] = [h for h in sat["holdings"] if h["ticker"] != ticker]

    # Check for duplicates in tech_stocks
    if any(h["ticker"] == ticker for h in tech.get("holdings", [])):
        return jsonify({"error": f"{ticker} already exists in tech_stocks"}), 409

    # Add to tech_stocks with target_amount=0
    holding["target_amount"] = 0
    tech["holdings"].append(holding)

    _write_portfolio(portfolio, f"Promote {ticker} from satellite to tech_stocks")
    return jsonify({"status": "ok", "ticker": ticker})


# ---------------------------------------------------------------------------
# API – Options CRUD
# ---------------------------------------------------------------------------

@app.route("/api/portfolio/option", methods=["PUT"])
def api_update_option():
    body = request.get_json(force=True)
    option_id = body.get("id")

    portfolio = _read_portfolio()
    for i, opt in enumerate(portfolio.get("options", [])):
        if opt.get("id") == option_id:
            portfolio["options"][i] = {**opt, **body}
            _write_portfolio(portfolio, f"Update option {option_id}")
            return jsonify(portfolio)

    return jsonify({"error": f"Option '{option_id}' not found"}), 404


@app.route("/api/portfolio/option", methods=["POST"])
def api_add_option():
    body = request.get_json(force=True)

    # Generate an id from underlying + type + random suffix
    underlying = body.get("underlying", "unk").lower()
    opt_type = body.get("type", "put").lower()
    suffix = "".join(random.choices(string.ascii_lowercase + string.digits, k=4))
    body.setdefault("id", f"{underlying}-{opt_type}-{suffix}")

    portfolio = _read_portfolio()
    portfolio.setdefault("options", []).append(body)
    _write_portfolio(portfolio, f"Add option {body.get('id','')}")
    return jsonify(portfolio)


@app.route("/api/portfolio/option", methods=["DELETE"])
def api_delete_option():
    body = request.get_json(force=True)
    option_id = body.get("id")

    portfolio = _read_portfolio()
    original_len = len(portfolio.get("options", []))
    portfolio["options"] = [
        o for o in portfolio.get("options", []) if o.get("id") != option_id
    ]
    if len(portfolio["options"]) == original_len:
        return jsonify({"error": f"Option '{option_id}' not found"}), 404

    _write_portfolio(portfolio, f"Delete option {option_id}")
    return jsonify(portfolio)


# ---------------------------------------------------------------------------
# API – Trade recording
# ---------------------------------------------------------------------------

@app.route("/api/portfolio/trade", methods=["POST"])
def api_record_trade():
    """Record a BUY or SELL trade and auto-update shares + avg price.

    Body: {bucket, ticker, action: "BUY"|"SELL", shares, price, date?, fees?, notes?}

    BUY:  new_shares = old + bought
          new_avg    = (old_shares*old_avg + bought_shares*buy_price) / new_shares
    SELL: new_shares = old - sold   (avg stays the same)
    """
    body = request.get_json(force=True)
    bucket_key = body.get("bucket")
    ticker     = (body.get("ticker") or "").upper()
    action     = (body.get("action") or "").upper()
    shares     = float(body.get("shares", 0))
    price      = float(body.get("price", 0))
    fees       = float(body.get("fees", 0))
    date_str   = body.get("date", "")
    notes      = body.get("notes", "")

    if action not in ("BUY", "SELL"):
        return jsonify({"error": "action must be BUY or SELL"}), 400
    if shares <= 0:
        return jsonify({"error": "shares must be > 0"}), 400
    if price <= 0:
        return jsonify({"error": "price must be > 0"}), 400

    portfolio = _read_portfolio()
    bucket = portfolio.get("buckets", {}).get(bucket_key)
    if not bucket:
        return jsonify({"error": f"Bucket '{bucket_key}' not found"}), 404

    holding = None
    for h in bucket.get("holdings", []):
        if h["ticker"] == ticker:
            holding = h
            break
    if not holding:
        return jsonify({"error": f"Ticker '{ticker}' not found in bucket '{bucket_key}'"}), 404

    old_shares = float(holding.get("actual_shares", 0))
    old_avg    = float(holding.get("avg_price", 0))

    if action == "BUY":
        new_shares = old_shares + shares
        # Weighted average cost (including fees spread over bought shares)
        effective_price = price + (fees / shares if shares else 0)
        new_avg = ((old_shares * old_avg) + (shares * effective_price)) / new_shares if new_shares else 0
        holding["actual_shares"] = round(new_shares, 6)
        holding["avg_price"]     = round(new_avg, 4)
    else:
        # SELL
        if shares > old_shares:
            return jsonify({"error": f"Cannot sell {shares} shares, only {old_shares} held"}), 400
        new_shares = old_shares - shares
        holding["actual_shares"] = round(new_shares, 6)
        # avg_price stays the same on sells

    # Append to trade log
    trade_id = "".join(random.choices(string.ascii_lowercase + string.digits, k=8))
    trade_entry = {
        "id": trade_id,
        "date": date_str or "",
        "bucket": bucket_key,
        "ticker": ticker,
        "action": action,
        "shares": shares,
        "price": price,
        "fees": fees,
        "notes": notes,
        "resulting_shares": holding["actual_shares"],
        "resulting_avg": holding["avg_price"],
    }
    portfolio.setdefault("trades", []).insert(0, trade_entry)  # newest first

    _write_portfolio(portfolio, f"Trade: {action} {shares} {ticker} @ ${price:.2f}")
    return jsonify({"trade": trade_entry, "portfolio": portfolio})


@app.route("/api/portfolio/trade", methods=["DELETE"])
def api_delete_trade():
    """Delete a trade from the log (does NOT reverse the shares/avg changes)."""
    body = request.get_json(force=True)
    trade_id = body.get("id")

    portfolio = _read_portfolio()
    original_len = len(portfolio.get("trades", []))
    portfolio["trades"] = [t for t in portfolio.get("trades", []) if t.get("id") != trade_id]
    if len(portfolio["trades"]) == original_len:
        return jsonify({"error": f"Trade '{trade_id}' not found"}), 404

    _write_portfolio(portfolio, f"Delete trade log entry {trade_id}")
    return jsonify(portfolio)


# ---------------------------------------------------------------------------
# API – Strategy
# ---------------------------------------------------------------------------

@app.route("/api/strategy")
def api_get_strategy():
    strategy = _read_strategy()
    portfolio = _read_portfolio()
    return jsonify({
        "strategy": strategy,
        "total_capital": portfolio.get("total_capital", 0),
    })


@app.route("/api/strategy", methods=["PUT"])
def api_update_strategy():
    body = request.get_json(force=True)
    strategy = _read_strategy()

    # Update whichever sections were provided
    for key in ("bucket_weights", "str_thresholds", "btd_thresholds", "hedge_strategy"):
        if key in body:
            strategy[key] = body[key]

    _write_strategy(strategy, "Update strategy")

    # If bucket weights changed, recalculate target_amount for each bucket
    if "bucket_weights" in body:
        portfolio = _read_portfolio()
        total_capital = portfolio.get("total_capital", 0)
        for bk, bd in portfolio.get("buckets", {}).items():
            weight = strategy.get("bucket_weights", {}).get(bk, 0)
            bd["target_weight"] = weight
            if weight > 0:
                bd["target_amount"] = round(total_capital * weight / 100, 2)
        _write_portfolio(portfolio, "Sync bucket weights from strategy")

    portfolio = _read_portfolio()
    return jsonify({
        "strategy": strategy,
        "total_capital": portfolio.get("total_capital", 0),
        "buckets": {bk: {"target_weight": bd.get("target_weight", 0), "target_amount": bd.get("target_amount", 0)}
                    for bk, bd in portfolio.get("buckets", {}).items()},
    })


@app.route("/api/strategy/reset", methods=["POST"])
def api_reset_strategy():
    """Reset strategy to defaults by copying strategy_defaults.json."""
    defaults = _read_strategy_defaults()
    _write_strategy(defaults, "Reset strategy to defaults")

    # Also sync bucket weights back to portfolio
    portfolio = _read_portfolio()
    total_capital = portfolio.get("total_capital", 0)
    for bk, bd in portfolio.get("buckets", {}).items():
        weight = defaults.get("bucket_weights", {}).get(bk, 0)
        bd["target_weight"] = weight
        if weight > 0:
            bd["target_amount"] = round(total_capital * weight / 100, 2)
    _write_portfolio(portfolio, "Sync bucket weights after strategy reset")

    return jsonify({
        "strategy": defaults,
        "total_capital": total_capital,
    })


# ---------------------------------------------------------------------------
# API – Portfolio settings
# ---------------------------------------------------------------------------

@app.route("/api/portfolio/settings", methods=["PUT"])
def api_update_settings():
    body = request.get_json(force=True)

    portfolio = _read_portfolio()
    allowed_keys = {"rotation_pool", "monthly_btd_budget", "total_capital"}
    for key in allowed_keys:
        if key in body:
            portfolio[key] = body[key]

    # Recalculate bucket target_amount when total_capital changes
    # Skip buckets with weight=0 (fixed-dollar buckets like satellite)
    if "total_capital" in body:
        strategy = _read_strategy()
        total_capital = portfolio["total_capital"]
        for bk, bd in portfolio.get("buckets", {}).items():
            weight = strategy.get("bucket_weights", {}).get(bk, 0)
            bd["target_weight"] = weight
            if weight > 0:
                bd["target_amount"] = round(total_capital * weight / 100, 2)

    _write_portfolio(portfolio, "Update portfolio settings")
    return jsonify(portfolio)


# ---------------------------------------------------------------------------
# API – Summary / scenarios
# ---------------------------------------------------------------------------

@app.route("/api/summary")
def api_summary():
    portfolio = _read_portfolio()
    tickers = _collect_tickers(portfolio)
    raw_market = market.fetch_all_tickers(tickers)

    # Build per-bucket actual values and deviation from target
    bucket_summaries = {}
    total_actual = 0
    for bucket_key, bucket in portfolio.get("buckets", {}).items():
        bucket_actual = 0
        holdings_detail = []
        for holding in bucket.get("holdings", []):
            ticker = holding["ticker"]
            price = raw_market.get(ticker, {}).get("price", 0)
            shares = holding.get("actual_shares", 0)
            value = shares * price
            bucket_actual += value
            holdings_detail.append({
                "ticker": ticker,
                "shares": shares,
                "price": price,
                "value": round(value, 2),
                "target_amount": holding.get("target_amount", 0),
                "deviation": round(value - holding.get("target_amount", 0), 2),
            })

        target_amount = bucket.get("target_amount", 0)
        bucket_summaries[bucket_key] = {
            "name": bucket.get("name", bucket_key),
            "target_amount": target_amount,
            "actual_value": round(bucket_actual, 2),
            "deviation": round(bucket_actual - target_amount, 2),
            "holdings": holdings_detail,
        }
        total_actual += bucket_actual

    # Scenario analysis
    bull = market.compute_scenario(portfolio, raw_market, 5.0)
    bear = market.compute_scenario(portfolio, raw_market, -5.0)
    crash = market.compute_scenario(portfolio, raw_market, -10.0)

    return jsonify({
        "total_capital": portfolio.get("total_capital", 0),
        "total_actual": round(total_actual, 2),
        "buckets": bucket_summaries,
        "scenarios": {
            "bull_5pct": bull,
            "bear_5pct": bear,
            "crash_10pct": crash,
        },
    })


# ---------------------------------------------------------------------------
# API – Cache management
# ---------------------------------------------------------------------------

@app.route("/api/cache/clear", methods=["POST"])
def api_clear_cache():
    market.clear_cache()
    return jsonify({"status": "ok", "message": "Market data cache cleared"})


# ---------------------------------------------------------------------------
# API – IBKR Integration
# ---------------------------------------------------------------------------


_gateway_process = None   # Track the gateway subprocess


@app.route("/api/ibkr/config", methods=["GET", "PUT"])
def api_ibkr_config():
    """Get or update IBKR configuration (account_id, gateway_url)."""
    config_path = os.path.join(DATA_DIR, "config.json")
    try:
        with open(config_path, "r") as f:
            config = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        config = {}

    if request.method == "GET":
        ibkr_cfg = config.get("ibkr", {})
        return jsonify({
            "gateway_url": ibkr_cfg.get("gateway_url", "https://localhost:5001"),
            "account_id": ibkr_cfg.get("account_id", ""),
        })

    body = request.get_json(force=True, silent=True) or {}
    config.setdefault("ibkr", {})
    if "account_id" in body:
        config["ibkr"]["account_id"] = body["account_id"].strip()
    if "gateway_url" in body:
        config["ibkr"]["gateway_url"] = body["gateway_url"].strip().rstrip("/")

    with open(config_path, "w") as f:
        json.dump(config, f, indent=2)
        f.write("\n")

    return jsonify({"status": "ok", "ibkr": config["ibkr"]})


@app.route("/api/ibkr/gateway/start", methods=["POST"])
def api_ibkr_gateway_start():
    """Start the IBKR Client Portal Gateway as a background process."""
    global _gateway_process

    # Check if already running
    if _gateway_process and _gateway_process.poll() is None:
        return jsonify({"status": "already_running", "pid": _gateway_process.pid})

    # Locate gateway directory
    body = request.get_json(force=True, silent=True) or {}
    gw_dir = body.get("gateway_dir", "")
    if not gw_dir:
        gw_dir = os.environ.get("IBKR_GATEWAY_DIR", os.path.expanduser("~/Downloads/clientportal.gw"))

    run_script = os.path.join(gw_dir, "bin", "run.sh")
    conf_yaml = os.path.join(gw_dir, "root", "conf.yaml")
    if not os.path.isfile(run_script):
        return jsonify({"error": f"Gateway not found at {gw_dir}. Download it from IBKR."}), 404

    try:
        _gateway_process = subprocess.Popen(
            [run_script, conf_yaml],
            cwd=gw_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        return jsonify({"status": "started", "pid": _gateway_process.pid})
    except Exception as e:
        return jsonify({"error": f"Failed to start gateway: {e}"}), 500


@app.route("/api/ibkr/gateway/stop", methods=["POST"])
def api_ibkr_gateway_stop():
    """Stop the running IBKR Client Portal Gateway process."""
    global _gateway_process
    if _gateway_process and _gateway_process.poll() is None:
        _gateway_process.terminate()
        _gateway_process.wait(timeout=5)
        _gateway_process = None
        return jsonify({"status": "stopped"})
    return jsonify({"status": "not_running"})


@app.route("/api/ibkr/status")
def api_ibkr_status():
    """Check IBKR Client Portal Gateway connection/auth status."""
    status = ibkr.check_auth()
    # Also report whether we started the gateway process
    if _gateway_process and _gateway_process.poll() is None:
        status["gateway_managed"] = True
        status["gateway_pid"] = _gateway_process.pid
    else:
        status["gateway_managed"] = False
    return jsonify(status)


@app.route("/api/ibkr/accounts")
def api_ibkr_accounts():
    """List available IBKR accounts."""
    try:
        accounts = ibkr.get_accounts()
        return jsonify({"accounts": accounts})
    except Exception as e:
        return jsonify({"error": str(e)}), 502


@app.route("/api/ibkr/positions")
def api_ibkr_positions():
    """Fetch raw positions from IBKR (preview before sync)."""
    try:
        positions = ibkr.get_positions()
        return jsonify({"positions": positions, "count": len(positions)})
    except Exception as e:
        return jsonify({"error": str(e)}), 502


@app.route("/api/ibkr/trades")
def api_ibkr_trades():
    """Fetch recent trades from IBKR (preview before sync)."""
    days = request.args.get("days", 7, type=int)
    try:
        trades = ibkr.get_trades(days=min(days, 7))
        return jsonify({"trades": trades, "count": len(trades)})
    except Exception as e:
        return jsonify({"error": str(e)}), 502


@app.route("/api/ibkr/sync", methods=["POST"])
def api_ibkr_sync():
    """Sync positions and trades from IBKR into portfolio.json.

    Body (optional):
        { "bucket_map": {"AAPL": "tech_stocks", ...}, "sync_trades": true, "trade_days": 7 }
    """
    body = request.get_json(force=True, silent=True) or {}
    bucket_map = body.get("bucket_map", {})
    sync_trades = body.get("sync_trades", True)
    trade_days = min(body.get("trade_days", 7), 7)

    portfolio = _read_portfolio()

    try:
        pos_result = ibkr.sync_positions_to_portfolio(portfolio, bucket_map=bucket_map)
    except Exception as e:
        return jsonify({"error": f"Position sync failed: {e}"}), 502

    trade_result = None
    if sync_trades:
        try:
            trade_result = ibkr.sync_trades_to_portfolio(portfolio, days=trade_days)
        except Exception as e:
            trade_result = {"error": str(e), "added": 0, "skipped": 0}

    _write_portfolio(portfolio, commit_msg="IBKR sync: update positions and trades")

    return jsonify({
        "status": "ok",
        "positions": pos_result,
        "trades": trade_result,
    })


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    app.run(debug=True, port=5000)
