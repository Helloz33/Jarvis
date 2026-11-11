"""Events: list, add, change, delete, place (Iris picks the time) and clear a day."""
from __future__ import annotations

import copy
import math
import re
from datetime import date, datetime, timedelta

from . import permission, tasks
from .rules import _task_overlaps, _applies, _bumpable, _busy, _conflict, _describe, _find, _free, _is_school, _new_id, _off, _shows, _span, _suggest
from .store import DEFAULT, _load, _lock, _save
from .timeparse import DAY_CODES, WEEKDAYS, _MONTHS, _WEEKDAY_NAMES, _fmt, _hhmm, _pretty_day, _to_date, _to_days, _to_min, _week_start


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
            problem = _conflict(data, ev, skip_tasks=True)
            if problem:
                return f"Error: that {problem}"
            covered = _task_overlaps(data, ev)          # planned task work this event sits on top of
            after = copy.deepcopy(data)
            after["events"] = [e for e in after["events"] if e["id"] not in {c["id"] for c in covered}] + [ev]
            if covered:
                refused = tasks.guard(data, after, "add an event over task time", title)
                if refused:
                    return refused
            if kind == "fixed" and not permission.ask("add a fixed event", title, _describe(ev)):
                return f"Add cancelled: you declined the fixed event {title}."
            for c in covered:
                data["events"].remove(c)
            data["events"].append(ev)
            moved = tasks.replan_after_change(data) if covered else ""
            _save(data)
        return f"Added {kind} event: {_describe(ev)}" + (f" {moved}" if moved else "")
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
            problem = _conflict(data, ev, ignore=ev["id"], skip_tasks=True)
            if problem:
                return f"Error: that {problem}"
            covered = [c for c in _task_overlaps(data, ev) if c["id"] != ev["id"]]
            if found.get("task") or covered:
                after = copy.deepcopy(data)
                after["events"] = [e for e in after["events"] if e["id"] != ev["id"]
                                   and e["id"] not in {c["id"] for c in covered}]
                moved_ev = dict(ev)
                moved_ev.pop("auto", None)
                after["events"].append(moved_ev)
                if found.get("task") and date.fromisoformat(ev.get("date") or "9999-12-31") > \
                        date.fromisoformat(next((t["due"] for t in data.get("tasks", []) if t["id"] == found["task"]),
                                                "9999-12-31")):
                    after["events"].remove(moved_ev)       # work after the due date does not count
                refused = tasks.guard(data, after, "move task time", found["title"])
                if refused:
                    return refused
                for c in covered:
                    data["events"].remove(c)
            if found.get("kind") == "fixed" and not permission.ask(
                "change a fixed event", found["title"], f"now: {_describe(found)}\nnew: {_describe(ev)}"
            ):
                return f"Change cancelled: you declined to change {found['title']}."
            found.clear()
            found.update(ev)
            found.pop("auto", None)      # a hand-edited event is no longer replanned
            moved = tasks.replan_after_change(data) if (found.get("task") or covered) else ""
            _save(data)
        return f"Updated: {_describe(ev)}" + (f" {moved}" if moved else "")
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
            if found.get("kind") == "fixed" and not permission.ask(
                "delete a fixed event", found["title"], _describe(found)
            ):
                return f"Deletion cancelled: you declined to delete {found['title']}."
            if found.get("task"):
                after = copy.deepcopy(data)
                after["events"] = [e for e in after["events"] if e["id"] != found["id"]]
                refused = tasks.guard(data, after, "remove task time", found["title"])
                if refused:
                    return refused
                tasks.block_slot(data, found)         # never plan it back into the same slot
            data["events"].remove(found)
            moved = tasks.replan_after_change(data) if found.get("task") else ""
            _save(data)
        return f"Deleted event: {_describe(found)}" + (f" {moved}" if moved else "")
    except (ValueError, RuntimeError) as exc:
        return f"Error: {exc}"


