import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()


@dataclass
class AppConfig:
    stock_symbol: str
    check_interval: int
    drop_threshold_percent: float
    unchanged_minutes_threshold: int
    enable_dashboard: bool


@dataclass
class PushoverConfig:
    user_key: str
    api_token: str


def load_app_config() -> AppConfig:
    symbol = os.getenv("STOCK_SYMBOL", "AAPL").upper()
    interval = int(os.getenv("CHECK_INTERVAL", "60"))
    drop_threshold = float(os.getenv("DROP_THRESHOLD_PERCENT", "5.0"))
    unchanged_threshold = int(os.getenv("UNCHANGED_MINUTES_THRESHOLD", "5"))
    enable_dashboard = os.getenv("ENABLE_DASHBOARD", "true").lower() == "true"

    return AppConfig(
        stock_symbol=symbol,
        check_interval=interval,
        drop_threshold_percent=drop_threshold,
        unchanged_minutes_threshold=unchanged_threshold,
        enable_dashboard=enable_dashboard,
    )


def load_pushover_config() -> PushoverConfig:
    user_key = os.getenv("PUSHOVER_USER_KEY", "")
    api_token = os.getenv("PUSHOVER_API_TOKEN", "")

    return PushoverConfig(
        user_key=user_key,
        api_token=api_token,
    )
