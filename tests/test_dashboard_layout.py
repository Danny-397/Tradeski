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
