"""Read-only data for the SCHEDULE tab."""
from __future__ import annotations

from datetime import date, timedelta

from .rules import _applies, _bumpable, _busy, _conflict, _describe, _find, _free, _is_school, _new_id, _off, _shows, _span, _suggest
from .store import DEFAULT, _load, _lock, _save
from .timeparse import DAY_CODES, WEEKDAYS, _MONTHS, _WEEKDAY_NAMES, _fmt, _hhmm, _pretty_day, _to_date, _to_days, _to_min, _week_start


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
                        "task": bool(ev.get("task")),
                        "start": _hhmm(_to_min(ev["start"])), "end": _hhmm(_to_min(ev["end"]))}
                       for ev in items],
        })
    goals = [{"title": g.get("title", ""), "minutes": g.get("minutes", 0), "per": g.get("per", "week")}
             for g in data.get("goals", [])]
    from .tasks import tasks_view
    return {"start": monday.isoformat(), "days": days, "goals": goals, "tasks": tasks_view()}
