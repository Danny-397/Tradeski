import sys
import os

_root = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _root)
sys.path.insert(0, os.path.join(_root, "Plotly dashboard"))

from app import app  # noqa: E402
