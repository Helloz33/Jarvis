"""Reading and writing times, dates and weekdays ("3:30 pm", "next friday", "mon,wed")."""
from __future__ import annotations

import re
from datetime import date, timedelta

DAY_CODES = ["MO", "TU", "WE", "TH", "FR", "SA", "SU"]   # index = date.weekday()
WEEKDAYS = DAY_CODES[:5]


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


_MONTHS = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}


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
    md = re.fullmatch(r"([a-z]{3,9})\.?\s+(\d{1,2})(?:st|nd|rd|th)?", t)
    num = re.fullmatch(r"(\d{1,2})/(\d{1,2})", t)
    month = day_n = None
    if md and md.group(1)[:3] in _MONTHS:
        month, day_n = _MONTHS[md.group(1)[:3]], int(md.group(2))
    elif num:
        month, day_n = int(num.group(1)), int(num.group(2))
    if month:
        try:
            found = date(today.year, month, day_n)
        except ValueError:
            raise ValueError(f"could not read the date '{text}'")
        if (today - found).days > 30:        # "November 24" said in December means next year
            found = date(today.year + 1, month, day_n)
        return found
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


def _week_start(d: date) -> date:
    """Weeks run Sunday to Saturday."""
    return d - timedelta(days=(d.weekday() + 1) % 7)
