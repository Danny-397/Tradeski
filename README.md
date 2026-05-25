# Tradeski — Real-Time Market Intelligence Platform

[![CI](https://github.com/Danny-397/Tradeski/actions/workflows/ci.yml/badge.svg)](https://github.com/Danny-397/Tradeski/actions/workflows/ci.yml)
[![Python 3.11](https://img.shields.io/badge/python-3.11-blue.svg)](https://www.python.org/downloads/release/python-3110/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

Tradeski is a full-stack, real-time financial analytics platform that streams live equity data, computes a complete suite of quantitative indicators, and visualizes everything through a cyber-styled interactive trading dashboard. It combines a high-performance Python backend with a modern JavaScript frontend, connected over WebSockets for millisecond-level updates.

---

## Table of Contents

- [Overview](#overview)
- [Features](#features)
- [Architecture](#architecture)
- [Tech Stack](#tech-stack)
- [Quantitative Indicators](#quantitative-indicators)
- [API Reference](#api-reference)
- [Getting Started](#getting-started)
- [Running Tests](#running-tests)
- [Deployment](#deployment)
- [Project Motivation](#project-motivation)
- [Future Work](#future-work)

---

## Overview

Tradeski was built to solve a real problem: retail traders have access to market data but rarely have the tooling to act on it quickly. Most dashboards are either paywalled, cluttered, or require no engineering depth to use.

This project implements the full data pipeline from scratch — price ingestion, database persistence, quantitative analysis, alert evaluation, and real-time visualization — with no third-party analytics libraries. Every indicator is implemented from first principles in [`tracker/analyzer.py`](tracker/analyzer.py).

---

## Features

### Real-Time Data Streaming
- Live price updates via WebSocket (Socket.IO)
- Configurable polling interval with automatic chart extension
- Multi-symbol watchlist with per-symbol live price refresh and color-coded flash animations

### Quantitative Analytics Engine
Ten indicators implemented from scratch without TA-Lib or similar:

| Indicator | Description |
|---|---|
| SMA (20, 50) | Simple Moving Average — exact arithmetic, no drift |
| EMA (20) | Exponential Moving Average — Wilder-style weighting |
| RSI (14) | Relative Strength Index — Wilder smoothing method |
| MACD | 12/26 EMA divergence with 9-period signal and histogram |
| Bollinger Bands | ±2σ bands around SMA20 with fill visualization |
| Z-Score | Rolling 20-period deviation from mean |
| Volatility | Rolling standard deviation proxy |
| ATR (14) | Average True Range — Wilder smoothed |
| Stochastic | %K and %D oscillator with configurable lookback |
| Linear Regression | Least-squares next-value prediction |

### Alert Engine
- Rule-based alerts: price threshold, RSI overbought/oversold, volume spike, volatility spike
- Cooldown tracking to suppress duplicate notifications
- Pushover push notification integration
- SQLite persistence — alerts survive restarts
- Real-time alert feed in the dashboard UI

### Interactive Dashboard
- TradingView-style dark UI with neon cyan/green/red cyber theme
- Multi-subplot Plotly chart: candlesticks + volume + RSI + MACD
- Toggleable overlays: Bollinger Bands, SMA20/50, EMA20, volume bars
- Timeframe selector: 1D / 5D / 1M / 3M / 6M / 1Y
- Indicators panel with RSI gauge, MACD signal chip, BB position, Z-score
- 52-week range bar with live cursor dot
- Scrolling live ticker tape
- Alert creation modal with form validation

### Production Infrastructure
- CI/CD via GitHub Actions (lint → test on every push)
- Railway backend deployment with WebSocket support
- Vercel frontend deployment with instant redeploys
- Automatic daily data pruning (30-day retention)
- APScheduler background jobs for analytics refresh and daily summary

---

## Architecture

```
Tradeski/
│
├── tracker/                   # Core Python backend module
│   ├── analyzer.py            # Quantitative indicators (10 functions, from scratch)
│   ├── database.py            # SQLite persistence layer (prices + alerts)
│   ├── price_fetcher.py       # yfinance market data integration
│   ├── alerts.py              # Rule-based alert evaluation engine
│   ├── notifier.py            # Pushover push notification handler
│   ├── scheduler.py           # APScheduler background job manager
│   ├── daily_summary.py       # Daily price/volume summary generator
│   ├── pruning.py             # Automatic data retention cleanup
│   ├── config.py              # Environment variable configuration
│   ├── logger.py              # Rotating file + console logger
│   ├── main.py                # Real-time tracker entry point
│   └── dashboard.py           # Flask server launcher
│
├── Plotly dashboard/          # Flask + Socket.IO backend server
│   ├── app.py                 # REST API + WebSocket event emitters
│   ├── cache.py               # TTL in-memory cache
│   ├── index.html             # Fallback dashboard UI
│   └── Procfile               # Railway deployment config
│
├── frontend/                  # Primary dashboard UI
│   ├── index.html             # Full dashboard layout (header, watchlist, chart, alerts)
│   ├── styles.css             # Cyber fintech dark theme (CSS custom properties, animations)
│   └── dashboard.js           # Real-time logic (WebSocket, Plotly, watchlist, alerts)
│
├── tests/                     # pytest test suite
│   ├── test_analyzer.py       # Indicator correctness and shape assertions
│   ├── test_analyzer_basic.py # Integration tests for analyze_series
│   ├── test_database.py       # SQLite persistence round-trip tests
│   ├── test_notifier.py       # Pushover mock tests
│   └── test_price_fetcher.py  # Live yfinance smoke test
│
├── .github/workflows/ci.yml   # GitHub Actions CI pipeline
├── requirements.txt           # Python dependencies (pinned where needed)
├── setup.cfg                  # Flake8 configuration
└── README.md
```

### Data Flow

```
yfinance API
     │
     ▼
price_fetcher.py  ──►  database.py (SQLite)
     │                      │
     ▼                      ▼
  alerts.py          analyzer.py (indicators)
     │                      │
     ▼                      ▼
notifier.py          app.py (Flask REST + Socket.IO)
                           │
                    ┌──────┴──────┐
                    ▼             ▼
              REST /stats    WebSocket
              /price_history  price_update
              /alerts         alert_triggered
                    │
                    ▼
              dashboard.js (Plotly + Socket.IO client)
```

---

## Tech Stack

| Layer | Technology |
|---|---|
| Language | Python 3.11 |
| Web Framework | Flask + Flask-SocketIO |
| Real-Time Transport | WebSocket (Socket.IO) |
| Database | SQLite (via Python stdlib `sqlite3`) |
| Data Source | yfinance (Yahoo Finance) |
| Scheduler | APScheduler |
| Notifications | Pushover API |
| Async Worker | eventlet |
| Frontend Charting | Plotly.js |
| Frontend Runtime | Vanilla JavaScript (ES2020) |
| Fonts | Inter + JetBrains Mono |
| CI/CD | GitHub Actions |
| Linting | Flake8 (max line length 120) |
| Testing | pytest |
| Backend Hosting | Railway |
| Frontend Hosting | Vercel |

---

## Quantitative Indicators

All indicators are implemented in [`tracker/analyzer.py`](tracker/analyzer.py) without using TA-Lib or pandas. This was a deliberate choice — implementing them from first principles builds a deeper understanding of the underlying mathematics.

### Simple Moving Average
An arithmetic mean over a rolling window. Exact — no floating-point accumulation error because each window is computed independently.

### Exponential Moving Average
Uses the standard multiplier `k = 2 / (period + 1)`. Seed value is the first price.

### RSI (Wilder Smoothing)
Computes initial up/down averages over the seed period, then applies Wilder's smoothing: `avg = (prev * (period - 1) + current) / period`. Returns values in [0, 100].

### MACD
Difference between 12-period and 26-period EMAs. Signal line is a 9-period EMA of the MACD line. Histogram is `MACD - Signal`. All periods are configurable.

### Bollinger Bands
Upper and lower bands computed as `SMA ± (std_factor × rolling_std)`. Default: 20-period SMA, 2.0 standard deviations.

### Z-Score
Rolling z-score over a configurable window: `(price - mean) / std`. Returns 0 when `std = 0` to avoid division errors.

### ATR (Average True Range)
True range is `max(High - Low, |High - PrevClose|, |Low - PrevClose|)`. Smoothed using Wilder's method (same as RSI).

### Stochastic Oscillator
`%K = (Close - LowestLow) / (HighestHigh - LowestLow) × 100`. `%D` is a 3-period SMA of `%K`. Returns 50 when the range is zero.

### Linear Regression Prediction
Fits a least-squares line to the full price series using `numpy.linalg.lstsq`, then extrapolates one step forward.

---

## API Reference

### `GET /stats?symbol=AAPL`
Returns OHLC data, 52-week range, and percent change for the period stored in the database.

```json
{
  "symbol": "AAPL",
  "open": 189.42,
  "high": 191.05,
  "low": 188.30,
  "close": 190.67,
  "high_52w": 199.62,
  "low_52w": 143.90,
  "change_pct": 0.66
}
```

### `GET /price_history?symbol=AAPL&limit=300`
Returns the full indicator payload for charting. All arrays are aligned by index to `timestamps`.

```json
{
  "timestamps": [...],
  "close": [...],
  "volume": [...],
  "sma20": [...],
  "sma50": [...],
  "ema20": [...],
  "rsi": [...],
  "macd": [...],
  "signal": [...],
  "histogram": [...],
  "upper_band": [...],
  "lower_band": [...],
  "zscore": [...],
  "volatility": [...],
  "prediction": 191.32
}
```

### `GET /watchlist?symbols=AAPL,MSFT,NVDA`
Batch price lookup for the watchlist sidebar.

### `GET /market_status`
Returns `open`, `extended`, or `closed` based on server UTC time.

### `GET /alerts` · `POST /alerts` · `DELETE /alerts/<id>`
List, create, and delete rule-based alerts stored in SQLite.

### WebSocket Events

| Event | Direction | Payload |
|---|---|---|
| `price_update` | Server → Client | `{ symbol, price, change_pct, timestamp }` |
| `alert_triggered` | Server → Client | `{ symbol, message, timestamp }` |

---

## Getting Started

### Prerequisites
- Python 3.11+
- pip

### Installation

```bash
git clone https://github.com/Danny-397/Tradeski.git
cd Tradeski
pip install -r requirements.txt
```

### Configuration

Copy `.env.example` to `.env` (or set environment variables directly):

```
STOCK_SYMBOL=AAPL
CHECK_INTERVAL=60
DROP_THRESHOLD_PERCENT=5.0
UNCHANGED_MINUTES_THRESHOLD=5
ENABLE_DASHBOARD=true
PUSHOVER_USER_KEY=your_key_here
PUSHOVER_API_TOKEN=your_token_here
```

### Run the Backend

```bash
cd "Plotly dashboard"
python app.py
```

Server starts on `http://localhost:5000`.

### Run the Tracker

```bash
python -m tracker.main
```

### Open the Dashboard

Open `frontend/index.html` in a browser, or serve it with any static file server:

```bash
python -m http.server 8080 --directory frontend
```

---

## Running Tests

```bash
pip install pytest
python -m pytest -v
```

The test suite covers:
- Indicator correctness: shape, value range, and arithmetic accuracy
- Database round-trips: insert and fetch for both prices and alerts
- Notifier mocking: verifies HTTP POST structure without hitting the API
- Price fetcher smoke test: validates yfinance integration returns a positive float or `None`

Linting:

```bash
pip install flake8
flake8 .
```

The CI pipeline runs both on every push and pull request to `main`.

---

## Deployment

### Backend — Railway

1. Push to GitHub. Railway auto-deploys from `main`.
2. Set environment variables in the Railway dashboard.
3. The `Procfile` configures the web process: `python app.py`.
4. Railway provisions a public HTTPS URL with WebSocket support automatically.

### Frontend — Vercel

1. Connect the GitHub repo to Vercel.
2. Set `frontend/` as the root directory.
3. Update `CFG.API` and `CFG.WS` in [`frontend/dashboard.js`](frontend/dashboard.js) to point to your Railway URL.
4. Push — Vercel deploys instantly.

---

## Project Motivation

Tradeski started as a personal project driven by two interests: quantitative finance and real-time systems engineering. The goal was to build something that is not a tutorial clone or a school assignment, but a complete, production-deployed platform that demonstrates competence across the full engineering stack.

Implementing every indicator from scratch — rather than importing a library — was intentional. It forces engagement with the actual mathematics: understanding why RSI uses Wilder smoothing instead of a simple average, how floating-point accumulation can corrupt a naive SMA, why Bollinger Band width is a proxy for realized volatility. The code reflects that understanding.

The project touches five distinct engineering disciplines:

- **Data engineering** — polling, storage, retention, schema design
- **Backend architecture** — REST API design, WebSocket streaming, background scheduling
- **Quantitative analysis** — implementing and testing financial algorithms from first principles
- **Frontend engineering** — real-time state management, canvas rendering, responsive layout
- **DevOps** — CI/CD pipelines, containerized deployment, environment configuration

---

## Future Work

- **Portfolio tracking** — position entry/exit, P&L calculation, exposure heatmap
- **User authentication** — per-user watchlists, alerts, and settings
- **News & sentiment** — NLP-based headline scoring integrated into the signal feed
- **ML forecasting** — LSTM or transformer-based price prediction as a chart overlay
- **Options chain visualization** — IV surface, open interest, Greeks display
- **Cloud database migration** — PostgreSQL on Supabase for multi-user scale
- **Mobile-optimized layout** — responsive grid collapse for tablet and phone
- **Order simulation** — paper trading mode with a virtual portfolio

---

## License

MIT © 2026 Dan Lichtenberger. See [LICENSE](LICENSE).