def _anchor_event(data: dict, day: date, name: str) -> tuple[int, int] | None:
    """(start, end) in minutes of the event on this day whose title matches name."""
    name = name.strip().lower()
    for ev in data["protected"] + data["events"]:
        title = str(ev.get("title", "")).strip().lower()
        if title and (name in title or title in name) and _shows(data, ev, day):
            return _to_min(ev["start"]), _to_min(ev["end"])
    return None


def place_event(
    title: str = "",
    minutes: int = 60,
    count: int = 1,
    titles: str = "",
    day: str = "",
    after: str = "",
    before: str = "",
    within: str = "this week",
) -> str:
    """Add flexible event(s) and choose the time yourself. Use this when the user does not
    give a clock time ("add 2 hours of test prep, one for math and one for chem, place it
    how you see fit"). title + minutes + count makes count sessions of that length; titles
    ("Math test prep;Chem test prep") makes one session per title. day = a weekday, date, today
    or tomorrow (default: spread over the rest of this week, falling back to next week).
    after / before = the name of an event to sit right after or before (e.g. 'club', 'dinner')."""
    try:
        data = _load()
        names = [" ".join(p.split()) for p in re.split(r"[;|,]", str(titles or "")) if p.strip()]
        if not names:
            base = " ".join(str(title).split())
            if not base:
                return "Error: the event needs a title."
            try:
                n = max(1, min(int(count or 1), 14))
            except (TypeError, ValueError):
                n = 1
            names = [base] * n
        try:
            length = int(float(minutes or 60))
        except (TypeError, ValueError):
            length = 60
        if not 15 <= length <= 12 * 60:
            return "Error: a session must be between 15 minutes and 12 hours."

        today = date.today()
        now = datetime.now()
        now_min = math.ceil((now.hour * 60 + now.minute) / 15) * 15
        windows = data["settings"]["study_window"]
        after, before = str(after or "").strip(), str(before or "").strip()

        if str(day or "").strip():
            first = _to_date(day)
            if first < today:
                return f"Error: {_pretty_day(first)} has already passed."
            phases = [[first]]
        else:
            start = _week_start(today)
            this_week = [d for d in (start + timedelta(days=i) for i in range(7)) if d >= today]
            next_start = start + timedelta(days=7)
            if "next" in str(within).lower():
                phases = [[next_start + timedelta(days=i) for i in range(7)]]
            else:
                phases = [this_week, [next_start + timedelta(days=i) for i in range(7)]]

        used: dict[date, int] = {}
        placed: list[str] = []
        seen_anchor = not (after or before)

        def try_day(d: date, name: str) -> tuple[int, int] | None:
            nonlocal seen_anchor
            key = "weekend" if (d.weekday() >= 5 or _off(data, d)) else "weekday"
            lo, hi = (_to_min(x) for x in windows[key])
            if d == today:
                lo = max(lo, now_min)
            if after or before:
                spot = _anchor_event(data, d, after or before)
                if not spot:
                    return None
                seen_anchor = True
                if after:
                    lo = max(spot[1], now_min if d == today else 0)
                    hi = max(hi, lo + length)
                else:
                    hi = min(hi, spot[0]) if spot[0] > lo else spot[0]
            gaps = [(a, b) for a, b in _free(data, d, lo, hi) if b - a >= length]
            if not gaps:
                return None
            if before and not after:
                b = gaps[-1][1]
                return b - length, b                  # right before the anchor
            a = gaps[0][0]
            return a, a + length

        with _lock:
            for name in names:
                done = None
                for days in phases:
                    for d in sorted(days, key=lambda x: (used.get(x, 0), x)):
                        slot = try_day(d, name)
                        if slot:
                            done = (d, slot)
                            break
                    if done:
                        break
                if not done:
                    if not seen_anchor:
                        return f"Error: I could not find '{after or before}' on those days."
                    hint = _suggest(data, phases[0][0], length) if len(phases) == 1 else ""
                    return ("Error: " + (f"placed {'; '.join(placed)}, but " if placed else "")
                            + f"there is no free {length}-minute gap for {name}. {hint}").strip()
                d, (a, b) = done
                data["events"].append({"id": _new_id(data), "title": name, "kind": "flexible",
                                       "date": d.isoformat(), "start": _hhmm(a), "end": _hhmm(b)})
                used[d] = used.get(d, 0) + 1
                placed.append(f"{name} on {_pretty_day(d)}, {_fmt(a)}-{_fmt(b)}")
            _save(data)
        return "Placed " + "; ".join(placed)
    except (ValueError, RuntimeError) as exc:
        return f"Error: {exc}"


