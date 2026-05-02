import requests
import time
import threading

_cache = {}
_cache_lock = threading.Lock()
CACHE_TTL = 600  # 10 minutes

HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}


def fetch_ticker_data(ticker):
    """Fetch 3 months of daily data for a single ticker from Yahoo Finance."""
    with _cache_lock:
        if ticker in _cache and time.time() - _cache[ticker]["ts"] < CACHE_TTL:
            return _cache[ticker]["data"]

    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?range=3mo&interval=1d"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        result = data["chart"]["result"][0]
        closes = result["indicators"]["quote"][0]["close"]
        closes = [c for c in closes if c is not None]
        timestamps = result.get("timestamp", [])

        if not closes:
            return None

        current = closes[-1]

        # 20-day SMA
        sma20 = sum(closes[-20:]) / min(len(closes), 20) if len(closes) >= 2 else current

        # 20-day EMA
        ema20 = _compute_ema(closes, 20)

        # 50-day SMA (for trend context)
        sma50 = sum(closes[-50:]) / min(len(closes), 50) if len(closes) >= 2 else current

        # Divergence
        div_sma = ((current - sma20) / sma20) * 100 if sma20 else 0
        div_ema = ((current - ema20) / ema20) * 100 if ema20 else 0

        # 1-month change (~22 trading days)
        chg_1m = None
        if len(closes) >= 22:
            price_1m = closes[-22]
            chg_1m = ((current - price_1m) / price_1m) * 100

        # Month-open price (approx first trading day of current month)
        month_open = _get_month_open(closes, timestamps)
        chg_from_month_open = None
        if month_open:
            chg_from_month_open = ((current - month_open) / month_open) * 100

        result_data = {
            "ticker": ticker,
            "price": round(current, 2),
            "sma20": round(sma20, 2),
            "ema20": round(ema20, 2),
            "sma50": round(sma50, 2),
            "div_sma": round(div_sma, 2),
            "div_ema": round(div_ema, 2),
            "chg_1m": round(chg_1m, 2) if chg_1m is not None else None,
            "chg_month_open": round(chg_from_month_open, 2) if chg_from_month_open is not None else None,
            "month_open": round(month_open, 2) if month_open else None,
        }

        with _cache_lock:
            _cache[ticker] = {"data": result_data, "ts": time.time()}

        return result_data

    except Exception as e:
        return {"ticker": ticker, "error": str(e)}


def _compute_ema(closes, period):
    """Compute Exponential Moving Average."""
    if len(closes) < period:
        return sum(closes) / len(closes)
    k = 2 / (period + 1)
    ema = sum(closes[:period]) / period
    for price in closes[period:]:
        ema = price * k + ema * (1 - k)
    return ema


def _get_month_open(closes, timestamps):
    """Get the opening price of the current month."""
    import datetime

    if not timestamps:
        return closes[0] if closes else None

    now = datetime.datetime.now()
    current_month = now.month
    current_year = now.year

    for i, ts in enumerate(timestamps):
        dt = datetime.datetime.fromtimestamp(ts)
        if dt.year == current_year and dt.month == current_month:
            if i < len(closes) and closes[i] is not None:
                return closes[i]
    return None


def fetch_all_tickers(tickers):
    """Fetch data for multiple tickers with rate limiting."""
    results = {}
    for ticker in tickers:
        data = fetch_ticker_data(ticker)
        if data:
            results[ticker] = data
        time.sleep(0.25)
    return results


def compute_signal(div_sma, bucket_type, thresholds_map):
    """Compute STR/BTD signal based on divergence and bucket thresholds.

    thresholds_map is a dict keyed by bucket_type, each value having
    "str" (list of (div, trim_pct, label) tuples) and
    "btd" (list of (dip, label) tuples).
    Loaded from data/strategy.json by the caller — no hardcoded fallback.
    """
    thresholds = thresholds_map.get(bucket_type)
    if not thresholds:
        return {"action": "HOLD", "label": "Hold (no thresholds)", "trim_pct": 0, "severity": "none"}

    if div_sma > 0:
        # Check STR thresholds (highest first)
        for threshold, trim_pct, label in reversed(thresholds["str"]):
            if div_sma >= threshold:
                return {"action": "STR", "label": label, "trim_pct": trim_pct, "severity": "high" if div_sma >= thresholds["str"][-1][0] else "medium"}
        if div_sma >= thresholds["str"][0][0] * 0.6:
            return {"action": "WATCH", "label": "Watch (approaching STR)", "trim_pct": 0, "severity": "low"}
    elif div_sma < 0:
        # Check BTD thresholds (most negative first)
        for threshold, label in reversed(thresholds["btd"]):
            if div_sma <= threshold:
                return {"action": "BTD", "label": label, "trim_pct": 0, "severity": "high" if div_sma <= thresholds["btd"][-1][0] else "medium"}

    return {"action": "HOLD", "label": "Hold", "trim_pct": 0, "severity": "none"}


