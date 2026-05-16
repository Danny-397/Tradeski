from typing import Optional
import requests
from .config import PushoverConfig
from .logger import get_logger
from . import database

logger = get_logger(__name__)


class Notifier:
    def __init__(self, pushover_config: PushoverConfig):
        self.pushover_config = pushover_config

    def send_pushover(self, title: str, message: str) -> None:
        if not self.pushover_config.user_key or not self.pushover_config.api_token:
            logger.warning("Pushover credentials not set; skipping notification.")
            return

        try:
            resp = requests.post(
                "https://api.pushover.net/1/messages.json",
                data={
                    "token": self.pushover_config.api_token,
                    "user": self.pushover_config.user_key,
                    "title": title,
                    "message": message,
                },
                timeout=5,
            )
            resp.raise_for_status()
            logger.info("Notification sent: %s", title)
        except requests.RequestException as e:
            logger.error("Notification failed: %s", e)

    def alert(
        self,
        symbol: str,
        alert_type: str,
        title: str,
        message: str,
        persist: bool = True,
    ) -> None:
        full_message = f"{message}"
        self.send_pushover(title, full_message)
        if persist:
            database.insert_alert(symbol, alert_type, full_message)
