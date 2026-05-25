import sys
import os

_root = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _root)
sys.path.insert(0, os.path.join(_root, "Plotly dashboard"))

from tracker import database  # noqa: E402
database.init_db()

from app import app, socketio, _background_tracker  # noqa: E402

socketio.start_background_task(_background_tracker)
