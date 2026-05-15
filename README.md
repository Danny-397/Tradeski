Overview
This project provides a real‑time stock price monitoring tool that retrieves live market data using the yfinance library and delivers push notifications through the Pushover API. The script continuously tracks a specified stock, alerts the user of significant price changes or inactivity, and generates a summary report upon termination.

The program is designed for reliability, simplicity, and continuous operation, with a dedicated listener thread for manual shutdown commands.

Features
Real‑time stock price retrieval using Yahoo Finance data.

Automatic detection of price drops of 5% or more.

Alerts when the stock price remains unchanged for five consecutive minutes.

Pushover push notifications for all alerts and the final summary.

Background listener thread for manual termination (stop or send).

Summary report including runtime, starting price, ending price, and percent change.

Graceful shutdown support, including CTRL + C.

Requirements
Install the required Python packages:

bash
pip install yfinance requests
You must also have:

A Pushover account

A Pushover User Key

A Pushover API Token (Application Token)

Pushover application setup:
https://pushover.net/apps/build

Usage
Run the script:

bash
python script.py
When prompted, enter:

Your Pushover User Key

Your Pushover API Token

The stock ticker symbol (e.g., AAPL)

The program will:

Retrieve the initial stock price

Begin monitoring at 60‑second intervals

Display live updates in the console

To stop the program at any time, type:

Code
stop
or

Code
send
You may also terminate with CTRL + C.
In all cases, a summary notification will be sent automatically.

Alert Conditions
Price Drop Alert
A notification is sent when the stock price falls 5% or more from the initial tracked price.

No‑Change Alert
If the stock price remains unchanged for five consecutive minutes, a notification is sent. This often indicates market closure or low activity.

Summary Notification
Upon termination, the script sends a summary containing:

Total runtime (in minutes)

Starting price

Ending price

Percent change

Code Structure
get_stock_price(symbol)  
Retrieves the most recent stock price using fast_info, with a fallback to daily historical data.

send_notification(title, message)  
Sends a push notification through the Pushover API.

send_summary(initial_price, last_price, start_time)  
Generates and sends the final session summary.

stop_listener()  
Runs in a separate thread to listen for shutdown commands.

Main Loop  
Continuously retrieves prices, checks alert conditions, and prints updates.

Notes
The default check interval is 60 seconds but can be modified in the configuration section.

The script supports any ticker symbol available through Yahoo Finance.

Network interruptions or invalid ticker symbols are handled gracefully.
