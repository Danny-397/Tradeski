"""Deterministic graders for Ski eval cases. No model is used to grade."""

import re


def grade(case: dict, response: dict) -> list[str]:
    """Return the list of failed checks (empty = pass)."""
    reply = response.get("reply") or ""
    tools = response.get("tools_used") or []
    failures = []

    if response.get("error"):
        return [f"error: {response['error']}"]

    if not reply.lstrip().lower().startswith("bottom line:"):
        failures.append("format: does not start with 'Bottom line:'")

    if response.get("grounded") is False:
        failures.append(f"grounding: figures not in the data {response.get('ungrounded_figures')}")

    wanted = case.get("tools_any")
    if wanted and not set(wanted) & set(tools):
        failures.append(f"tools: expected one of {wanted}, called {tools or 'none'}")

    pattern = case.get("must_match")
    if pattern and not re.search(pattern, reply, re.IGNORECASE):
        if not (case.get("or_web_search") and "web_search" in tools):
            failures.append(f"content: reply does not match /{pattern}/")

    banned = case.get("must_not")
    if banned and re.search(banned, reply, re.IGNORECASE):
        failures.append(f"content: reply matches banned /{banned}/")

    return failures
