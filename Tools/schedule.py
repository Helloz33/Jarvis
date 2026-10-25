"""Schedule: fixed commitments, protected time, study goals and a planner.

The schedule is plain data in Schedule_data/schedule.json (gitignored, and easy
to edit by hand). All the rules live here in code, not in the AI model:

  * fixed events (school, club, gym...) are locked: changing them asks you first
  * protected time (sleep, dinner) can never be scheduled over
  * flexible events can be added, moved and deleted freely, but never overlap
    anything else; a conflict comes back with free times so the model can retry
  * goals ("Physics 2 h per week") are placed into real free time by plan_week
"""
from __future__ import annotations

import copy
import json
import math
import os
import re
import threading
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path

from .filesystem import ask_permission

DATA_DIR = Path(__file__).resolve().parent.parent / "Schedule_data"
SCHEDULE_FILE = DATA_DIR / "schedule.json"

DAY_CODES = ["MO", "TU", "WE", "TH", "FR", "SA", "SU"]   # index = date.weekday()
WEEKDAYS = DAY_CODES[:5]

_lock = threading.RLock()

# First run writes this generic starting point to Schedule_data/schedule.json
# (gitignored, so your real schedule never reaches GitHub). Edit that file, or
# just tell Jarvis your classes and commitments.
DEFAULT: dict = {
    "settings": {
        "study_window": {"weekday": ["16:00", "21:30"], "weekend": ["09:00", "21:30"]},
        "session_minutes": 60,
        "reminders": {"lead_minutes": 15, "quiet_until": {}},
    },
    "protected": [
        {"title": "Sleep", "days": DAY_CODES, "start": "00:00", "end": "06:30"},
        {"title": "Sleep", "days": DAY_CODES, "start": "23:00", "end": "24:00"},
        {"title": "Dinner", "days": DAY_CODES, "start": "18:00", "end": "18:45"},
    ],
    "goals": [],
    "events": [],
    "days_off": [],      # e.g. {"start": "2026-11-26", "end": "2026-11-27", "title": "Thanksgiving"}
}


# --- parsing and formatting -----------------------------------------------------
def _to_min(text) -> int:
    t = str(text).strip().lower().replace(".", "")
    if t == "noon":
        return 12 * 60
    m = re.fullmatch(r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)?", t)
    if not m:
        raise ValueError(f"could not read the time '{text}'; use a form like 15:00 or 3:30 pm")
    hour, minute, ampm = int(m.group(1)), int(m.group(2) or 0), m.group(3)
    if ampm:
        if not 1 <= hour <= 12:
            raise ValueError(f"could not read the time '{text}'")
        hour = hour % 12 + (12 if ampm == "pm" else 0)
    if hour == 24 and minute == 0 and not ampm:
        return 24 * 60
    if hour > 23 or minute > 59:
        raise ValueError(f"could not read the time '{text}'")
    return hour * 60 + minute


def _fmt(minutes: int) -> str:
    hour, minute = divmod(minutes, 60)
    hour %= 24
    return f"{hour % 12 or 12}:{minute:02d} {'AM' if hour < 12 else 'PM'}"


def _hhmm(minutes: int) -> str:
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


_WEEKDAY_NAMES = {
    "mon": 0, "monday": 0, "tue": 1, "tues": 1, "tuesday": 1, "wed": 2, "wednesday": 2,
    "thu": 3, "thur": 3, "thurs": 3, "thursday": 3, "fri": 4, "friday": 4,
    "sat": 5, "saturday": 5, "sun": 6, "sunday": 6,
}


def _to_date(text, today: date | None = None) -> date:
    today = today or date.today()
    t = str(text).strip().lower()
    if t in ("", "today"):
        return today
    if t == "tomorrow":
        return today + timedelta(days=1)
    if t == "yesterday":
        return today - timedelta(days=1)
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", t):
        return date.fromisoformat(t)
    nxt = t.startswith("next ")
    name = t.removeprefix("next ").removeprefix("this ").strip()
    if name in _WEEKDAY_NAMES:
        delta = (_WEEKDAY_NAMES[name] - today.weekday()) % 7
        if nxt and delta == 0:
            delta = 7
        return today + timedelta(days=delta)
    raise ValueError(f"could not read the date '{text}'; use YYYY-MM-DD, today, tomorrow or a weekday")


def _to_days(text) -> list[str]:
    if isinstance(text, (list, tuple)):
        text = ",".join(str(x) for x in text)
    t = str(text or "").strip().lower()
    if not t or t in ("none", "no", "never", "once", "one-off", "one off", "n/a", "null"):
        return []
    if t in ("daily", "everyday", "every day", "all"):
        return DAY_CODES[:]
    if t in ("weekdays", "weekday"):
        return WEEKDAYS[:]
    if t in ("weekends", "weekend"):
        return ["SA", "SU"]
    out: list[str] = []
    for part in re.split(r"[,/;&\s]+|\band\b", t):
        if not part:
            continue
        code = part[:2].upper()
        if code not in DAY_CODES:
            raise ValueError(f"could not read the day '{part}'; use names like mon,wed,fri")
        if code not in out:
            out.append(code)
    return out


