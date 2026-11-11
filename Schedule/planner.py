"""Goals and the week planner, homework per day, and days off school."""
from __future__ import annotations

import copy
import math
import re
from datetime import date, datetime, timedelta

from . import permission, tasks
from .rules import _applies, _bumpable, _busy, _conflict, _describe, _find, _free, _is_school, _new_id, _off, _shows, _span, _suggest
from .store import DEFAULT, _load, _lock, _save
from .timeparse import DAY_CODES, WEEKDAYS, _MONTHS, _WEEKDAY_NAMES, _fmt, _hhmm, _pretty_day, _to_date, _to_days, _to_min, _week_start


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
            if old.get("skip_dates"):
                goal["skip_dates"] = old["skip_dates"]
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
            if not (ev.get("auto") and ev.get("date") and not ev.get("task")
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
            skipped = set(goal.get("skip_dates", []))
            days = [d for d in week if d >= today and d.isoformat() not in skipped
                    and (not allowed or DAY_CODES[d.weekday()] in allowed)]

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
        if data.get("tasks"):
            tasks.replan_after_change(data)       # deadlines: fill anything that went missing
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
        keep, touched = [], False
        for d in data["days_off"]:
            d_start, d_end = date.fromisoformat(d["start"]), date.fromisoformat(d.get("end", d["start"]))
            if d_end < first or d_start > last:
                keep.append(d)
                continue
            touched = True                   # trim only the days asked for; keep the rest of the range
            if d_start < first:
                keep.append(dict(d, end=(first - timedelta(days=1)).isoformat()))
            if d_end > last:
                keep.append(dict(d, start=(last + timedelta(days=1)).isoformat()))
        if not touched:
            return f"There is no day off on {span}."
        if not permission.ask("remove day off", span, "School will count on these days again."):
            return "The user declined this time, so nothing changed. If they ask again, call set_day_off again."
        with _lock:
            data["days_off"] = keep
            _save(data)
        return f"Removed the day off on {span}. Run plan_week to re-plan."

    if not permission.ask("add day off", span, f"{' '.join(str(title).split()) or 'No school'}: school is skipped on these days."):
        return "The user declined this time, so nothing changed. If they ask again, call set_day_off again."
    with _lock:
        data["days_off"].append({"start": first.isoformat(), "end": last.isoformat(),
                                 "title": " ".join(str(title).split()) or "No school"})
        data["days_off"].sort(key=lambda d: d["start"])
        _save(data)
    return f"Marked {span} as a day off ({title}). Run plan_week to re-plan."
