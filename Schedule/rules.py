"""The rules: what happens on a day, what is busy or free, and what conflicts."""
from __future__ import annotations

import uuid
from datetime import date, timedelta

from .timeparse import DAY_CODES, WEEKDAYS, _MONTHS, _WEEKDAY_NAMES, _fmt, _hhmm, _pretty_day, _to_date, _to_days, _to_min, _week_start


# --- the rules ----------------------------------------------------------------------
def _applies(ev: dict, day: date) -> bool:
    days = ev.get("days") or []
    if days:
        if DAY_CODES[day.weekday()] not in days:
            return False
        if ev.get("date") and day < date.fromisoformat(ev["date"]):
            return False
        if ev.get("until") and day > date.fromisoformat(ev["until"]):
            return False
        return True
    return ev.get("date") == day.isoformat()


def _is_school(ev: dict) -> bool:
    """School and everything that is cancelled with it (club, gym): skipped on days off."""
    title = str(ev.get("title", "")).strip().lower()
    return bool(ev.get("school")) or title == "school" or title.startswith(("club", "gym"))


def _off(data: dict, day: date) -> str:
    """The reason this day is a day off school ("" if it is a normal day)."""
    for item in data.get("days_off", []):
        if item["start"] <= day.isoformat() <= item.get("end", item["start"]):
            return item.get("title") or "No school"
    return ""


def _shows(data: dict, ev: dict, day: date) -> bool:
    """Does this event happen on this day? School does not happen on days off."""
    return _applies(ev, day) and not (_is_school(ev) and _off(data, day))


def _bumpable(ev: dict) -> bool:
    """A one-off flexible event can be moved aside by a priority goal (homework)."""
    return (ev.get("kind") != "fixed" and bool(ev.get("date")) and not ev.get("days") and not ev.get("priority")
            and not ev.get("task"))                       # deadline work is re-planned by Schedule/tasks.py


def _busy(data: dict, day: date, ignore: str | None = None, hard: bool = False,
          skip_tasks: bool = False) -> list[tuple[int, int, str]]:
    """hard=True leaves out the events a priority goal is allowed to move.
    skip_tasks=True leaves out automatically planned task sessions (they can be re-planned)."""
    out = []
    for ev in data["protected"] + data["events"]:
        if ignore and ev.get("id") == ignore:
            continue
        if hard and _bumpable(ev):
            continue
        if skip_tasks and ev.get("task") and ev.get("auto"):
            continue
        if _shows(data, ev, day):
            out.append((_to_min(ev["start"]), _to_min(ev["end"]), ev["title"]))
    return sorted(out)


def _free(data: dict, day: date, lo: int, hi: int, ignore: str | None = None,
          hard: bool = False) -> list[tuple[int, int]]:
    windows, cursor = [], lo
    for start, end, _ in _busy(data, day, ignore, hard):
        if cursor >= hi:
            break
        if start > cursor:
            windows.append((cursor, min(start, hi)))
        cursor = max(cursor, end)
    if cursor < hi:
        windows.append((cursor, hi))
    return windows


def _suggest(data: dict, day: date, length: int, ignore: str | None = None) -> str:
    fits = [(a, b) for a, b in _free(data, day, 0, 24 * 60, ignore) if b - a >= length]
    if not fits:
        return f"No free gap of {length} minutes on {_pretty_day(day)}."
    shown = ", ".join(f"{_fmt(a)}-{_fmt(b)}" for a, b in fits[:3])
    return f"Free on {_pretty_day(day)}: {shown}."


def _span(ev: dict) -> list[date]:
    if ev.get("days"):
        first = date.fromisoformat(ev["date"]) if ev.get("date") else date.today()
        last = first + timedelta(days=84)
        if ev.get("until"):
            last = min(last, date.fromisoformat(ev["until"]))
        return [first + timedelta(days=i) for i in range((last - first).days + 1)]
    return [date.fromisoformat(ev["date"])]


def _conflict(data: dict, ev: dict, ignore: str | None = None, skip_tasks: bool = False) -> str:
    start, end = _to_min(ev["start"]), _to_min(ev["end"])
    for day in _span(ev):
        if not _applies(ev, day):
            continue
        for b_start, b_end, title in _busy(data, day, ignore, skip_tasks=skip_tasks):
            if start < b_end and b_start < end:
                return (
                    f"conflicts with {title} ({_fmt(b_start)}-{_fmt(b_end)}) on "
                    f"{_pretty_day(day)}. {_suggest(data, day, end - start, ignore)}"
                )
    return ""


def _find(data: dict, key: str) -> dict | list[dict] | None:
    key = str(key).strip()
    for ev in data["events"]:
        if ev.get("id") == key:
            return ev
    matches = [ev for ev in data["events"] if ev["title"].lower() == key.lower()]
    if len(matches) == 1:
        return matches[0]
    return matches or None


def _describe(ev: dict) -> str:
    when = f"every {','.join(ev['days'])}" if ev.get("days") else ev.get("date", "")
    if ev.get("days") and ev.get("date"):
        when += f" from {ev['date']}"
    if ev.get("until"):
        when += f" until {ev['until']}"
    return f"{ev['title']} {_fmt(_to_min(ev['start']))}-{_fmt(_to_min(ev['end']))} ({when}) [{ev['id']}]"


def _new_id(data: dict) -> str:
    used = {ev.get("id") for ev in data["events"]}
    while True:
        new = uuid.uuid4().hex[:4]
        if new not in used:
            return new


def _task_overlaps(data: dict, ev: dict) -> list[dict]:
    """Automatically planned task sessions that this (new or changed) event would sit on top of."""
    start, end = _to_min(ev["start"]), _to_min(ev["end"])
    out = []
    for other in data["events"]:
        if not (other.get("task") and other.get("auto")) or other.get("id") == ev.get("id"):
            continue
        day = date.fromisoformat(other["date"])
        if _applies(ev, day) and start < _to_min(other["end"]) and _to_min(other["start"]) < end:
            out.append(other)
    return out
