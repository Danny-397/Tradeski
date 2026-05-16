from tracker.notifier import Notifier
from tracker.config import PushoverConfig


def test_notifier_no_credentials():
    n = Notifier(PushoverConfig(user_key="", api_token=""))
    # Should not raise
    n.alert("AAPL", "test", "Test Title", "Test Message", persist=False)
