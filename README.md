Real‑Time Stock Tracker
Live price monitoring, technical analysis, data storage, and automated alerts — built with Python, SQLite, and a modular architecture.

This project is a fully functional application designed to track stock prices in real time, analyze trends, store historical data, and send push notifications when important events occur. It demonstrates clean architecture, testing, CI/CD, and real‑world software engineering practices.

Features
Real‑time price fetching using a configurable polling interval

Technical analysis (moving averages, trend detection, volatility checks)

SQLite database storage for historical price data

Pushover notifications for alerts and threshold triggers

Config‑driven design for API keys, symbols, and user preferences

Automated tests with pytest

Continuous Integration (GitHub Actions) with linting and test enforcement

Modular, extensible architecture suitable for future expansion

Architecture Overview
Code
tracker/
    analyzer.py        # Computes trends, moving averages, and signals
    database.py        # SQLite wrapper for storing and retrieving prices
    notifier.py        # Sends Pushover alerts
    price_fetcher.py   # Fetches live stock prices
    config.py          # Configuration model for Pushover and app settings
tests/
    test_analyzer.py
    test_price_fetcher.py
    test_notifier.py
.github/workflows/
    ci.yml             # Linting and testing pipeline
requirements.txt
setup.cfg              # Flake8 configuration
This structure mirrors real-world Python applications: modular, testable, and easy to maintain.

Installation
Clone the repository:

Code
git clone https://github.com/Danny-397/real-time-stock-tracker.git
cd real-time-stock-tracker
Install dependencies:

Code
pip install -r requirements.txt
Running the Application
Run the main tracker:

Code
python tracker/main.py
Ensure your configuration (API keys, symbols, etc.) is set correctly in your config file or environment variables.

Example Output
Code
[INFO] Fetching price for AAPL...
[INFO] Latest price: 187.42
[INFO] 20-period moving average: 185.91
[INFO] Trend: Upward
[ALERT] AAPL crossed above its moving average — sending notification
Testing
Run the full test suite:

Code
pytest -q
The CI pipeline automatically runs:

flake8 linting

pytest tests

import validation

A green pipeline indicates the project is stable and production‑ready.

What I Learned
Building this project taught me how to:

Design a modular Python application with clean separation of concerns

Use SQLite for lightweight, persistent data storage

Implement real‑time data pipelines

Write automated tests that validate core logic

Configure GitHub Actions for continuous integration

Enforce code quality with flake8 and type hints

Build a real-world notification system using Pushover

This project strengthened my skills in software engineering, debugging, and system design.

Future Improvements
Add a web dashboard for live visualization

Support multiple stock symbols simultaneously

Add more technical indicators (RSI, MACD, Bollinger Bands)

Implement asynchronous price fetching for higher frequency updates

Add Docker support for deployment

Expand notification channels (email, SMS, Discord)

About the Author
Danny - Aspiring software engineer interested in automation, data systems, and real‑time analytics. Focused on building projects that can give peope some adavantage in the financial sectors of their lives. 