def compute_scenario(portfolio_data, market_data, scenario_pct):
    """
    Estimate portfolio P&L for a given market move scenario.
    scenario_pct: e.g. 5.0 for +5%, -5.0 for -5%
    """
    results = {"buckets": {}, "total_change": 0, "total_value": 0, "hedge_pnl": 0, "theta_cost": 0}

    # Approximate betas
    betas = {
        "NVDA": 2.3, "MSFT": 1.1, "GOOG": 1.2, "AAPL": 1.2, "TSM": 1.4,
        "ARM": 2.0, "GEV": 1.3, "RSP": 1.0, "SPMO": 1.1, "IWY": 1.1,
        "EMXC": 0.9, "SOXX": 1.5, "DXJ": 0.8, "XLF": 1.2,
        "SCHD": 0.7, "JEPQ": 0.8, "DGRO": 0.8, "PFF": 0.3, "ALLW": 0.5,
        "GLD": -0.1, "SLV": 0.0, "GDX": -0.2, "OILK": 0.3,
    }

    for bucket_key, bucket in portfolio_data.get("buckets", {}).items():
        bucket_change = 0
        bucket_value = 0
        for holding in bucket.get("holdings", []):
            ticker = holding.get("ticker", "")
            shares = holding.get("actual_shares", 0)
            price = market_data.get(ticker, {}).get("price", holding.get("avg_price", 0))
            current_value = shares * price
            beta = betas.get(ticker, 1.0)
            change = current_value * (scenario_pct / 100) * beta
            bucket_change += change
            bucket_value += current_value

        results["buckets"][bucket_key] = {
            "name": bucket.get("name", bucket_key),
            "current_value": round(bucket_value, 2),
            "estimated_change": round(bucket_change, 2),
        }
        results["total_change"] += bucket_change
        results["total_value"] += bucket_value

    # Hedge P&L estimation
    for option in portfolio_data.get("options", []):
        contracts = option.get("contracts", 0)
        delta = option.get("delta", 0)
        avg_cost = option.get("avg_cost", 0)
        multiplier = 100
        underlying_price = 0
        underlying = option.get("underlying", "")
        if underlying in market_data:
            underlying_price = market_data[underlying].get("price", 0)

        if underlying_price and contracts:
            # Approximate option P&L using delta
            price_move = underlying_price * (scenario_pct / 100)
            option_pnl = contracts * multiplier * delta * price_move
            results["hedge_pnl"] += option_pnl

            # Theta cost (approximate monthly)
            dte = option.get("dte", 90)
            daily_theta = (avg_cost * multiplier * contracts) / max(dte, 1) * 0.7
            monthly_theta = daily_theta * 30
            results["theta_cost"] += monthly_theta

    results["total_change"] = round(results["total_change"], 2)
    results["total_value"] = round(results["total_value"], 2)
    results["hedge_pnl"] = round(results["hedge_pnl"], 2)
    results["theta_cost"] = round(results["theta_cost"], 2)
    results["net_change"] = round(results["total_change"] + results["hedge_pnl"], 2)

    return results


def fetch_ohlc_history(ticker, range_str="1y"):
    """Fetch OHLC daily candle data for a ticker.

    Returns list of {time, open, high, low, close, volume} dicts
    sorted by date ascending.  range_str can be 3mo, 6mo, 1y, 2y, 5y, max.
    """
    allowed = {"5d", "1mo", "3mo", "6mo", "1y", "2y", "5y", "max"}
    if range_str not in allowed:
        range_str = "1y"

    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?range={range_str}&interval=1d"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        result = data["chart"]["result"][0]
        timestamps = result.get("timestamp", [])
        quote = result["indicators"]["quote"][0]
        opens  = quote.get("open", [])
        highs  = quote.get("high", [])
        lows   = quote.get("low", [])
        closes = quote.get("close", [])
        vols   = quote.get("volume", [])

        candles = []
        for i, ts in enumerate(timestamps):
            o = opens[i] if i < len(opens) else None
            h = highs[i] if i < len(highs) else None
            l = lows[i]  if i < len(lows)  else None
            c = closes[i] if i < len(closes) else None
            v = vols[i]   if i < len(vols)   else None
            if o is None or h is None or l is None or c is None:
                continue
            import datetime as _dt
            day = _dt.datetime.utcfromtimestamp(ts).strftime("%Y-%m-%d")
            candles.append({
                "time": day,
                "open":  round(o, 2),
                "high":  round(h, 2),
                "low":   round(l, 2),
                "close": round(c, 2),
                "volume": v or 0,
            })

        return candles

    except Exception as e:
        return {"error": str(e)}


def clear_cache():
    """Clear the market data cache."""
    with _cache_lock:
        _cache.clear()