def _pretty_day(day: date) -> str:
    return f"{day:%a %b} {day.day}"


# --- storage ---------------------------------------------------------------------
def _save(data: dict) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = SCHEDULE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    os.replace(tmp, SCHEDULE_FILE)


def _load() -> dict:
    with _lock:
        if not SCHEDULE_FILE.exists():
            data = copy.deepcopy(DEFAULT)
            _save(data)
            return data
        try:
            data = json.loads(SCHEDULE_FILE.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise RuntimeError(f"the schedule file is unreadable ({exc}); fix or delete {SCHEDULE_FILE}")
        for key, value in DEFAULT.items():
            data.setdefault(key, copy.deepcopy(value))
        return data


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
    return ev.get("kind") != "fixed" and bool(ev.get("date")) and not ev.get("days") and not ev.get("priority")


def _busy(data: dict, day: date, ignore: str | None = None, hard: bool = False) -> list[tuple[int, int, str]]:
    """hard=True leaves out the events a priority goal is allowed to move."""
    out = []
    for ev in data["protected"] + data["events"]:
        if ignore and ev.get("id") == ignore:
            continue
        if hard and _bumpable(ev):
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


def _conflict(data: dict, ev: dict, ignore: str | None = None) -> str:
    start, end = _to_min(ev["start"]), _to_min(ev["end"])
    for day in _span(ev):
        if not _applies(ev, day):
            continue
        for b_start, b_end, title in _busy(data, day, ignore):
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


def _week_start(d: date) -> date:
    """Weeks run Sunday to Saturday."""
    return d - timedelta(days=(d.weekday() + 1) % 7)


# --- read-only view for the UI -------------------------------------------------------
def week_view(start_date: str = "") -> dict:
    """The week containing start_date (default: this week) as plain data for the SCHEDULE tab."""
    try:
        data = _load()
        anchor = _to_date(start_date) if start_date else date.today()
    except (ValueError, RuntimeError) as exc:
        return {"error": str(exc)}
    monday = _week_start(anchor)
    days = []
    for i in range(7):
        day = monday + timedelta(days=i)
        items = sorted((ev for ev in data["events"] if _shows(data, ev, day)),
                       key=lambda ev: _to_min(ev["start"]))
        days.append({
            "date": day.isoformat(),
            "label": day.strftime("%a %d").upper(),
            "today": day == date.today(),
            "off": _off(data, day),
            "protected": [{"title": ev["title"], "start": _hhmm(_to_min(ev["start"])),
                           "end": _hhmm(_to_min(ev["end"]))}
                          for ev in data["protected"] if _applies(ev, day)],
            "events": [{"id": ev["id"], "title": ev["title"], "kind": ev.get("kind", "flexible"),
                        "start": _hhmm(_to_min(ev["start"])), "end": _hhmm(_to_min(ev["end"]))}
                       for ev in items],
        })
    goals = [{"title": g.get("title", ""), "minutes": g.get("minutes", 0), "per": g.get("per", "week")}
             for g in data.get("goals", [])]
    return {"start": monday.isoformat(), "days": days, "goals": goals}


# --- tools the model can call ----------------------------------------------------------
def list_schedule(start_date: str = "", end_date: str = "") -> str:
    """Events for a day (default today) or a range of up to 14 days."""
    try:
        data = _load()
        first = _to_date(start_date) if start_date else date.today()
        last = _to_date(end_date) if end_date else first
    except (ValueError, RuntimeError) as exc:
        return f"Error: {exc}"
    if last < first:
        first, last = last, first
    last = min(last, first + timedelta(days=13))

    lines = []
    for i in range((last - first).days + 1):
        day = first + timedelta(days=i)
        items = sorted(
            (ev for ev in data["events"] if _shows(data, ev, day)),
            key=lambda ev: _to_min(ev["start"]),
        )
        off = _off(data, day)
        note = f" [DAY OFF: {off}]" if off else ""
        if not items:
            lines.append(f"{_pretty_day(day)}{note}: nothing scheduled")
            continue
        parts = [
            f"{_fmt(_to_min(ev['start']))}-{_fmt(_to_min(ev['end']))} {ev['title']}"
            f"{' (fixed)' if ev.get('kind') == 'fixed' else ''} [{ev['id']}]"
            for ev in items
        ]
        lines.append(f"{_pretty_day(day)}{note}: " + "; ".join(parts))
    return "\n".join(lines)


def add_event(
    title: str,
    start: str,
    end: str = "",
    date: str = "",          # noqa: A002 - this is the tool's argument name
    repeat_days: str = "",
    kind: str = "flexible",
    until: str = "",
    duration_minutes: int = 0,
) -> str:
    """Add an event. One-off: give date (default today). Repeating: give repeat_days like
    'mon,wed,fri'. Give end, or duration_minutes instead."""
    try:
        data = _load()
        title = " ".join(str(title).split())
        if not title:
            return "Error: the event needs a title."
        kind = str(kind or "flexible").strip().lower()
        if kind not in ("fixed", "flexible"):
            kind = "flexible"      # a small model may say "study", "personal"... that is not fixed
        s_min = _to_min(start)
        try:
            duration = int(duration_minutes or 0)
        except (TypeError, ValueError):
            duration = 0
        if not str(end or "").strip():
            if duration <= 0:
                return "Error: give an end time, or duration_minutes."
            e_min = s_min + duration
        else:
            m = re.fullmatch(r"\s*(?:(an?|one|\d+(?:\.\d+)?)\s*(hours?|hrs?|h|minutes?|mins?|m))\s*", str(end).lower())
            if m:       # "1 hour" / "90 minutes" instead of a clock time
                n = 1.0 if m.group(1) in ("a", "an", "one") else float(m.group(1))
                e_min = s_min + int(n * (60 if m.group(2).startswith("h") else 1))
            else:
                e_min = _to_min(end)
        if e_min <= s_min:
            return "Error: the end time must be after the start time (events cannot pass midnight)."
        days = _to_days(repeat_days)
        ev: dict = {"id": _new_id(data), "title": title, "kind": kind,
                    "start": _hhmm(s_min), "end": _hhmm(e_min)}
        if days:
            ev["days"] = days
            if date:
                ev["date"] = _to_date(date).isoformat()
        else:
            ev["date"] = _to_date(date or "today").isoformat()
        if until:
            ev["until"] = _to_date(until).isoformat()

        with _lock:
            problem = _conflict(data, ev)
            if problem:
                return f"Error: that {problem}"
            if kind == "fixed" and not ask_permission("add a fixed event", title, _describe(ev)):
                return f"Add cancelled: you declined the fixed event {title}."
            data["events"].append(ev)
            _save(data)
        return f"Added {kind} event: {_describe(ev)}"
    except (ValueError, RuntimeError) as exc:
        return f"Error: {exc}"


def update_event(
    event_id: str,
    title: str = "",
    date: str = "",          # noqa: A002
    start: str = "",
    end: str = "",
    repeat_days: str = "",
    until: str = "",
) -> str:
    """Change an event (id from list_schedule, or its exact title). Only pass what changes."""
    try:
        data = _load()
        with _lock:
            found = _find(data, event_id)
            if found is None:
                return f"Error: no event with id or title '{event_id}'. Use list_schedule to see ids."
            if isinstance(found, list):
                ids = ", ".join(f"{e['title']} [{e['id']}]" for e in found)
                return f"Error: several events match; use one of these ids: {ids}"
            ev = copy.deepcopy(found)
            if title:
                ev["title"] = " ".join(str(title).split())
            if start:
                ev["start"] = _hhmm(_to_min(start))
            if end:
                ev["end"] = _hhmm(_to_min(end))
            if repeat_days:
                ev["days"] = _to_days(repeat_days)
            if date:
                ev["date"] = _to_date(date).isoformat()
            if until:
                ev["until"] = _to_date(until).isoformat()
            if _to_min(ev["end"]) <= _to_min(ev["start"]):
                return "Error: the end time must be after the start time."
            if not ev.get("days") and not ev.get("date"):
                return "Error: a one-off event needs a date."
            problem = _conflict(data, ev, ignore=ev["id"])
            if problem:
                return f"Error: that {problem}"
            if found.get("kind") == "fixed" and not ask_permission(
                "change a fixed event", found["title"], f"now: {_describe(found)}\nnew: {_describe(ev)}"
            ):
                return f"Change cancelled: you declined to change {found['title']}."
            found.clear()
            found.update(ev)
            found.pop("auto", None)      # a hand-edited event is no longer replanned
            _save(data)
        return f"Updated: {_describe(ev)}"
    except (ValueError, RuntimeError) as exc:
        return f"Error: {exc}"


def delete_event(event_id: str) -> str:
    """Delete an event by id (from list_schedule) or exact title."""
    try:
        data = _load()
        with _lock:
            found = _find(data, event_id)
            if found is None:
                return f"Error: no event with id or title '{event_id}'. Use list_schedule to see ids."
            if isinstance(found, list):
                ids = ", ".join(f"{e['title']} [{e['id']}]" for e in found)
                return f"Error: several events match; use one of these ids: {ids}"
            if found.get("kind") == "fixed" and not ask_permission(
                "delete a fixed event", found["title"], _describe(found)
            ):
                return f"Deletion cancelled: you declined to delete {found['title']}."
            data["events"].remove(found)
            _save(data)
        return f"Deleted event: {_describe(found)}"
    except (ValueError, RuntimeError) as exc:
        return f"Error: {exc}"


def set_goal(title: str, minutes: int, per: str = "week", session_minutes: int = 0, days: str = "",
             buffer_minutes: int = 0) -> str:
    """Set a study/time goal, e.g. Homework 120 minutes per day, Physics 120 per week.
    minutes=0 removes the goal. buffer_minutes>0 starts it that long after the day's last fixed
    commitment (e.g. homework 30 minutes after you get back from the gym).
    Run plan_week afterwards to place it."""
    try:
        data = _load()
        title = " ".join(str(title).split())
        if not title:
            return "Error: the goal needs a title."
        minutes = int(minutes)
        per = str(per or "week").strip().lower()
        if per not in ("day", "week"):
            return "Error: per must be 'day' or 'week'."
        with _lock:
            old = next((g for g in data["goals"] if g["title"].lower() == title.lower()), {})
            data["goals"] = [g for g in data["goals"] if g["title"].lower() != title.lower()]
            if minutes <= 0:
                _save(data)
                return f"Removed the goal {title}."
            goal = {"title": title, "minutes": minutes, "per": per,
                    "days": _to_days(days) or old.get("days", []),
                    "session_minutes": int(session_minutes) or min(minutes, 60)}
            if old.get("overrides"):
                goal["overrides"] = old["overrides"]
            if old.get("priority") or title.lower() in ("homework", "hw"):
                goal["priority"] = True          # homework may move other flexible events
            if old.get("buffer_minutes") and not int(buffer_minutes or 0):
                goal["buffer_minutes"] = old["buffer_minutes"]
            if int(buffer_minutes or 0) > 0:
                goal["buffer_minutes"] = int(buffer_minutes)
            data["goals"].append(goal)
            _save(data)
        return (f"Goal set: {title}, {minutes} minutes per {per}"
                f"{' on ' + ','.join(goal['days']) if goal['days'] else ''}"
                f"{', starting ' + str(goal['buffer_minutes']) + ' min after your last commitment' if goal.get('buffer_minutes') else ''}. "
                "Run plan_week to put it in the schedule.")
    except (ValueError, TypeError, RuntimeError) as exc:
        return f"Error: {exc}"


def plan_week(start_date: str = "") -> str:
    """Place every goal into free time for the week containing start_date (default this week).
    Re-running replaces the earlier automatic plan for that week (hand-made events stay).
    Priority goals (homework) go first and may move other flexible, one-off events to another
    day; fixed commitments never move."""
    try:
        data = _load()
        today = date.today()
        anchor = _to_date(start_date) if start_date else today
    except (ValueError, RuntimeError) as exc:
        return f"Error: {exc}"

    monday = _week_start(anchor)
    week = [monday + timedelta(days=i) for i in range(7)]
    now = datetime.now()
    now_min = math.ceil((now.hour * 60 + now.minute) / 15) * 15

    with _lock:
        # Drop the previous automatic plan for the days that can still change.
        data["events"] = [
            ev for ev in data["events"]
            if not (ev.get("auto") and ev.get("date")
                    and monday <= date.fromisoformat(ev["date"]) <= week[-1]
                    and date.fromisoformat(ev["date"]) >= today)
        ]
        windows = data["settings"]["study_window"]
        default_session = int(data["settings"].get("session_minutes", 60))
        placed: dict[date, list[str]] = {}
        load: dict[date, int] = {}
        unmet: list[str] = []
        bumped: list[dict] = []
        moved: list[str] = []

        def window(day: date) -> tuple[int, int]:
            key = "weekend" if (day.weekday() >= 5 or _off(data, day)) else "weekday"
            lo, hi = (_to_min(x) for x in windows[key])
            if day == today:
                lo = max(lo, now_min)
            return lo, hi

        def place(day: date, goal: dict, minutes: int, partial: bool = False) -> int:
            """Put a session on this day. Returns the minutes placed (0 = no room).
            With partial=True it may use a shorter gap (30 minutes or more)."""
            lo, hi = window(day)
            gap = int(goal.get("buffer_minutes") or 0)
            if gap:
                ends = [_to_min(ev["end"]) for ev in data["events"]
                        if ev.get("kind") == "fixed" and _shows(data, ev, day)]
                if ends:
                    lo = max(lo, max(ends) + gap)
                if day == today:
                    lo = max(lo, now_min)
            priority = bool(goal.get("priority"))
            gaps = _free(data, day, lo, hi, hard=priority)
            fits = [(a, b) for a, b in gaps if b - a >= minutes]
            if gap:
                # Start right at the buffer, even if dinner splits the session in two.
                early = [(a, b) for a, b in gaps if b - a >= min(30, minutes)]
                if not early:
                    return 0
                a = early[0][0]
                length = min(minutes, early[0][1] - a)
            elif fits:
                a, length = fits[0][0], minutes
            elif partial:
                big = [(a, b) for a, b in gaps if b - a >= min(30, minutes)]
                if not big:
                    return 0
                a, b = max(big, key=lambda g: g[1] - g[0])
                length = min(minutes, b - a)
            else:
                return 0
            piece = {"id": _new_id(data), "title": goal["title"], "kind": "flexible",
                     "date": day.isoformat(), "start": _hhmm(a), "end": _hhmm(a + length),
                     "auto": True}
            if priority:
                piece["priority"] = True
                for other in [e for e in data["events"] if _bumpable(e) and e["date"] == day.isoformat()
                              and _to_min(e["start"]) < a + length and a < _to_min(e["end"])]:
                    data["events"].remove(other)         # moved to another day below
                    bumped.append(other)
            data["events"].append(piece)
            placed.setdefault(day, []).append(f"{goal['title']} {_fmt(a)}-{_fmt(a + length)}")
            load[day] = load.get(day, 0) + length
            return length

        def run_goal(goal: dict) -> None:
            session = int(goal.get("session_minutes") or default_session)
            allowed = goal.get("days") or []
            floor = min(30, int(goal["minutes"]))       # ignore leftovers smaller than this
            days = [d for d in week if d >= today and (not allowed or DAY_CODES[d.weekday()] in allowed)]

            if goal.get("per") == "day":
                for day in days:
                    need = int(goal.get("overrides", {}).get(day.isoformat(), goal["minutes"]))
                    floor_d = min(30, need)
                    while need > 0 and need >= floor_d:
                        want = need if goal.get("priority") else min(session, need)
                        got = place(day, goal, want, partial=True)
                        if not got:
                            unmet.append(f"{goal['title']} on {_pretty_day(day)}: {need} min")
                            break
                        need -= got
            else:
                need = int(goal["minutes"])
                used: dict[date, int] = {}
                while need >= floor:
                    chunk = min(session, need)
                    order = sorted(days, key=lambda d: (used.get(d, 0), load.get(d, 0), d))
                    got = 0
                    for partial in (False, True):        # full sessions first, then shorter ones
                        for d in order:
                            got = place(d, goal, chunk, partial=partial)
                            if got:
                                used[d] = used.get(d, 0) + 1
                                break
                        if got:
                            break
                    if not got:
                        unmet.append(f"{goal['title']}: {need} min left over")
                        break
                    need -= got

        def reflow(ev: dict) -> None:
            """Give a moved event a new slot, the same day if possible, else a later day."""
            length = _to_min(ev["end"]) - _to_min(ev["start"])
            first = date.fromisoformat(ev["date"])
            for offset in range(0, 8):
                day = first + timedelta(days=offset)
                if day < today:
                    continue
                lo, hi = window(day)
                fit = [(a, b) for a, b in _free(data, day, lo, hi) if b - a >= length]
                if fit:
                    a = fit[0][0]
                    new = dict(ev, date=day.isoformat(), start=_hhmm(a), end=_hhmm(a + length))
                    data["events"].append(new)
                    moved.append(f"{ev['title']} from {_pretty_day(first)} {_fmt(_to_min(ev['start']))} "
                                 f"to {_pretty_day(day)} {_fmt(a)}")
                    return
            data["events"].append(ev)                    # no room anywhere: leave it as it was
            unmet.append(f"{ev['title']} could not be moved and now overlaps homework")

        goals = sorted(data["goals"], key=lambda g: (not g.get("priority"), g.get("per") != "day"))
        for goal in [g for g in goals if g.get("priority")]:
            run_goal(goal)
        for ev in sorted(bumped, key=lambda e: (e["date"], e["start"])):
            reflow(ev)
        for goal in [g for g in goals if not g.get("priority")]:
            run_goal(goal)
        _save(data)

    if not placed and not unmet and not moved:
        return "Nothing to plan: there are no goals for the days left in that week."
    lines = [f"Planned the week of {_pretty_day(monday)}:"]
    for day in sorted(placed):
        lines.append(f"{_pretty_day(day)}: " + "; ".join(placed[day]))
    if moved:
        lines.append("Moved to make room for homework: " + "; ".join(moved))
    if unmet:
        lines.append("Could not fit: " + "; ".join(unmet))
    return "\n".join(lines)


def adjust_homework(minutes: int, date: str = "today") -> str:
    """Change how much homework there is on ONE day (e.g. 'I have 3 hours of homework on
    Thursday' = 180, 'no homework Friday' = 0). The week is re-planned straight away; homework
    has priority, so other flexible events that are in the way move to another day by themselves."""
    try:
        data = _load()
        day = _to_date(date or "today")
        minutes = int(minutes)
        if minutes < 0 or minutes > 12 * 60:
            return "Error: minutes must be between 0 and 720."
        with _lock:
            goal = next((g for g in data["goals"] if g["title"].lower() in ("homework", "hw")), None)
            if goal is None:
                return "Error: there is no Homework goal yet. Set one with set_goal (title Homework, per day)."
            goal.setdefault("overrides", {})[day.isoformat()] = minutes
            for key in [k for k in goal["overrides"] if k < (datetime.now().date() - timedelta(days=14)).isoformat()]:
                del goal["overrides"][key]            # forget old one-day changes
            _save(data)
    except (ValueError, TypeError, RuntimeError) as exc:
        return f"Error: {exc}"
    plan = plan_week(day.isoformat())
    head = f"Homework on {_pretty_day(day)} is now {minutes} minutes." if minutes else \
           f"No homework planned on {_pretty_day(day)}."
    return head + "\n" + plan


# --- reminders ---------------------------------------------------------------------------
def due_reminders(now: datetime | None = None) -> list[dict]:
    """Reminders that should be delivered right now (the caller remembers which it already sent).
    Events with "remind": false (school, club, gym) are skipped. quiet_until (per weekday) holds
    spoken reminders back: an event that starts after quiet hours end is announced when they end;
    one that starts inside quiet hours only gets a silent notification."""
    try:
        data = _load()
    except RuntimeError:
        return []
    now = now or datetime.now()
    day, nm = now.date(), now.hour * 60 + now.minute
    cfg = data["settings"].get("reminders", {})
    lead = int(cfg.get("lead_minutes", 15))
    quiet_s = (cfg.get("quiet_until") or {}).get(DAY_CODES[day.weekday()])
    quiet = _to_min(quiet_s) if quiet_s else 0
    out = []
    for ev in data["events"]:
        if ev.get("remind") is False or not _shows(data, ev, day):
            continue
        start = _to_min(ev["start"])
        quiet_event = start < quiet
        at = start - lead
        if not quiet_event:
            at = max(at, quiet)
        if at <= nm <= start + 10:
            out.append({"key": f"{day.isoformat()}|{ev['id']}|{ev['start']}", "title": ev["title"],
                        "start": _fmt(start), "quiet": quiet_event,
                        "text": f"Sir, we have {ev['title']} scheduled for {_fmt(start)}."})
    return out


def set_day_off(start_date: str, end_date: str = "", title: str = "No school", remove: bool = False) -> str:
    """Mark a day (or a range) as a day off school, e.g. a holiday or teacher in-service day.
    School is skipped on those days and study time may start earlier. remove=True undoes it.
    Run plan_week afterwards to re-plan the week."""
    try:
        data = _load()
        first = _to_date(start_date)
        last = _to_date(end_date) if end_date else first
    except (ValueError, RuntimeError) as exc:
        return f"Error: {exc}"
    if last < first:
        first, last = last, first
    if (last - first).days > 60:
        return "Error: a day off can last at most 60 days."
    span = f"{_pretty_day(first)}" + (f" to {_pretty_day(last)}" if last != first else "")

    if remove:
        keep = [d for d in data["days_off"]
                if not (d["start"] <= last.isoformat() and first.isoformat() <= d.get("end", d["start"]))]
        if len(keep) == len(data["days_off"]):
            return f"There is no day off on {span}."
        if not ask_permission("remove day off", span, "School will count on these days again."):
            return "Cancelled by the user. Do not retry."
        with _lock:
            data["days_off"] = keep
            _save(data)
        return f"Removed the day off on {span}. Run plan_week to re-plan."

    if not ask_permission("add day off", span, f"{' '.join(str(title).split()) or 'No school'}: school is skipped on these days."):
        return "Cancelled by the user. Do not retry."
    with _lock:
        data["days_off"].append({"start": first.isoformat(), "end": last.isoformat(),
                                 "title": " ".join(str(title).split()) or "No school"})
        data["days_off"].sort(key=lambda d: d["start"])
        _save(data)
    return f"Marked {span} as a day off ({title}). Run plan_week to re-plan."


# --- a deterministic shortcut for plain "add ..." requests ---------------------------------
# A small local model sometimes talks about adding an event without calling add_event. For the
# common spoken forms ("add an hour of physics at 2 pm", "set a physics session for 3 to 4 pm")
# the request is parsed here instead, so it always works and is fast.
_INTENT = re.compile(r"\b(add|schedule|set|book|put|create|block|slot|pencil)\b", re.I)
_QUESTION = re.compile(r"^\s*(?:(?:hey|ok|okay|so|and|jarvis|well|yes|yeah)[ ,]+)*"
                       r"(what|when|where|why|how|which|who|did|does|do|is|are)\b", re.I)
_MER = r"(a\.?\s?m\.?|p\.?\s?m\.?)"
_RANGE = re.compile(rf"(\d{{1,2}})(?::(\d\d))?\s*{_MER}?\s*(?:to|until|till|through|-)\s*(\d{{1,2}})(?::(\d\d))?\s*{_MER}?", re.I)
_AT = re.compile(rf"(?:\bat\b|@|\bfrom\b)\s*(\d{{1,2}})(?::(\d\d))?\s*{_MER}?|\b(\d{{1,2}})(?::(\d\d))?\s*{_MER}", re.I)
_DUR = re.compile(r"\b(half an? hour|(?:an?|one|\d+(?:\.\d+)?)[ -]?(?:hours?|hrs?|minutes?|mins?))\b(?:\s+of)?", re.I)
_DAYWORD = re.compile(r"\b(today|tonight|tomorrow|(?:on |this |next )?(?:mon|tues?|wed(?:nes)?|thu(?:rs?)?|fri|sat(?:ur)?|sun)(?:day)?)\b", re.I)
_FILL = {"a", "an", "the", "to", "my", "please", "can", "could", "you", "also", "first", "for", "from",
         "at", "on", "in", "into", "me", "jarvis", "hey", "ok", "okay", "so", "and", "then", "it",
         "that", "this", "of", "schedule", "calendar", "new", "yes", "yeah", "thanks", "thank", "now",
         "another", "one", "other", "again", "more", "second", "third", "also"}


def _clock(h: str, m: str | None, mer: str | None) -> int:
    """Clock time in minutes. With no am/pm: 6-11 means the next one still ahead today
    (so 'at 7' at 6:30 AM is 7 AM, at 5 PM it is 7 PM); 1-5 is PM; 12 is noon."""
    hour, minute = int(h), int(m or 0)
    if hour >= 13 or hour == 0:
        return hour * 60 + minute                       # already a 24-hour time
    if mer:
        pm = mer.lower().replace(".", "").replace(" ", "").startswith("p")
        return (hour % 12 + (12 if pm else 0)) * 60 + minute
    if hour == 12:
        return 12 * 60 + minute
    now = datetime.now()
    am_ahead = 6 <= hour <= 11 and hour * 60 + minute > now.hour * 60 + now.minute
    return (hour if am_ahead else hour + 12) * 60 + minute


def _dur_minutes(t: str) -> int | None:
    """'a 30-minute session' / 'an hour of' / 'half an hour' -> minutes."""
    dur = _DUR.search(t)
    if not dur:
        return None
    w = dur.group(1).lower()
    if w.startswith("half"):
        return 30
    n = 1.0 if w.split()[0] in ("a", "an", "one") else float(re.match(r"[\d.]+", w).group())
    return int(n * (1 if "min" in w else 60))


def parse_add_request(text: str, previous: str = "") -> dict | None:
    """Turn 'add an hour of physics at 2 pm today' into add_event arguments, or None
    if the sentence is not a clear add request. previous = the user's message before this one,
    used when the intent and the details were said in separate sentences."""
    for raw in (text, f"{previous} {text}".strip() if previous else ""):
        if not raw:
            continue
        if _QUESTION.search(raw if raw is text else text):
            continue
        t = " ".join(raw.replace(",", " ").split())
        t = re.sub(r"\b(?:to|in|on|into|from)?\s*(?:the|my|our)\s+(?:schedule|calendar)\b", " ", t, flags=re.I)
        if not _INTENT.search(t):
            continue
        span = _RANGE.search(t)
        start = end = None
        if span:
            h1, m1, a1, h2, m2, a2 = span.groups()
            if a1 or a2:
                s = _clock(h1, m1, a1 or a2)
                e = _clock(h2, m2, a2 or a1)
                if e <= s and not a1:
                    s -= 12 * 60 if s >= 12 * 60 else 0
            else:
                s, e = _clock(h1, m1, None), _clock(h2, m2, None)
                if e <= s:
                    e += 12 * 60 if e < 12 * 60 else 0
            length = _dur_minutes(t)
            if length and not (0 <= s < e <= 24 * 60 and e - s <= 12 * 60):
                e = s + length        # the spoken end time was garbled; trust "a 30-minute session"
            if not (0 <= s < e <= 24 * 60):
                continue
            start, end = s, e
            cut = span
        else:
            at = None
            for at in _AT.finditer(t):
                pass                     # the last time mentioned
            if not at:
                continue
            g = at.groups()
            h, m, mer = (g[0], g[1], g[2]) if g[0] else (g[3], g[4], g[5])
            start = _clock(h, m, mer)
            minutes = _dur_minutes(t) or 60
            end = start + minutes
            if end > 24 * 60:
                continue
            cut = at

        before = t[:cut.start()]
        after = t[cut.end():]
        verbs = list(_INTENT.finditer(before))
        title_src = before[verbs[-1].end():] if verbs else before
        if not re.sub(r"[^a-z]", "", _DUR.sub("", title_src).lower().replace("jarvis", "")):
            title_src = after
        title_src = _DUR.sub(" ", title_src)
        day = _DAYWORD.search(t)
        title_src = _DAYWORD.sub(" ", title_src)
        title_src = re.sub(r"\bto (the|my) schedule\b", " ", title_src, flags=re.I)
        title_src = re.sub(r"\bfor an? (study|practice|prep|review)\b", r"\1", title_src, flags=re.I)
        words = [w for w in re.findall(r"[A-Za-z][A-Za-z'+&-]*", title_src)]
        while words and words[0].lower() in _FILL:
            words.pop(0)
        while words and words[-1].lower() in _FILL:
            words.pop()
        if not words or len(words) > 6:
            continue
        title = " ".join(words)
        title = title[0].upper() + title[1:]
        dayword = day.group(1).lower().replace("tonight", "today") if day else "today"
        dayword = re.sub(r"^(on|this|next) ", "", dayword)
        return {"title": title, "start": _hhmm(start), "end": _hhmm(end), "date": dayword}
    return None


_RENAME = re.compile(r"\b(rename|name|call|label|title|retitle)\b", re.I)


def find_rename_target(text: str) -> tuple[str, str] | str | None:
    """'name that session calculus' / 'rename the 6 to 7 session to chemistry' ->
    (event_id, new_title). A string is a message to say to the user; None = not a rename."""
    t = " ".join(text.replace(",", " ").split())
    if _QUESTION.search(t):
        return None
    verbs = list(_RENAME.finditer(t))
    if not verbs:
        return None
    verb = verbs[-1]
    head, tail = t[:verb.start()], t[verb.end():]

    split = re.match(r"^(.*?)\b(?:to|as|into)\b\s+(?!\d)(.+)$", tail, re.I)   # not "7 to 8"
    if split:                                    # "rename <which> to <new>"
        ref_text, new_src = f"{head} {split.group(1)}", split.group(2)
    else:                                        # "name it <new>" / "label it <new> for the 7 to 8 one"
        ref_text = head + " " + tail
        new_src = re.sub(r"^\s*(?:the\s+)?(?:it|that|this|them|those)\s*(?:one|session|event|block|slot)?\s*", "",
                         tail, flags=re.I)
    new_src = _RANGE.sub(" ", new_src)
    new_src = _AT.sub(" ", new_src)
    new_src = re.split(r"\b(?:or|and|but)\b", new_src, maxsplit=1, flags=re.I)[0]
    words = re.findall(r"[A-Za-z][A-Za-z'+&-]*", new_src)
    stop = _FILL | {"please", "thanks", "pm", "am", "session", "one", "event"}
    while words and words[0].lower() in stop - {"session", "one", "event"}:
        words.pop(0)
    while words and words[-1].lower() in stop:
        words.pop()
    if not words or len(words) > 5:
        return None
    new_title = " ".join(words)
    new_title = new_title[0].upper() + new_title[1:]

    try:
        data = _load()
    except RuntimeError:
        return None
    dayword = _DAYWORD.search(t)
    day = _to_date(re.sub(r"^(on|this|next) ", "", dayword.group(1).lower()).replace("tonight", "today")) \
        if dayword else date.today()
    todays = [ev for ev in data["events"] if _shows(data, ev, day)]

    cands: list[dict] = []
    span = _RANGE.search(ref_text)
    if span:
        h1, m1, a1, h2, m2, a2 = span.groups()
        mer = bool(a1 or a2)
        s1 = _clock(h1, m1, a1 or a2 if mer else None)
        e1 = _clock(h2, m2, a2 or a1 if mer else None)
        cands = [ev for ev in todays if _to_min(ev["start"]) == s1 and _to_min(ev["end"]) == e1] \
            or [ev for ev in todays if _to_min(ev["start"]) == s1]
    else:
        at = _AT.search(ref_text)
        if at:
            g = at.groups()
            h, m, mer = (g[0], g[1], g[2]) if g[0] else (g[3], g[4], g[5])
            cands = [ev for ev in todays if _to_min(ev["start"]) == _clock(h, m, mer)]
    if not cands:
        cands = [ev for ev in todays if ev["title"].lower() in ref_text.lower()]
    if not cands and re.search(r"\b(it|that|this|last|latest)\b", ref_text, re.I):
        recent = [ev for ev in data["events"] if ev.get("kind") != "fixed" and ev.get("date") == day.isoformat()]
        cands = recent[-1:]                       # the one added most recently
    if not cands:
        return "I could not tell which event to rename. Say the time, for example: rename the 6 to 7 PM session to calculus."
    if len(cands) > 1:
        cands = [ev for ev in cands if ev.get("kind") != "fixed"] or cands
    if len(cands) > 1:
        return "More than one event matches. Tell me the exact time, for example 6 to 7 PM."
    return cands[0]["id"], new_title


_NUMW = {"zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8}
_HW_DUR = re.compile(
    r"\b(?:(an?|one|two|three|four|five|six|seven|eight|\d+(?:\.\d+)?)\s*(?:and a half|and a quarter)?\s*"
    r"(hours?|hrs?|minutes?|mins?)|half an hour|an hour and a half|(\d+)\s*(?:and a half)\s*hours?)\b", re.I)


def parse_homework_request(text: str) -> tuple[str, int, str] | None:
    """'I have 3 hours of homework on thursday' -> ('day', 180, 'thursday');
    'set my homework to 90 minutes' -> ('default', 90, ''). None if it is not about the amount."""
    t = " ".join(text.lower().replace(",", " ").split())
    if not re.search(r"\b(homework|hw)\b", t) or _QUESTION.search(t):
        return None
    if _RANGE.search(t) or re.search(r"\bat\s+\d", t):        # clock times = an add request
        return None
    if re.search(r"\b(no|zero|none|without)\b[^.]{0,12}\b(homework|hw)\b|\b(homework|hw)\b[^.]{0,12}\b(is|are)\s+(zero|none)\b", t):
        minutes = 0
    else:
        m = None
        if "an hour and a half" in t:
            minutes = 90
        elif "half an hour" in t:
            minutes = 30
        else:
            m = re.search(r"\b(an?|one|two|three|four|five|six|seven|eight|\d+(?:\.\d+)?)\s*(and a half\s*)?"
                          r"(hours?|hrs?|minutes?|mins?)\b", t)
            if not m:
                return None
            n = 1.0 if m.group(1) in ("a", "an") else float(_NUMW.get(m.group(1), m.group(1)) if m.group(1) in _NUMW else m.group(1))
            if m.group(2):
                n += 0.5
            minutes = int(round(n * (60 if m.group(3).startswith("h") else 1)))
    day = _DAYWORD.search(t)
    dayword = re.sub(r"^(on|this|next) ", "", day.group(1)).replace("tonight", "today") if day else ""
    if dayword:
        return "day", minutes, dayword
    if re.search(r"\b(set|make|change|update|usually|every|each|per|default|normally|from now on)\b", t):
        return "default", minutes, ""
    return "day", minutes, "today"


def sounds_like_add(text: str) -> bool:
    """An add request with numbers in it that parse_add_request could not read
    (e.g. speech recognition turned 6:40 into '6: 4')."""
    t = " ".join(text.split())
    return bool(_INTENT.search(t)) and bool(re.search(r"\d", t)) and not _QUESTION.search(t) \
        and not re.search(r"\b(homework|hw)\b", t, re.I)