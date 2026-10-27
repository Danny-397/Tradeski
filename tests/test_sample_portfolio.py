"""The signed-out "sample portfolio" sent to Ski is browser input.

Like test_security_contract.py this reads app.py rather than importing it
(import starts a database and a background thread), then runs the parser on
its own.
"""

import ast
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SERVER = os.path.join(ROOT, "Plotly dashboard", "app.py")

with open(SERVER, encoding="utf-8") as fh:
    SOURCE = fh.read()
TREE = ast.parse(SOURCE)


def _load_parser():
    ns = {"re": re}
    for node in TREE.body:
        if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "_SAMPLE_MAX_HOLDINGS" for t in node.targets):
            exec(compile(ast.Module([node], []), SERVER, "exec"), ns)
        if isinstance(node, ast.FunctionDef) and node.name == "_parse_sample_portfolio":
            exec(compile(ast.Module([node], []), SERVER, "exec"), ns)
    return ns["_parse_sample_portfolio"]


parse = _load_parser()


def test_keeps_well_formed_rows():
    rows = parse([{"symbol": "aapl", "shares": 10, "avg_cost": 185},
                  {"symbol": "BRK-B", "shares": "2.5", "avg_cost": None}])
    assert rows == [{"symbol": "AAPL", "shares": 10.0, "avg_cost": 185.0},
                    {"symbol": "BRK-B", "shares": 2.5, "avg_cost": None}]


def test_drops_bad_rows_instead_of_failing():
    rows = parse([{"symbol": "<script>", "shares": 1},
                  {"symbol": "MSFT", "shares": -3},
                  {"symbol": "NVDA", "shares": "lots"},
                  {"symbol": "", "shares": 1},
                  "not a row",
                  {"symbol": "SPY", "shares": 1, "avg_cost": 0}])
    assert rows == [{"symbol": "SCRIPT", "shares": 1.0, "avg_cost": None}]


def test_rejects_non_lists_and_caps_size():
    assert parse(None) == [] and parse({"symbol": "AAPL"}) == [] and parse("AAPL") == []
    many = [{"symbol": "AAPL", "shares": 1}] * 50
    assert len(parse(many)) == 10


def test_chat_only_uses_the_sample_when_signed_out():
    chat = next(n for n in ast.walk(TREE) if isinstance(n, ast.FunctionDef) and n.name == "chat")
    src = ast.get_source_segment(SOURCE, chat)
    assert '_parse_sample_portfolio(data.get("sample_portfolio")) if user_id is None else None' in src
