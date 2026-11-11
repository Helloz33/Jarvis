"""Which schedule reminders are due right now (delivered by Tools/reminders.py)."""
from __future__ import annotations

from datetime import datetime

import Strings

from .rules import _applies, _bumpable, _busy, _conflict, _describe, _find, _free, _is_school, _new_id, _off, _shows, _span, _suggest
from .store import DEFAULT, _load, _lock, _save
from .timeparse import DAY_CODES, WEEKDAYS, _MONTHS, _WEEKDAY_NAMES, _fmt, _hhmm, _pretty_day, _to_date, _to_days, _to_min, _week_start


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
                        "text": (Strings.task_session(ev["title"], _fmt(start)) if ev.get("task")
                                 else Strings.event_reminder(ev["title"], _fmt(start)))})
    return out
