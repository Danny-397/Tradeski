import time
import threading
import requests
import yfinance as yf
from datetime import datetime



# CONFIGuration
PUSHOVER_USER_KEY = input("Enter your Pushover User Key: ")
PUSHOVER_API_TOKEN = input("Enter your Pushover API Token: ")

stock_symbol = input("Enter stock symbol (Example: AAPL): ").upper()
check_interval = 60
running = True



# GET STOCK PRICE 
def get_stock_price(symbol):
    try:
        ticker = yf.Ticker(symbol)
        price = ticker.fast_info.get("last_price")

        if price is None:
            data = ticker.history(period="1d")
            if data.empty:
                return None
            price = float(data["Close"].iloc[-1])

        return float(price)

    except Exception as e:
        print(f"Error retrieving price: {e}")
        return None


# SEND PUSHOVER NOTIFICATION

def send_notification(title, message):
    try:
        requests.post(
            "https://api.pushover.net/1/messages.json",
            data={
                "token": PUSHOVER_API_TOKEN,
                "user": PUSHOVER_USER_KEY,
                "title": title,
                "message": message
            },
            timeout=5
        )
        print(f"\nNOTIFICATION SENT: {title}")

    except requests.exceptions.RequestException as e:
        print(f"Notification failed: {e}")


# SUMMARY NOTIFICATION
def send_summary(initial_price, last_price, start_time):
    end_time = datetime.now()
    runtime = end_time - start_time
    minutes = runtime.total_seconds() / 60

    percent_change = ((last_price - initial_price) / initial_price) * 100

    summary_message = (
        f"Runtime: {minutes:.1f} minutes\n"
        f"Start Price: ${initial_price:.2f}\n"
        f"End Price: ${last_price:.2f}\n"
        f"Change: {percent_change:.2f}%"
    )

    send_notification(f"{stock_symbol} Summary", summary_message)


# STOP running the program 
def stop_listener():
    global running
    while running:
        command = input("\nType 'stop' or 'send' to quit:\n").lower()
        if command in ("stop", "send"):
            running = False
            print("\nStopping tracker and sending summary...")


threading.Thread(target=stop_listener, daemon=True).start()


# INITIAL PRICE

initial_price = get_stock_price(stock_symbol)

if initial_price is None:
    print("Invalid stock symbol.")
    exit()

print("\n==============================")
print(f"Tracking: {stock_symbol}")
print(f"Starting Price: ${initial_price:.2f}")
print("==============================\n")

start_time = datetime.now()


# VARIABLES
alert_sent = False
last_price = initial_price
unchanged_minutes = 0


# MAIN LOOP
try:
    while running:

        current_price = get_stock_price(stock_symbol)

        if current_price is None:
            print("Unable to retrieve price.")
            time.sleep(check_interval)
            continue

        drop_percent = ((initial_price - current_price) / initial_price) * 100

        print(
            f"{stock_symbol} | "
            f"Price: ${current_price:.2f} | "
            f"Drop: {drop_percent:.2f}%"
        )

        # DROP ALERT
        if drop_percent >= 5 and not alert_sent:
            send_notification(
                f"{stock_symbol} Alert",
                f"Stock dropped {drop_percent:.2f}%\nCurrent Price: ${current_price:.2f}"
            )
            alert_sent = True

        # NO CHANGE ALERT
        if current_price == last_price:
            unchanged_minutes += 1
        else:
            unchanged_minutes = 0

        if unchanged_minutes >= 5:
            send_notification(
                f"{stock_symbol} No Change",
                f"No price change for 5 minutes.\nLikely market closed.\nPrice: ${current_price:.2f}"
            )
            unchanged_minutes = 0

        last_price = current_price
        time.sleep(check_interval)

except KeyboardInterrupt:
    print("\nStopped with CTRL + C")

# SEND SUMMARY ON EXIT
send_summary(initial_price, last_price, start_time)

print("\nProgram ended.")

