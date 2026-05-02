# Portfolio Dashboard

A local-first web dashboard for tracking and managing a multi-bucket investment portfolio. Built with Flask + vanilla JS, it provides real-time market data, signal-based trading alerts, interactive charts, and strategy tuning -- all running on your machine with no external accounts required.

## Features

### Dashboard
- Real-time market prices via Yahoo Finance (10-minute cache)
- Per-ticker STR (Sell-The-Rip) and BTD (Buy-The-Dip) signal computation based on 20-day SMA divergence
- Color-coded signal badges (STR / BTD / WATCH / HOLD)
- Portfolio P&L overview with unrealized gains per holding
- Filter by bucket or signal type

### Portfolio Management
- Organize holdings into configurable buckets (e.g. Tech Stocks, Growth ETFs, Defensive ETFs, Gold/Silver, Hedges)
- Inline-editable cells for shares and average price (click to edit, Enter to save)
- Options/hedges tracking with delta, DTE, and budget fields
- Record BUY/SELL trades with automatic weighted-average cost recalculation
- Trade log with delete capability

### Price History
- Interactive candlestick charts powered by [Lightweight Charts](https://github.com/nicehash/lightweight-charts)
- 20-day and 60-day moving average overlays
- Configurable time ranges: 1 Week, 1 Month, 3 Months, 6 Months, 1 Year, 2 Years, 5 Years, Max
- BUY/SELL trade markers on the chart with average cost line
- Position summary cards (shares, market value, unrealized/realized P&L)
- Per-trade P&L breakdown table

### Strategy Tuning
- Editable bucket allocation weights with auto-calculated dollar amounts
- Per-bucket STR thresholds (3 tiers: divergence % + trim %)
- Per-bucket BTD thresholds (3 tiers: dip %)
- Hedge strategy parameters (put/call split, DTE range, delta range, OTM %)
- Save/Reset to defaults -- all changes immediately reflected in Dashboard signals
- Strategy fully decoupled into JSON (no hardcoded values in Python)

### Summary & Scenarios
- Bucket-level deviation analysis (actual vs target allocation)
- Scenario modeling: Bull (+5%), Bear (-5%), Crash (-10%) with beta-weighted estimates
- Hedge P&L and theta cost approximations

### Data Protection
- **Atomic writes**: `tempfile` + `os.replace()` prevents corruption on crash
- **Rolling backups**: Last 50 snapshots saved automatically in `data/backups/`
- **Git auto-commit**: Every mutation gets a descriptive commit message (if git is configured)

## Quick Start

### Prerequisites
- Python 3.10+
- [`uv`](https://github.com/astral-sh/uv) (recommended) or `pip`

### Setup

```bash
# Clone the repo
git clone git@github.com:realAaronWu/portfolio-dashboard.git
cd portfolio-dashboard

# Create the data directory
mkdir -p data

# Copy sample files as starting point
cp data.sample/portfolio.json data/portfolio.json
cp data.sample/strategy_defaults.json data/strategy_defaults.json
```

### Run

```bash
# With uv (auto-installs dependencies)
uv run app.py

# Or with pip
pip install flask requests
python app.py
```

Open [http://127.0.0.1:5000](http://127.0.0.1:5000) in your browser.

### Using a Private Data Repo

To keep your personal portfolio data separate and version-controlled privately:

```bash
# Clone your private data repo into the data/ directory
git clone git@github.com:<your-user>/portfolio.git data

# The app reads from data/portfolio.json and data/strategy.json automatically
```

## Project Structure

```
portfolio-dashboard/
├── app.py                  # Flask backend (routes, API endpoints, data helpers)
├── market.py               # Yahoo Finance data fetching, signal computation, scenario modeling
├── static/
│   ├── css/style.css       # Dark-themed responsive UI styles
│   └── js/app.js           # Frontend logic (dashboard, portfolio, inline editing, trades)
├── templates/
│   ├── base.html           # Shared layout with navbar
│   ├── dashboard.html      # Market signals overview
│   ├── portfolio.html      # Holdings management + trade modal
│   ├── history.html        # Candlestick charts with MA overlays
│   ├── strategy.html       # Strategy parameter tuning
│   └── summary.html        # Allocation analysis + scenarios
├── data/                   # User data (gitignored)
│   ├── portfolio.json      # Holdings, trades, capital
│   ├── strategy.json       # Active strategy config
│   ├── strategy_defaults.json  # Default strategy template
│   └── backups/            # Rolling backup snapshots
├── data.sample/            # Sample templates for fresh setup
│   ├── portfolio.json
│   └── strategy_defaults.json
├── .gitignore
└── README.md
```

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/market-data` | Fetch prices + signals for all tickers |
| GET | `/api/portfolio` | Read portfolio data |
| PUT | `/api/portfolio/holding` | Update a holding (shares, avg price) |
| POST | `/api/portfolio/holding` | Add a new holding |
| DELETE | `/api/portfolio/holding` | Remove a holding |
| POST | `/api/portfolio/trade` | Record a BUY/SELL trade |
| DELETE | `/api/portfolio/trade` | Delete a trade log entry |
| GET | `/api/history/<ticker>` | OHLC candles + trades for a ticker |
| GET | `/api/strategy` | Read active strategy |
| PUT | `/api/strategy` | Update strategy |
| POST | `/api/strategy/reset` | Reset strategy to defaults |
| GET | `/api/summary` | Allocation summary + scenario analysis |
| POST | `/api/cache/clear` | Clear market data cache |

## License

Private use.
