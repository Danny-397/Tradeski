Real‑Time Stock Tracker
Live Alerts • Technical Analysis • Web Dashboard • Data Storage
This project is a full‑stack, real‑time financial monitoring system built in Python.
It tracks stock prices, performs technical analysis, detects anomalies, sends alerts, and displays everything on a live dashboard.

Designed to demonstrate skills in:

Software engineering

Data science & quantitative finance

API integration

Web development (Flask)

Multithreading

Database design

Logging & testing

Features
Real‑Time Alerts
Price drop alerts (configurable threshold)

No‑change alerts (market closed detection)

Anomaly detection using Z‑score

RSI overbought/oversold alerts

Sent via Pushover

Technical Analysis
The system automatically computes:

SMA (20, 50)

EMA (20)

RSI‑14

Volatility (σ)

Z‑score anomaly detection

Linear regression price prediction

These analytics are included in alerts and displayed on the dashboard.

Data Storage
All price checks and alerts are stored in a local SQLite database:

prices table

alerts table

This enables historical analysis and dashboard visualization.

Web Dashboard (Flask)
A live dashboard displays:

Real‑time price chart (auto‑refreshing)

Recent alerts

Historical data

Accessible at:

Code
http://127.0.0.1:5000
Testing & Logging
Unit tests using pytest

Rotating log files for debugging

Modular architecture for easy testing

Project Structure
Code
stock-tracker/
│
├── tracker/
│   ├── main.py
│   ├── config.py
│   ├── price_fetcher.py
│   ├── notifier.py
│   ├── analyzer.py
│   ├── database.py
│   ├── dashboard.py
│   ├── logger.py
│
├── tests/
│   ├── test_price_fetcher.py
│   ├── test_analyzer.py
│   ├── test_notifier.py
│
├── data/
│   ├── prices.db   (auto-created)
│
├── requirements.txt
└── .gitignore
Installation
1. Install dependencies
Code
pip install -r requirements.txt
2. Create a .env file
Code
PUSHOVER_USER_KEY=your_key_here
PUSHOVER_API_TOKEN=your_token_here

STOCK_SYMBOL=AAPL
CHECK_INTERVAL=60
DROP_THRESHOLD_PERCENT=5
UNCHANGED_MINUTES_THRESHOLD=5
ENABLE_DASHBOARD=true
Running the Application
Start the tracker:
Code
python -m tracker.main
Start the dashboard (optional):
Code
python -m tracker.dashboard
Example Alert
Code
AAPL Drop Alert
Stock dropped 5.12%
Current Price: $162.44
RSI: 28.3 (Oversold)
Volatility (20): 1.92σ
Predicted next price: $163.01
🎯 Future Improvements
WebSocket real‑time streaming (Polygon.io)

LSTM neural network prediction

Portfolio tracking

Options chain analysis

Mobile app integration

Author
Danny — Python developer, data science enthusiast, and finance researcher.
