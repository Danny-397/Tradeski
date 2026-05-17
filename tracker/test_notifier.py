from tracker.notifier import Notifier
from tracker.config import PushoverConfig


def test_notifier_no_credentials():
    config = PushoverConfig(
        user_key="",
        api_token=""
    )

    notifier = Notifier(config)

    # Should not raise an exception
    notifier.alert(
        "AAPL",
        "test",
        "Test Title",
        "Test Message",
        persist=False,
    )
