"""Yes/No permission for schedule changes that need it (fixed events, days off, clearing a day).

Calls go through permission.ask(...) at call time, so the app's popup (or a test) can replace it.
"""
from __future__ import annotations


def ask(action: str, target: str, detail: str = "") -> bool:
    from Tools.filesystem import ask_permission     # imported late: Tools imports Schedule too
    return ask_permission(action, target, detail)
