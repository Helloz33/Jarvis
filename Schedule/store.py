"""Loading and saving Schedule_data/schedule.json (plain data, easy to edit by hand)."""
from __future__ import annotations

import copy
import json
import os
import threading

import paths

from .timeparse import DAY_CODES


def schedule_file():
    return paths.SCHEDULE_DIR / "schedule.json"


_lock = threading.RLock()

# First run writes this generic starting point to Schedule_data/schedule.json
# (gitignored, so your real schedule never reaches GitHub). Edit that file, or
# just tell the assistant your classes and commitments.
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
    "tasks": [],         # deadlines with estimates, planned by Schedule/tasks.py
    "days_off": [],      # e.g. {"start": "2026-11-26", "end": "2026-11-27", "title": "Thanksgiving"}
}


# --- storage ---------------------------------------------------------------------
def _save(data: dict) -> None:
    paths.SCHEDULE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = schedule_file().with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    os.replace(tmp, schedule_file())


def _load() -> dict:
    with _lock:
        if not schedule_file().exists():
            data = copy.deepcopy(DEFAULT)
            _save(data)
            return data
        try:
            data = json.loads(schedule_file().read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise RuntimeError(f"the schedule file is unreadable ({exc}); fix or delete {schedule_file()}")
        for key, value in DEFAULT.items():
            data.setdefault(key, copy.deepcopy(value))
        return data
