"""Source-level guards for two security properties of app.py.

Like test_stream_contract.py, these read the source rather than importing app.py,
which starts a database and a background thread on import.

1. Rate limits must be keyed on the visitor, not the socket. On Render every
   request arrives from Render's proxy, so keying on get_remote_address alone
   put every visitor in one bucket: one person retrying a login locked out the
   whole site, and Ask Ski's hourly quota was shared by everyone.
2. Alert creation must validate its input. The alerts list renders symbol and
   type into HTML, and the endpoint used to store whatever it was sent.
"""

import ast
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SERVER = os.path.join(ROOT, "Plotly dashboard", "app.py")

with open(SERVER, encoding="utf-8") as fh:
    SOURCE = fh.read()
TREE = ast.parse(SOURCE)


def _function(name: str) -> ast.FunctionDef:
    for node in ast.walk(TREE):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"{name} not found in app.py")


def test_limiter_is_keyed_on_the_client_ip():
    limiter = next(
        node.value for node in ast.walk(TREE)
        if isinstance(node, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == "limiter" for t in node.targets)
    )
    key = next(kw.value for kw in limiter.keywords if kw.arg == "key_func")
    assert isinstance(key, ast.Name) and key.id != "get_remote_address", (
        "Limiter keyed on get_remote_address: behind Render's proxy that is one "
        "bucket for every visitor"
    )
    body = ast.get_source_segment(SOURCE, _function(key.id))
    assert "CF-Connecting-IP" in body


def test_alert_creation_validates_type_and_symbol():
    body = ast.get_source_segment(SOURCE, _function("create_alert"))
    assert "_ALERT_TYPES" in body, "alert_type is stored without checking it"
    assert "_clean_symbol(" in body, "symbol is stored without sanitizing it"


def test_symbol_sanitizer_only_keeps_ticker_characters():
    """Every stored symbol goes through _clean_symbol, which must allow nothing
    beyond letters, digits, '.' and '-' (the hyphen is for BRK-B)."""
    body = ast.get_source_segment(SOURCE, _function("_clean_symbol"))
    assert 're.sub(r"[^A-Z0-9.\\-]", ""' in body
    for route in ("add_holding_route", "create_alert", "chat"):
        assert "_clean_symbol(" in ast.get_source_segment(SOURCE, _function(route)), route
