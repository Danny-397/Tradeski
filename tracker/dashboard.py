# tracker/dashboard.py
# Starts the main dashboard server (defined in dashboard/app.py).

from dashboard.app import socketio, app
from .logger import get_logger

logger = get_logger(__name__)


def run_dashboard() -> None:
    """
    Run the main dashboard server.
    This wraps the Flask-SocketIO server defined in dashboard/app.py.
    """
    logger.info("Starting dashboard server on http://127.0.0.1:5000")
    socketio.run(app, host="127.0.0.1", port=5000, debug=False)
