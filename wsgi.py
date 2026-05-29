"""WSGI entry point for gunicorn / Render.com deployment."""

# Must be the very first thing — patches stdlib sockets before any other import
from gevent import monkey
monkey.patch_all()

import sys
import os

# Put "Plotly dashboard/" on sys.path before importing app.py so the local
# `cache` module is found regardless of the process working directory.
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "Plotly dashboard"))

from app import app  # noqa: E402
