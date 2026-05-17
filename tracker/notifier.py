import requests

from . import database
from .config import PushoverConfig
from .logger import get_logger

logger = get_logger(__name__)


class Notifier:
    """
    Send notifications and optionally
    persist alerts to the database.
    """

    def __init__(
        self,
        pushover_config: PushoverConfig,
    ) -> None:
        """
        Initialize notifier.

        Args:
            pushover_config:
                Pushover credentials.
        """
        self.pushover_config = (
            pushover_config
        )

    def send_pushover(
        self,
        title: str,
        message: str,
    ) -> None:
        """
        Send a Pushover notification.

        Args:
            title:
                Notification title.
            message:
                Notification text.
        """
        credentials_missing = (
            not self.pushover_config.user_key
            or not self.pushover_config.api_token
        )

        if credentials_missing:
            logger.warning(
                "Pushover credentials "
                "not set; skipping "
                "notification."
            )
            return

        try:
            response = requests.post(
                (
                    "https://api.pushover.net/"
                    "1/messages.json"
                ),
                data={
                    "token": (
                        self.pushover_config
                        .api_token
                    ),
                    "user": (
                        self.pushover_config
                        .user_key
                    ),
                    "title": title,
                    "message": message,
                },
                timeout=5,
            )

            response.raise_for_status()

            logger.info(
                "Notification sent: %s",
                title,
            )

        except requests.RequestException as error:
            logger.error(
                "Notification failed: %s",
                error,
            )

    def alert(
        self,
        symbol: str,
        alert_type: str,
        title: str,
        message: str,
        persist: bool = True,
    ) -> None:
        """
        Send notification and
        optionally save alert.

        Args:
            symbol:
                Stock ticker symbol.
            alert_type:
                Alert category.
            title:
                Notification title.
            message:
                Notification body.
            persist:
                Whether to store
                the alert.
        """
        self.send_pushover(
            title,
            message,
        )

        if persist:
            database.insert_alert(
                symbol,
                alert_type,
                message,
            )
