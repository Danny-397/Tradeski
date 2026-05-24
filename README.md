Tradeski — Real‑Time Market Intelligence Dashboard
Tradeski is a full‑stack, real‑time financial analytics platform that streams live market data, computes quantitative indicators, and visualizes them through an interactive TradingView‑style dashboard.
It combines a high‑performance Python backend with a modern JavaScript frontend to deliver a complete market‑monitoring experience.

Features
Real‑Time Data
Live price streaming via WebSockets

Millisecond‑level updates

Automatic chart extension

Advanced Technical Indicators
Tradeski computes a full suite of quantitative indicators:

SMA20

EMA20

RSI(14)

MACD (macd, signal, histogram)

Bollinger Bands

Z‑Score

Volatility

Linear regression prediction

Interactive Dashboard
Candlestick chart

Volume bars

RSI subplot

MACD subplot

Bollinger Band overlays

Real‑time alert feed

Symbol switching

Alert Engine
Rule‑based alerts

Z‑score alerts

Threshold alerts

Real‑time push notifications to the dashboard

Full‑Stack Architecture
Python + Flask + Socket.IO backend

SQLite database

JavaScript + Plotly frontend

REST API + WebSocket streaming

Production‑ready deployment (Railway + Vercel)

Architecture Overview
Code
Tradeski/
│
├── dashboard/          # Flask + Socket.IO backend
│   ├── app.py
│   └── ...
│
├── tracker/            # Data ingestion + analytics engine
│   ├── analyzer.py
│   ├── database.py
│   └── ...
│
├── frontend/           # Public dashboard UI
│   ├── index.html
│   ├── styles.css
│   └── dashboard.js
│
└── README.md
Backend Technology
Data Pipeline
Real‑time ingestion

Timestamped price storage

Volume tracking

Automatic pruning

Analytics Engine
Implemented in analyzer.py:

SMA, EMA

RSI

MACD

Bollinger Bands

Z‑score

Volatility

Linear regression forecasting

API Endpoints
/price_history — full indicator set

/stats — OHLC + 52‑week range

/alerts — create, list, delete alerts

WebSocket Events
price_update

alert_triggered

Frontend Technology
Dashboard
Built with HTML, CSS, and vanilla JavaScript

Plotly.js for charting

Socket.IO client for real‑time updates

Charts
Candlesticks

Volume bars

RSI

MACD

Bollinger Bands

SMA/EMA overlays

UI
Dark‑mode TradingView‑style layout

Stats panel

Alerts feed

Symbol selector

How to Run Locally
Backend
Code
cd dashboard
pip install -r requirements.txt
python app.py
Frontend
Open frontend/index.html in a browser
(or serve with any static file server).

Deployment
Backend
Deployed on Railway

Auto‑redeploy on push

Public API endpoint

WebSocket support

Frontend
Deployed on Vercel

Static hosting

Instant redeploys

Connected to Railway backend

Why I Built Tradeski
Tradeski began as a personal project to explore real‑time systems, quantitative finance, and full‑stack engineering.
I wanted to build something that wasn’t just a script or a school assignment, but a complete, production‑ready platform that integrates

data engineering

backend architecture

quantitative analysis

frontend visualization

real‑time communication

Tradeski represents my interest in automation, markets, and system design — and my ability to take a complex idea from concept to a fully deployed product.

What I Learned
Building real‑time systems with WebSockets

Designing REST APIs and backend services

Implementing quantitative indicators from scratch

Managing stateful data pipelines

Structuring a full‑stack application

Deploying production services (Railway + Vercel)

Creating interactive data visualizations

Writing clean, maintainable, modular code

Future Improvements
Multi‑symbol watchlist

User accounts + authentication

Custom alert creation UI

Portfolio tracking

News + sentiment integration

Machine learning prediction models

Mobile‑optimized dashboard

Cloud database migration
