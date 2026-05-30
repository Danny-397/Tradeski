# Tradeski — Real-Time Market Intelligence Platform

[![CI](https://github.com/Danny-397/Tradeski/actions/workflows/ci.yml/badge.svg)](https://github.com/Danny-397/Tradeski/actions/workflows/ci.yml)
[![Python 3.12](https://img.shields.io/badge/python-3.12-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Tests](https://img.shields.io/badge/tests-46%20passing-brightgreen.svg)](#running-tests)

**Live demo:** [tradeski.vercel.app](https://tradeski.vercel.app)

Tradeski is a full-stack, production-deployed financial analytics platform that streams live equity data, computes a complete suite of quantitative indicators, and delivers real-time market intelligence through a terminal-styled interactive dashboard. It combines a Python/Flask backend with a vanilla JavaScript frontend connected over WebSockets, and integrates AI-powered financial analysis through a built-in assistant named Ski.

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

Tradeski integrates five distinct data pipelines — live equity prices, Federal Reserve macroeconomic data, financial news with sentiment scoring, a fundamental stock screener, and an AI assistant grounded in real-time context — into a single coherent interface, with quantitative portfolio analytics and a correlation heatmap layered on top.

Every quantitative indicator is implemented from first principles without TA-Lib or pandas. The AI assistant (Ski) is grounded in live market data rather than relying on static training knowledge. The backend runs as a persistent WebSocket server on Render; the frontend is a static site deployed on Vercel.

---

## Feature Set

### Real-Time Data Streaming
- Live equity prices via WebSocket (Socket.IO / gevent) with automatic chart extension
- Scrolling ticker tape across 11 symbols with live price and percentage change
- Color-coded price flash animations on WebSocket price updates

### Interactive Charts
- True OHLC candlestick data sourced from yfinance
- Six timeframes: **1D** (5-min bars), **5D** (15-min), **1M**, **3M**, **6M**, **1Y** (daily)
- Line chart with moving cursor dot and crosshair (+) on hover
- Candlestick click: populates market data strip with that candle's exact OHLC, change %, and range
- Multi-subplot Plotly layout: main price panel + optional RSI subpanel + optional MACD subpanel
- Toggleable overlays: Bollinger Bands, SMA 20/50, EMA 20
- Isolated hover tooltips per trace — hovering EMA shows only EMA value
- **Compare mode:** overlay up to 5 symbols on a single normalized chart (all rebased to 0%) for direct relative-performance comparison

### Macroeconomic Ribbon (FRED API)
A live ribbon beneath the header displays seven Federal Reserve economic indicators, refreshed hourly from the St. Louis Fed's FRED API:

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

### Quantitative Indicators Panel
Six indicators displayed in a tabbed right sidebar, always fully expanded:
RSI (14) with gauge bar, MACD with signal line, Bollinger Bands, Z-Score (20), SMA 20, SMA 50, EMA 20 — each with a BUY / SELL / NEUTRAL signal chip.

### News Feed & Sentiment Analysis
- NewsAPI integration fetches recent headlines per symbol
- Every headline is scored using VADER (Valence Aware Dictionary and sEntiment Reasoner)
- Standard VADER lexicon augmented with ~30 financial-domain terms (e.g., "beats" → +2.0, "bankruptcy" → −3.0, "downgraded" → −1.8) to correct systematic under-scoring of financial jargon
- Each article shows a sentiment chip (BULLISH / BEARISH / NEUTRAL) with numeric score
- Aggregate sentiment badge summarizes the overall tone for the viewed symbol

### Portfolio Tracker & Risk Analytics
- Add holdings by symbol, share count, and optional average cost basis
- Real-time P&L: unrealized gain/loss (% and $) per position and portfolio total
- Persistent storage in SQLite via UPSERT — re-adding a symbol updates the existing position
- Portfolio holdings injected into Ski's context for personalized analysis
- **Risk metrics panel:** Sharpe ratio (4.5% risk-free rate), portfolio beta vs. S&P 500, and annualized volatility — computed from 1-year daily returns weighted by current market value

### Correlation Heatmap
- Opens as a full-screen modal via the **HEATMAP** button in the header
- Fetches 90 days of daily returns for all 11 tracked symbols and computes a full pairwise correlation matrix using `numpy.corrcoef`
- Plotly heatmap with a diverging red→green colorscale: green = strong positive correlation, red = negative; correlation coefficients printed on every cell
- Cached server-side for 1 hour to avoid redundant computation

### Alert Engine
- Rule-based alerts: price above/below threshold, RSI overbought (>70) / oversold (<30), volume spike, volatility spike
- Cooldown tracking suppresses duplicate triggers
- Optional Pushover push notification integration
- SQLite persistence — alerts survive server restarts

### Stock Screener
A fundamental screener covering 28 curated stocks across five sectors:
- **Filters:** P/E ratio (min/max), market cap tier (Mega / Large / Mid / Small), sector, 52-week performance (min/max %)
- **Sortable columns:** Symbol, Name, Price, P/E, Market Cap, Sector, 52W High, 52W Low, 52W Performance
- Clicking a screener result loads that stock as the active chart
- Data fetched from yfinance in parallel (8-worker thread pool), cached 10 minutes

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
├── frontend/                  # Static UI — served via Vercel
│   ├── index.html             # Full layout: header, ticker, macro ribbon, sidebars, modals
│   ├── styles.css             # Terminal dark theme (~1,500 lines, CSS custom properties)
│   └── dashboard.js           # Real-time logic: WebSocket, Plotly, Ski, screener
│
├── tests/                     # pytest suite (46 tests across 10 files)
│   ├── test_analyzer.py       # Indicator correctness: shape, range, arithmetic
│   ├── test_analyzer_basic.py # Edge cases: empty input, flat series, single-element
│   ├── test_database.py       # SQLite round-trip tests for prices, alerts, portfolio
│   ├── test_fred.py           # FRED client with mocked HTTP — trend detection, dot values
│   ├── test_news.py           # NewsAPI + VADER: financial lexicon, aggregation
│   ├── test_portfolio.py      # Portfolio CRUD and UPSERT behavior
│   ├── test_screener.py       # Screener normalization, ETF fallback, edge cases
│   ├── test_notifier.py       # Pushover mock: correct POST structure, skip without creds
│   └── test_price_fetcher.py  # Live yfinance smoke test
│
├── .github/workflows/ci.yml   # GitHub Actions: lint → test on every push
├── render.yaml                # Render deployment (gunicorn + gevent WebSocket worker)
├── vercel.json                # Vercel static deployment config
├── wsgi.py                    # WSGI entry point with gevent monkey-patching
├── requirements.txt           # Python dependencies
├── setup.cfg                  # Flake8 configuration
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
   price_fetcher  fred.py     news.py       /chat endpoint
         │          │            │          (Claude Haiku 4.5)
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
          (Plotly · Socket.IO)
```

---

## Tech Stack

| Layer | Technology |
|---|---|
| Language | Python 3.12 |
| Web Framework | Flask + Flask-SocketIO |
| Real-Time Transport | WebSocket (Socket.IO / gevent) |
| Database | SQLite (Python stdlib `sqlite3`) |
| Market Data | yfinance (Yahoo Finance) |
| Macro Data | FRED API (St. Louis Federal Reserve) |
| News & Sentiment | NewsAPI + VADER with financial lexicon |
| AI Assistant | Anthropic Claude Haiku 4.5 (via `anthropic` SDK) |
| Parallel Fetching | `concurrent.futures.ThreadPoolExecutor` |
| Scheduler | APScheduler |
| Notifications | Pushover API (optional) |
| Frontend Charting | Plotly.js |
| Frontend Runtime | Vanilla JavaScript (ES2020) |
| Fonts | Space Grotesk + JetBrains Mono |
| CI/CD | GitHub Actions |
| Linting | Flake8 |
| Testing | pytest (46 tests) |
| Backend Hosting | Render |
| Frontend Hosting | Vercel |

---

## Quantitative Indicators

All ten indicators live in [`tracker/analyzer.py`](tracker/analyzer.py) and are implemented without TA-Lib or pandas. This was a deliberate choice: implementing them from first principles requires genuine engagement with the underlying mathematics, not just an API call.

| Indicator | Description |
|---|---|
| SMA (20, 50) | Simple Moving Average — each window computed independently to avoid floating-point drift |
| EMA (20) | Exponential Moving Average — standard `k = 2/(n+1)` multiplier |
| RSI (14) | Relative Strength Index — Wilder smoothing method |
| MACD | 12/26 EMA divergence with 9-period signal line and histogram |
| Bollinger Bands | ±2σ bands around SMA-20 |
| Z-Score | Rolling 20-period deviation from mean |
| Volatility | Rolling standard deviation proxy for realized vol |
| ATR (14) | Average True Range — Wilder smoothed over true range |
| Stochastic | %K/%D oscillator with configurable lookback |
| Linear Regression | Least-squares next-value prediction via `numpy.linalg.lstsq` |

### RSI — Wilder Smoothing
Initial up/down averages are computed over the seed period using an arithmetic mean. Subsequent values use Wilder's smoothing: `avg = (prev × (period − 1) + current) / period`. Returns values in [0, 100]. Wilder smoothing was chosen over SMA-based RSI because it is the industry-standard formulation and produces less volatile results.

### Bollinger Bands
Upper and lower bands: `SMA ± (std_factor × rolling_std)`. Default: 20-period SMA, 2.0 standard deviations. Band width serves as a proxy for short-term realized volatility.

### ATR
True range: `max(High − Low, |High − PrevClose|, |Low − PrevClose|)`. Smoothed using Wilder's method to match the original Wilder (1978) specification.

---

## Ski — AI Financial Assistant

Ski is an AI-powered financial Q&A assistant embedded in the dashboard, powered by **Anthropic Claude Haiku 4.5**. It is designed to function like a knowledgeable analyst who has seen the same data as the user.

### What Makes Ski Different from a Generic Chatbot

Most AI assistants answer financial questions in a vacuum. Ski is grounded in three live data sources injected into its system context on every request:

| Context Block | Source | Content |
|---|---|---|
| System prompt | Static | Financial knowledge: equities, macro, sector rotation, indicator signals |
| Macro context | FRED API (cached 1h) | Current CPI, Fed Funds Rate, GDP, unemployment, yield curve, credit spreads |
| Portfolio context | SQLite (live) | User's holdings, share counts, avg cost, current P&L |
| News context | NewsAPI + VADER (cached 30m) | Recent headlines for the viewed symbol with sentiment scores |

This means Ski can answer questions like "Is now a good time to add to my NVDA position?" with awareness of the user's actual cost basis, the current macro environment, and the most recent news sentiment — not just general knowledge.

### Capabilities
- Equity analysis: valuations, earnings, sector dynamics, technical signals
- Macro interpretation: what rate decisions, CPI prints, and GDP readings mean for specific sectors
- Portfolio-aware Q&A: cost basis, P&L context, concentration risk
- News sentiment analysis: connects headline tone to price action patterns
- Educational explanations: options Greeks, yield curve mechanics, short interest dynamics

---

## API Reference

### `GET /health`
Health check. Returns `{"status": "ok"}`.

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
  "sma20": [...], "sma50": [...], "ema20": [...],
  "rsi": [...], "macd": [...], "signal": [...], "histogram": [...],
  "upper_band": [...], "lower_band": [...],
  "zscore": [...], "volatility": [...]
}
```

### `GET /macro`
Current FRED macro snapshot (cached 1 hour). Requires `FRED_API_KEY`.

```json
{
  "CPIAUCSL": {"label": "CPI", "value": 3.2, "unit": "%", "trend": "down", "date": "2024-10-01"},
  "FEDFUNDS": {"label": "Fed Funds Rate", "value": 5.33, "unit": "%", "trend": "neutral", "date": "..."}
}
```

### `GET /news?symbol=AAPL`
VADER-scored headlines + aggregate sentiment (cached 30 min). Requires `NEWS_API_KEY`.

```json
{
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
  "aggregate": { "score": 0.341, "label": "bullish", "count": 10 }
}
```

### `GET /portfolio` · `POST /portfolio` · `DELETE /portfolio/<id>`
List all holdings enriched with live prices and P&L, add/update a position, or remove one.

`POST` body: `{ "symbol": "AAPL", "shares": 10, "avg_cost": 175.00 }` — UPSERT on symbol.

### `GET /portfolio/risk`
Sharpe ratio, beta vs. S&P 500, and annualized volatility for the current portfolio. Fetches 1-year daily returns per holding and SPY, weights by current market value.

```json
{ "sharpe": 1.24, "beta": 0.91, "volatility": 18.4 }
```

### `GET /correlation`
Pairwise 90-day return correlation matrix for all tracked symbols (cached 1 hour).

```json
{
  "symbols": ["AAPL", "MSFT", "NVDA", "..."],
  "matrix": [[1.0, 0.874, 0.761, "..."], ["..."]]
}
```

### `GET /screener`
Fundamental data for the full 28-stock universe (parallel fetch, cached 10 min per symbol).

### `GET /alerts` · `POST /alerts` · `DELETE /alerts/<id>`
List, create, and delete rule-based alerts.

### `POST /chat`
Ski chatbot. Body: `{ "message": "...", "history": [...], "symbol": "AAPL" }`.
Injects live macro, portfolio, and news context. Requires `ANTHROPIC_API_KEY`.

### WebSocket Events

| Event | Direction | Payload |
|---|---|---|
| `price_update` | Server → Client | `{ symbol, price, change_pct, timestamp }` |
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

```bash
cp .env.example .env
```

Fill in the required values:

```env
# Required: Anthropic API key for Ski chatbot
# Get from console.anthropic.com
ANTHROPIC_API_KEY=sk-ant-...

# Required: FRED API key for macro ribbon
# Free key at https://fred.stlouisfed.org/docs/api/api_key.html
FRED_API_KEY=...

# Required: NewsAPI key for news sentiment feed
# Free key at https://newsapi.org/register (100 req/day on free tier)
NEWS_API_KEY=...

# Symbols to track via WebSocket
STOCK_SYMBOLS=AAPL,MSFT,TSLA,NVDA,AMZN

# Optional: Pushover push notifications
PUSHOVER_USER_KEY=
PUSHOVER_API_TOKEN=
```

The dashboard functions without `FRED_API_KEY` and `NEWS_API_KEY` — those panels display a "not configured" state. `ANTHROPIC_API_KEY` is required for Ski.

### Run the Backend

```bash
cd "Plotly dashboard"
python app.py
```

Server starts on `http://localhost:5000`.

### Open the Dashboard

```bash
python -m http.server 8080 --directory frontend
```

Open `http://localhost:8080`.

---

## Running Tests

```bash
python -m pytest -v
```

**46 tests across 10 files**, covering:

| File | Coverage |
|---|---|
| `test_analyzer.py` | Indicator shape, value range, and arithmetic correctness |
| `test_analyzer_basic.py` | Edge cases: empty input, flat series, single-element arrays |
| `test_database.py` | SQLite round-trips for prices, alerts, and portfolio |
| `test_fred.py` | FRED client with mocked HTTP — trend detection, missing series, dot values |
| `test_news.py` | NewsAPI + VADER: financial lexicon augmentation, filtered articles, aggregation |
| `test_portfolio.py` | CRUD operations, UPSERT behavior, case-insensitive symbols |
| `test_screener.py` | Data normalization, ETF sector fallback, 52W perf conversion, edge cases |
| `test_notifier.py` | Pushover mock: correct POST structure, skip without credentials |
| `test_price_fetcher.py` | Live yfinance smoke test |

Linting:

```bash
flake8 .
```

The GitHub Actions CI pipeline runs lint and the full test suite on every push and pull request to `main`.

---

## Deployment

### Backend — Render

1. Push to GitHub. Connect the repo to Render and select `render.yaml` for configuration.
2. Set all environment variables in the Render dashboard (Environment tab).
3. `render.yaml` configures a gunicorn + gevent WebSocket worker process.
4. Render provisions a public HTTPS URL with persistent WebSocket connections.

### Frontend — Vercel

1. Connect the GitHub repo to Vercel.
2. Vercel reads `vercel.json` and serves `frontend/` as a static site automatically.
3. Set the **Root Directory** to `frontend` in Vercel project settings.
4. Push — Vercel deploys in under 30 seconds.
5. Update `CFG.API` and `CFG.WS` in [`frontend/dashboard.js`](frontend/dashboard.js) to point to your Render URL.

---

## Project Motivation

This project started from a simple frustration: the tools professional traders use every day — live indicators, macro dashboards, portfolio analytics, and AI-assisted research — are either locked behind expensive terminals or scattered across a dozen different websites. Retail investors end up context-switching constantly, making decisions on stale or incomplete information.

The goal was to build a platform that integrates all of those data sources into a single, coherent interface — and to build it properly, not as a tutorial project. That meant implementing every quantitative indicator from first principles rather than importing a library; it meant wiring a real macroeconomic data pipeline from the Federal Reserve; and it meant building an AI assistant that actually knows what the user is looking at, rather than answering questions in a vacuum.

The decision to implement RSI, MACD, and Bollinger Bands without a library was intentional and instructive. Writing Wilder's smoothing from scratch requires understanding why it differs from a simple moving average and what that difference means for the signal. Writing the VADER financial lexicon augmentation requires reading enough financial headlines to know that "beats" and "surges" are systematically under-scored by a general-purpose sentiment model. These are not problems that get solved by importing a package.

Tradeski covers six distinct engineering disciplines in one codebase:

- **Data engineering** — real-time polling, SQLite schema design, TTL caching, 30-day retention pruning
- **Backend architecture** — REST API design, WebSocket streaming, background scheduling, parallel HTTP fetching
- **Quantitative analysis** — implementing ten financial indicators from first principles; Sharpe ratio, beta, and volatility computed from raw daily return vectors
- **Statistical computing** — pairwise correlation matrix over 90-day return series using `numpy.corrcoef`; portfolio variance weighted by live market value
- **AI integration** — context injection, grounding an LLM in live external data sources
- **Frontend engineering** — real-time state management, multi-library charting, normalized multi-stock overlays, terminal-grade UI design

---

## License

MIT © 2026 Dan Lichtenberger. See [LICENSE](LICENSE).
