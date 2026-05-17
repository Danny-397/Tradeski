from unittest.mock import patch, MagicMock
from tracker.notifier import Notifier
from tracker.config import PushoverConfig


def test_notifier_sends_request():
    config = PushoverConfig(user_key="u", api_token="t")
    notifier = Notifier(config)

    with patch("requests.post") as mock_post:
        mock_response = MagicMock()
        mock_response.raise_for_status.return_value = None
        mock_post.return_value = mock_response

        notifier.send_pushover("Test", "Hello")

        mock_post.assert_called_once()
        args, kwargs = mock_post.call_args
        assert "messages.json" in args[0]
        assert kwargs["data"]["title"] == "Test"
        assert kwargs["data"]["message"] == "Hello"


def test_notifier_skips_without_credentials():
    config = PushoverConfig(user_key="", api_token="")
    notifier = Notifier(config)

    with patch("requests.post") as mock_post:
        notifier.send_pushover("Test", "Hello")
        mock_post.assert_not_called()
