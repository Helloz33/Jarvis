"""Clock: the current date and time, on this computer or in another time zone."""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def _format(moment: datetime) -> str:
    hour = moment.hour % 12 or 12
    return (
        f"{moment:%A, %B} {moment.day}, {moment:%Y}, "
        f"{hour}:{moment:%M} {moment:%p} {moment:%Z}"
    ).strip()


def now_line() -> str:
    """The current local date and time, e.g. 'Sunday, October 11, 2026, 12:45 PM EDT'."""
    return _format(datetime.now().astimezone())


def get_time(timezone: str = "") -> str:
    """Current date and time. Leave timezone empty for this computer's time,
    or pass an IANA name such as 'America/Los_Angeles' or 'Asia/Tokyo'."""
    timezone = (timezone or "").strip()
    if not timezone:
        return now_line()
    try:
        return f"{_format(datetime.now(ZoneInfo(timezone)))} ({timezone})"
    except (ZoneInfoNotFoundError, ValueError, KeyError):
        return (
            f"Error: unknown time zone '{timezone}'. Use a name like "
            "America/Chicago, Europe/London or Asia/Tokyo."
        )