def clear_day(start_date: str, end_date: str = "", what: str = "") -> str:
    """Remove the flexible events (homework, study sessions, test prep...) from a day or a range,
    and stop plan_week from putting those goals back on those days. what = names to clear, separated
    by ';' (e.g. 'homework;physics;test prep'); empty = everything flexible. Fixed commitments
    (school, club, gym) are never touched."""
    try:
        data = _load()
        first = _to_date(start_date)
        last = _to_date(end_date) if end_date else first
    except (ValueError, RuntimeError) as exc:
        return f"Error: {exc}"
    if last < first:
        first, last = last, first
    if (last - first).days > 31:
        return "Error: I can clear at most 31 days at once."
    names = [" ".join(n.lower().split()) for n in re.split(r"[;|,]", str(what or "")) if n.strip()]
    span = _pretty_day(first) + (f" to {_pretty_day(last)}" if last != first else "")
    days = [first + timedelta(days=i) for i in range((last - first).days + 1)]
    iso = {d.isoformat() for d in days}

    def wanted(title: str) -> bool:
        t = title.lower()
        return not names or any(n in t or t in n for n in names)

    with _lock:
        hit = [ev for ev in data["events"]
               if ev.get("kind") != "fixed" and ev.get("date") in iso and not ev.get("days") and wanted(ev["title"])]
        goals = [g for g in data["goals"] if wanted(g["title"])]
        task_hits = [t for t in data.get("tasks", []) if t.get("status", "open") == "open" and wanted(t["title"])]
        if not hit and not goals and not task_hits:
            return f"There is nothing to clear on {span}."
        today = date.today()

        def skip(items: list[dict]) -> None:
            for g in items:
                keep = [d for d in g.get("skip_dates", []) if date.fromisoformat(d) >= today - timedelta(days=7)]
                g["skip_dates"] = sorted(set(keep) | {d for d in iso if date.fromisoformat(d) >= today})

        impact_ask, impact = False, ""
        if any(ev.get("task") for ev in hit) or task_hits:
            after = copy.deepcopy(data)
            gone = {ev["id"] for ev in hit}
            after["events"] = [e for e in after["events"] if e["id"] not in gone]
            skip([t for t in after.get("tasks", []) if t["id"] in {x["id"] for x in task_hits}])
            impact_ask, impact = tasks.check_change(data, after, "clear a day")
        if not names and not permission.ask("clear everything flexible", span,
                                            f"{len(hit)} events will be removed and goals will skip these days."
                                            + (f" {impact}" if impact else "")):
            return "The user declined this time, so nothing changed. If they ask again, call clear_day again."
        if names and impact_ask and not permission.ask("clear task time", span, impact + " Still go ahead?"):
            return "The user declined this time, so nothing changed. If they ask again, call clear_day again."
        for ev in hit:
            data["events"].remove(ev)
        skip(goals)
        skip(task_hits)
        moved = tasks.replan_after_change(data) if (task_hits or any(ev.get("task") for ev in hit)) else ""
        _save(data)
    titles = []
    for ev in sorted(hit, key=lambda e: (e["date"], e["start"])):
        if ev["title"] not in titles:
            titles.append(ev["title"])
    removed = f"{len(hit)} session{'s' if len(hit) != 1 else ''} ({', '.join(titles)})" if hit else ""
    kept = sorted({ev["title"] for d in days for ev in data["events"]
                   if ev.get("kind") == "fixed" and _shows(data, ev, d)})
    out = f"Cleared {span}: " + (removed or "no events were placed") + "."
    if goals:
        out += " Goals skip these days: " + ", ".join(g["title"] for g in goals) + "."
    if kept:
        out += " Left alone: " + ", ".join(kept) + "."
    if moved:
        out += " " + moved
    return out
