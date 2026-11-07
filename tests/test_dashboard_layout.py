"""The dashboard's layout decisions, checked against the shipped index.html.

These are product choices that are easy to undo by accident while editing
markup, so they are written down as tests.
"""

import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INDEX = open(os.path.join(ROOT, "frontend", "index.html"), encoding="utf-8").read()


def test_news_is_the_first_sidebar_tab_and_open_on_load():
    tabs = re.findall(r'<button class="sidebar-tab( active)?" data-tab="(\w+)"', INDEX)
    assert [name for _, name in tabs] == ["news", "indicators"]
    assert [name for active, name in tabs if active] == ["news"]
    # The news pane is visible at load and the indicators pane hidden, matching the tab.
    assert re.search(r'<div id="tab-news" class="tab-pane">', INDEX)
    assert re.search(r'<div id="tab-indicators" class="tab-pane" style="display:none">', INDEX)


def test_stylesheets_have_balanced_braces():
    # A lost "}" once put every Options page rule inside the screener's mobile
    # @media block: on desktop the quick-pick chips became unstyled white buttons.
    for name in ("styles.css", "tokens.css"):
        css = open(os.path.join(ROOT, "frontend", name), encoding="utf-8").read()
        css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
        depth = 0
        for ch in css:
            depth += (ch == "{") - (ch == "}")
            assert depth >= 0, f"{name}: a '}}' with no matching '{{'"
        assert depth == 0, f"{name}: {depth} unclosed '{{'"
