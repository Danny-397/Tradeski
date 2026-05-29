# Tradeski — Real-Time Market Intelligence Platform

[![CI](https://github.com/Danny-397/Tradeski/actions/workflows/ci.yml/badge.svg)](https://github.com/Danny-397/Tradeski/actions/workflows/ci.yml)
[![Python 3.12](https://img.shields.io/badge/python-3.12-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Tests](https://img.shields.io/badge/tests-46%20passing-brightgreen.svg)](#running-tests)

Tradeski is a full-stack, production-deployed financial analytics platform that streams live equity data, computes a complete suite of quantitative indicators, and delivers real-time market intelligence through a cyber-styled interactive dashboard. It combines a Python backend with a modern JavaScript frontend connected over WebSockets, and integrates AI-powered financial analysis through a built-in assistant named Ski.

**Live deployment:** Railway (backend) + Vercel (frontend)

---

## Table of Contents

- [Overview](#overview)
- [Feature Set](#feature-set)
- [Architecture](#architecture)
- [Tech Stack](#tech-stack)
- [Quantitative Indicators](#quantitative-indicators)
- [Ski — AI Financial Assistant](#ski--ai-financial-assistant)
- [API Reference](#api-reference)
- [Getting Started](#getting-started)
- [Running Tests](#running-tests)
- [Deployment](#deployment)
- [Project Motivation](#project-motivation)

---

## Overview

Tradeski was built to solve a real problem: retail traders have access to market data but rarely have the tooling to act on it quickly. Most dashboards are either paywalled, cluttered, or require no engineering depth to use.

This project implements the full data pipeline from scratch — live price ingestion, database persistence, quantitative analysis, alert evaluation, macroeconomic context, news sentiment scoring, portfolio tracking, and real-time visualization. Every technical indicator is implemented from first principles in [`tracker/analyzer.py`](tracker/analyzer.py). The AI assistant (Ski) is grounded in real-time market data rather than relying on static training knowledge alone.

---

## Feature Set

### Real-Time Data Streaming
- Live equity prices via WebSocket (Socket.IO / eventlet)
- Configurable polling interval with automatic chart extension
- Multi-symbol watchlist with per-symbol price refresh and color-coded flash animations
- Scrolling live ticker tape across 9 symbols

### Interactive Candlestick Charts
- Real OHLC data sourced directly from yfinance for true candlestick rendering
- Six timeframes: **1D** (5-min bars), **5D** (15-min), **1M**, **3M**, **6M**, **1Y** (daily)
- Multi-subplot Plotly layout: candlestick + volume + RSI subpanel + MACD subpanel
- Toggleable overlays: Bollinger Bands, SMA 20/50, EMA 20, volume bars
- Chart.js sparklines per watchlist item (30-day trend at a glance)

### Quantitative Analytics Engine
Ten indicators implemented from scratch without TA-Lib or pandas:

| Indicator | Description |
|---|---|
| SMA (20, 50) | Simple Moving Average — window-isolated to avoid floating-point drift |
| EMA (20) | Exponential Moving Average — standard `k = 2/(n+1)` multiplier |
| RSI (14) | Relative Strength Index — Wilder smoothing method |
| MACD | 12/26 EMA divergence with 9-period signal line and histogram |
| Bollinger Bands | ±2σ bands around SMA-20 with fill visualization |
| Z-Score | Rolling 20-period deviation from mean |
| Volatility | Rolling standard deviation proxy for realized vol |
| ATR (14) | Average True Range — Wilder smoothed over true range |
| Stochastic | %K/%D oscillator with configurable lookback |
| Linear Regression | Least-squares next-value prediction via `numpy.linalg.lstsq` |

### Macroeconomic Ribbon (FRED API)
A live scrolling ribbon beneath the header displays seven Federal Reserve economic indicators, refreshed every hour from the St. Louis Federal Reserve's FRED API:

| Series | Metric |
|---|---|
| CPIAUCSL | Consumer Price Index (YoY %) |
| FEDFUNDS | Effective Federal Funds Rate |
| GDP | Real GDP (Chained 2017 $B) |
| UNRATE | Unemployment Rate |
| DGS10 | 10-Year Treasury Yield |
| T10Y2Y | Yield Curve Spread (10Y − 2Y) |
| BAMLH0A0HYM2 | High-Yield Credit Spread (OAS) |

Each indicator shows the current value, trend direction (↑ / ↓), and date of last observation.

### News Feed & Sentiment Analysis
- NewsAPI integration fetches recent headlines for each tracked stock
- Every headline is scored using VADER (Valence Aware Dictionary and sEntiment Reasoner)
- The standard VADER lexicon is augmented with ~30 financial-domain terms (e.g., "beats" → +2.0, "bankruptcy" → −3.0, "downgraded" → −1.8) to correct the systematic under-scoring of financial jargon
- Each article displays a sentiment chip (BULLISH / BEARISH / NEUTRAL) with numeric score
- An aggregate sentiment badge in the panel header summarizes the overall tone

### Portfolio Tracker
- Add holdings by symbol, share count, and optional average cost basis
- Real-time P&L calculation: unrealized gain/loss (% and $) per position
- Total portfolio value and aggregate P&L displayed in the sidebar
- Persistent storage in SQLite via UPSERT — re-adding a symbol updates the existing position
- Portfolio holdings are injected into Ski's context for personalized analysis

### Alert Engine
- Rule-based alerts: price above/below threshold, RSI overbought (>70) / oversold (<30), volume spike, volatility spike
- Cooldown tracking suppresses duplicate triggers
- Pushover push notification integration (optional)
- SQLite persistence — alerts survive server restarts
- Real-time signal feed panel in the dashboard UI

### Stock Screener
A full-universe fundamental screener covering 28 curated stocks across five sectors:

- **Filters:** P/E ratio (min/max), market cap tier (Mega / Large / Mid / Small), sector, 52-week performance (min/max %)
- **Sortable columns:** Symbol, Name, Price, P/E, Market Cap, Sector, 52W High, 52W Low, 52W Performance
- Clicking a symbol in the results closes the screener and loads that stock as the active chart
- Data fetched from yfinance in parallel (8-worker thread pool) and cached for 10 minutes

### Ski — AI Financial Assistant
See the [dedicated section](#ski--ai-financial-assistant) below.

---

## Architecture

```
Tradeski/
│
├── tracker/                   # Core Python backend module
│   ├── analyzer.py            # Quantitative indicators (10 functions, from scratch)
│   ├── database.py            # SQLite persistence (prices, alerts, portfolio)
│   ├── price_fetcher.py       # yfinance: live prices, OHLC history, screener data
│   ├── fred.py                # FRED API client — 7 macro series with trend direction
│   ├── news.py                # NewsAPI client + VADER sentiment scoring
│   ├── alerts.py              # Rule-based alert evaluation engine
│   ├── notifier.py            # Pushover push notification handler
│   ├── scheduler.py           # APScheduler background job manager
│   ├── daily_summary.py       # Daily price/volume summary generator
│   ├── pruning.py             # Automatic 30-day data retention cleanup
│   ├── config.py              # Environment variable configuration
│   ├── logger.py              # Rotating file + console logger
│   └── main.py                # Real-time tracker entry point
│
├── Plotly dashboard/          # Flask + Socket.IO application server
│   ├── app.py                 # REST API, WebSocket emitters, Ski /chat endpoint
│   └── cache.py               # TTL in-memory cache (SimpleCache)
│
├── frontend/                  # Dashboard UI (served via Vercel)
│   ├── index.html             # Full layout: header, ticker, macro ribbon, sidebars, modals
│   ├── styles.css             # Cyber fintech dark theme (~1,400 lines, CSS custom properties)
│   └── dashboard.js           # Real-time logic: WebSocket, Plotly, Chart.js, Ski, screener
│
├── tests/                     # pytest suite (46 tests across 9 files)
│   ├── test_analyzer.py       # Indicator correctness: shape, range, arithmetic accuracy
│   ├── test_database.py       # SQLite round-trip tests for prices, alerts, portfolio
│   ├── test_fred.py           # FRED client with mocked HTTP responses
│   ├── test_news.py           # NewsAPI + VADER scorer with mocked responses
│   ├── test_portfolio.py      # Portfolio CRUD and UPSERT behavior
│   ├── test_screener.py       # Screener data normalization and edge cases
│   ├── test_notifier.py       # Pushover mock tests
│   └── test_price_fetcher.py  # Live yfinance smoke test
│
├── .github/workflows/ci.yml   # GitHub Actions: lint → test on every push
├── railway.toml               # Railway deployment (gunicorn + eventlet)
├── requirements.txt           # Python dependencies (pinned where needed)
└── .env.example               # All required environment variables documented
```

### Data Flow

```
┌─────────────────────────────────────────────────────────────────┐
│  External Data Sources                                          │
│  yfinance  ·  FRED API  ·  NewsAPI  ·  Anthropic API           │
└────────┬──────────┬────────────┬───────────────┬───────────────┘
         │          │            │               │
         ▼          ▼            ▼               ▼
   price_fetcher  fred.py     news.py      /chat endpoint
         │          │            │          (claude-opus-4-7)
         ▼          │            │               │
   database.py      │            │               │
   (SQLite)         │            │               │
         │          │            │               │
         ▼          ▼            ▼               │
     analyzer.py  macro       VADER          Ski panel
     (indicators) snapshot    scores         (frontend)
         │          │            │
         └──────────┴────────────┘
                    │
                    ▼
             app.py (Flask)
           ┌─────────────────┐
           │  REST Endpoints │   WebSocket
           │  /stats         │──────────────► price_update
           │  /price_history │──────────────► alert_triggered
           │  /macro         │
           │  /news          │
           │  /portfolio     │
           │  /screener      │
           │  /chat          │
           └────────┬────────┘
                    │ JSON / WS
                    ▼
             dashboard.js
          (Plotly · Chart.js · Socket.IO)
```

---

## Tech Stack

| Layer | Technology |
|---|---|
| Language | Python 3.12 |
| Web Framework | Flask + Flask-SocketIO |
| Real-Time Transport | WebSocket (Socket.IO / eventlet) |
| Database | SQLite (Python stdlib `sqlite3`) |
| Market Data | yfinance (Yahoo Finance) |
| Macro Data | FRED API (St. Louis Federal Reserve) |
| News Data | NewsAPI |
| Sentiment Analysis | VADER (`vaderSentiment`) + financial lexicon |
| AI Assistant | Anthropic Claude claude-opus-4-7 (via `anthropic` SDK) |
| Prompt Caching | Anthropic ephemeral cache (4-block system prompt) |
| Parallel Fetching | `concurrent.futures.ThreadPoolExecutor` |
| Scheduler | APScheduler |
| Notifications | Pushover API |
| Frontend Charting | Plotly.js (candlestick + multi-subplot) |
| Frontend Sparklines | Chart.js 4.4 |
| Frontend Runtime | Vanilla JavaScript (ES2020) |
| Fonts | Inter + JetBrains Mono |
| CI/CD | GitHub Actions |
| Linting | Flake8 (max line length 120) |
| Testing | pytest (46 tests) |
| Backend Hosting | Railway |
| Frontend Hosting | Vercel |

---

## Quantitative Indicators

All indicators live in [`tracker/analyzer.py`](tracker/analyzer.py) and are implemented without TA-Lib or pandas. This was a deliberate choice: implementing them from first principles requires genuine engagement with the underlying mathematics, not just an API call.

### Simple Moving Average
An arithmetic mean over a rolling window. Each window is computed independently (not accumulated), which avoids floating-point drift over long series.

### Exponential Moving Average
Uses the standard multiplier `k = 2 / (period + 1)`. Seeded from the first price, then iterated: `ema = price × k + prev × (1 − k)`.

### RSI — Wilder Smoothing
Initial up/down averages are computed over the seed period using an arithmetic mean. Subsequent values use Wilder's smoothing: `avg = (prev × (period − 1) + current) / period`. Returns values in [0, 100]. Wilder smoothing was chosen over SMA-based RSI because it is the industry-standard formulation and produces less volatile results.

### MACD
12-period EMA minus 26-period EMA. The signal line is a 9-period EMA of the MACD line. The histogram is `MACD − Signal`. All three periods are configurable.

### Bollinger Bands
Upper and lower bands: `SMA ± (std_factor × rolling_std)`. Default: 20-period SMA, 2.0 standard deviations. Band width (upper − lower) / SMA serves as a proxy for short-term realized volatility.

### Z-Score
Rolling z-score: `(price − mean) / std` over a configurable window. Returns 0.0 when `std = 0` to avoid division errors on flat series.

### ATR (Average True Range)
True range: `max(High − Low, |High − PrevClose|, |Low − PrevClose|)`. Smoothed using Wilder's method to match the original Wilder (1978) specification.

### Stochastic Oscillator
`%K = (Close − LowestLow) / (HighestHigh − LowestLow) × 100`. `%D` is a 3-period SMA of `%K`. Returns 50.0 when the high-low range is zero.

### Linear Regression Prediction
Fits a least-squares line to the full price series using `numpy.linalg.lstsq`, then extrapolates one step forward. Displayed as a next-bar prediction overlay on the chart.

---

## Ski — AI Financial Assistant

Ski is an AI-powered financial Q&A assistant embedded in the dashboard, powered by **Claude claude-opus-4-7** (Anthropic). It is designed to function like a knowledgeable analyst who has seen the same data as the user.

### What Makes Ski Different from a Generic Chatbot

Most AI assistants answer financial questions in a vacuum. Ski is grounded in three live data sources that are injected into its system context on every request:

| Context Block | Source | Content |
|---|---|---|
| System prompt | Static (cached) | Deep financial knowledge: equities, macro, sector rotation, indicator signals |
| Macro context | FRED API (cached 1h) | Current CPI, Fed Funds Rate, GDP, unemployment, yield curve, credit spreads |
| Portfolio context | SQLite (live) | User's holdings, share counts, avg cost, current P&L |
| News context | NewsAPI + VADER (cached 30m) | Recent headlines for the viewed symbol with sentiment scores |

This means Ski can answer questions like "Is now a good time to add to my NVDA position?" with awareness of the user's actual cost basis, the current macro environment, and the most recent news sentiment — not just general knowledge.

### Prompt Architecture

The Anthropic `ephemeral` cache control is applied to the stable system prompt block, which is the longest and most expensive block to process. The three dynamic context blocks (macro, portfolio, news) are appended after the cached prefix, minimizing token costs across repeated requests.

```python
system_blocks = [
    {"type": "text", "text": SKI_SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}},
    {"type": "text", "text": macro_context},      # FRED snapshot
    {"type": "text", "text": portfolio_context},  # user holdings + P&L
    {"type": "text", "text": news_context},       # VADER-scored headlines
]
```

### Capabilities
- Equity analysis: valuations, earnings, sector dynamics, technical signals
- Macro interpretation: what rate decisions, CPI prints, and GDP readings mean for specific sectors
- Portfolio-aware Q&A: cost basis, P&L context, concentration risk
- News sentiment analysis: connects headline tone to price action patterns
- Educational explanations: options Greeks, yield curve mechanics, short interest dynamics

Ski always clarifies it provides educational information, not personalized investment advice.

---

## API Reference

### `GET /health`
Railway health check. Returns `{"status": "ok"}`.

### `GET /stats?symbol=AAPL`
OHLC snapshot + real 52-week range sourced from yfinance (cached 5 min).

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

### `GET /price_history?symbol=AAPL&tf=1M`
Full OHLC + indicator payload for charting. All arrays are index-aligned to `timestamps`. Valid `tf` values: `1D`, `5D`, `1M`, `3M`, `6M`, `1Y`.

```json
{
  "timestamps": ["2024-01-02T00:00:00", "..."],
  "open": [...], "high": [...], "low": [...], "close": [...],
  "volume": [...],
  "sma20": [...], "sma50": [...], "ema20": [...],
  "rsi": [...], "macd": [...], "signal": [...], "histogram": [...],
  "upper_band": [...], "lower_band": [...],
  "zscore": [...], "volatility": [...],
  "prediction": 191.32
}
```

### `GET /sparkline?symbol=AAPL`
30-day daily close prices for watchlist sparkline charts (cached 5 min).

### `GET /macro`
Current FRED macro snapshot (cached 1 hour). Requires `FRED_API_KEY`.

```json
{
  "CPIAUCSL": {"label": "CPI", "value": 3.2, "unit": "%", "trend": "down", "date": "2024-10-01"},
  "FEDFUNDS": {"label": "Fed Funds Rate", "value": 5.33, "unit": "%", "trend": "neutral", "date": "..."},
  "..."
}
```

### `GET /news?symbol=AAPL`
VADER-scored headlines + aggregate sentiment (cached 30 min). Requires `NEWS_API_KEY`.

```json
{
  "symbol": "AAPL",
  "articles": [
    {
      "title": "Apple beats Q4 earnings expectations",
      "url": "https://...",
      "source": "Reuters",
      "published_at": "2024-11-01T12:00:00Z",
      "sentiment": 0.612,
      "sentiment_label": "bullish"
    }
  ],
  "aggregate": {
    "score": 0.341,
    "label": "bullish",
    "count": 10,
    "bullish_count": 7,
    "neutral_count": 2,
    "bearish_count": 1
  }
}
```

### `GET /portfolio`
All holdings enriched with current prices and P&L.

### `POST /portfolio`
Add or update a holding. Body: `{ "symbol": "AAPL", "shares": 10, "avg_cost": 175.00 }`. UPSERT — re-posting the same symbol updates the existing row.

### `DELETE /portfolio/<id>`
Remove a holding by ID.

### `GET /screener`
Fundamental screening data for the full 28-stock universe (parallel fetch, cached 10 min per symbol).

```json
{
  "stocks": [
    {
      "symbol": "AAPL", "name": "Apple Inc.", "price": 182.50,
      "pe": 29.4, "market_cap": 2800000000000,
      "sector": "Technology",
      "high_52w": 199.62, "low_52w": 124.17,
      "perf_52w": 23.5
    }
  ],
  "universe_size": 28
}
```

### `GET /alerts` · `POST /alerts` · `DELETE /alerts/<id>`
List, create, and delete rule-based alerts stored in SQLite.

### `POST /chat`
Ski AI chatbot. Body: `{ "message": "...", "history": [...], "symbol": "AAPL" }`. Injects live macro, portfolio, and news context into the system prompt. Requires `ANTHROPIC_API_KEY`.

### WebSocket Events

| Event | Direction | Payload |
|---|---|---|
| `price_update` | Server → Client | `{ symbol, price, timestamp }` |
| `alert_triggered` | Server → Client | `{ symbol, message, timestamp }` |

---

## Getting Started

### Prerequisites
- Python 3.12+
- pip

### Installation

```bash
git clone https://github.com/Danny-397/Tradeski.git
cd Tradeski
pip install -r requirements.txt
```

### Configuration

Copy `.env.example` to `.env`:

```bash
cp .env.example .env
```

Fill in the required values:

```env
# Comma-separated symbols to track via WebSocket
STOCK_SYMBOLS=AAPL,MSFT,TSLA,NVDA,AMZN

# Price polling interval (seconds)
CHECK_INTERVAL=60

# Required: Anthropic API key for Ski chatbot
ANTHROPIC_API_KEY=sk-ant-...

# Required: FRED API key for macro ribbon
# Free key at https://fred.stlouisfed.org/docs/api/api_key.html
FRED_API_KEY=...

# Required: NewsAPI key for news sentiment feed
# Free key at https://newsapi.org/register (100 req/day on free tier)
NEWS_API_KEY=...

# Optional: Pushover push notifications
PUSHOVER_USER_KEY=
PUSHOVER_API_TOKEN=
```

The dashboard works without `FRED_API_KEY` and `NEWS_API_KEY` — those panels will show a "not configured" state. The Ski chatbot requires `ANTHROPIC_API_KEY`.

### Run the Backend

```bash
cd "Plotly dashboard"
python app.py
```

Server starts on `http://localhost:5000`.

### Open the Dashboard

Open `frontend/index.html` directly in a browser, or serve it with a local file server:

```bash
python -m http.server 8080 --directory frontend
```

Then open `http://localhost:8080`.

---

## Running Tests

```bash
python -m pytest -v
```

**46 tests across 9 files**, all passing:

| File | Coverage |
|---|---|
| `test_analyzer.py` | Indicator shape, value range, and arithmetic correctness |
| `test_database.py` | SQLite round-trips for prices, alerts, and portfolio |
| `test_fred.py` | FRED client with mocked HTTP — trend detection, missing series, dot values |
| `test_news.py` | NewsAPI + VADER: financial lexicon augmentation, filtered articles, aggregation |
| `test_portfolio.py` | CRUD operations, UPSERT behavior, case-insensitive symbols |
| `test_screener.py` | Data normalization, ETF sector fallback, 52W perf conversion, edge cases |
| `test_notifier.py` | Pushover mock: correct POST structure, skip without credentials |
| `test_price_fetcher.py` | Live yfinance smoke test — positive float or `None` |

Linting:

```bash
flake8 .
```

The GitHub Actions CI pipeline runs lint and the full test suite on every push and pull request to `main`.

---

## Deployment

### Backend — Railway

1. Push to GitHub. Railway auto-deploys from `main`.
2. Set all environment variables in the Railway dashboard.
3. `railway.toml` configures the gunicorn + eventlet web process with WebSocket support.
4. Railway provisions a public HTTPS URL with persistent WebSocket connections.

### Frontend — Vercel

1. Connect the GitHub repo to Vercel and set `frontend/` as the root directory.
2. Update `CFG.API` and `CFG.WS` in [`frontend/dashboard.js`](frontend/dashboard.js) to point to your Railway URL.
3. Push — Vercel deploys in under 30 seconds.

---

## Project Motivation

Tradeski started from a simple frustration: the tools that professional traders use every day — live indicators, macro dashboards, portfolio analytics, and AI-assisted research — are either locked behind expensive Bloomberg terminals or scattered across a dozen different websites. Retail traders end up context-switching constantly, losing time and making decisions on stale or incomplete information.

The engineering goal was to build a platform that integrates all of those data sources into a single, coherent interface — and to build it properly, not as a tutorial project. That meant implementing every quantitative indicator from first principles rather than importing TA-Lib; it meant wiring a real macroeconomic data pipeline from the Federal Reserve rather than hardcoding example values; and it meant building an AI assistant that actually knows what the user is looking at, rather than answering questions in a vacuum.

The decision to implement RSI, MACD, and Bollinger Bands without a library was intentional and instructive. Writing Wilder's smoothing from scratch requires understanding why it differs from a simple moving average and what that difference means for the signal. Writing the VADER financial lexicon augmentation requires reading enough financial headlines to know that "beats" and "surges" are systematically under-scored by a general-purpose sentiment model. These are not problems that get solved by importing a package.

Tradeski covers five distinct engineering disciplines in a single codebase:

- **Data engineering** — polling, SQLite schema design, TTL caching, 30-day retention pruning
- **Backend architecture** — REST API design, WebSocket streaming, background scheduling, parallel HTTP fetching
- **Quantitative analysis** — implementing and testing ten financial algorithms from mathematical first principles
- **AI integration** — prompt engineering, context injection, prompt caching for cost efficiency
- **Frontend engineering** — real-time state management, multi-library charting (Plotly + Chart.js), responsive layout

The version of Tradeski in this repository is fully deployed and functional with real API keys. Every feature described in this README is live.

---

## License

MIT © 2026 Dan Lichtenberger. See [LICENSE](LICENSE).
