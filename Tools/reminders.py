"""Spoken and silent schedule reminders: "Sir, we have Physics scheduled for 4:05 PM."

Used in two places, so reminders work whether or not the app's window is open:
  * the app (Server.py) starts it and speaks through its own voice;
  * Wake.py starts it too (from Tools import reminders), but it stays quiet while the app
    is running (the app handles reminders then) and otherwise sends a macOS notification and speaks.

The rules (which events, quiet hours, lead time) live in Schedule/alerts.py: due_reminders().
Which reminders were already given is remembered in Schedule_data/reminders_sent.json, so a
restart never repeats one.
"""
from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime, timedelta

from . import system

import paths

INTERVAL = 30            # seconds between checks

_lock = threading.Lock()


def _sent_file():
    return paths.SCHEDULE_DIR / "reminders_sent.json"


def _schedule():
    import Schedule
    return Schedule


def _voice() -> str:
    try:
        import Config
        return Config.voice()
    except Exception:
        return ""


def _load_sent() -> dict:
    try:
        return json.loads(_sent_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _remember(key: str) -> None:
    cutoff = (datetime.now() - timedelta(days=3)).isoformat()
    sent = {k: v for k, v in _load_sent().items() if v > cutoff}
    sent[key] = datetime.now().isoformat()
    try:
        _sent_file().parent.mkdir(parents=True, exist_ok=True)
        tmp = _sent_file().with_suffix(".tmp")
        tmp.write_text(json.dumps(sent), encoding="utf-8")
        os.replace(tmp, _sent_file())
    except OSError:
        pass


def _notes():
    from Schedule import notes
    return notes


def pending(now: datetime | None = None) -> list[dict]:
    """Reminders that are due and not given yet. Each is marked as given as it is returned.
    Both schedule events and the notes in the Reminders tab come through here."""
    out = []
    with _lock:
        sent = _load_sent()
        for item in list(_schedule().due_reminders(now)) + list(_notes().due_notes(now)):
            if item["key"] in sent:
                continue
            _remember(item["key"])
            out.append(item)
    return out


def notify(text: str) -> None:
    """A silent desktop notification (macOS, Windows, Linux: see Tools/system.py)."""
    import Config
    system.notify(text, Config.NAME)


def say(text: str) -> None:
    system.speak(text, _voice())


def app_running() -> bool:
    """Is the app (App.py) running right now?"""
    return system.app_running("App.py")


def _standalone_deliver(item: dict) -> None:
    notify(item["text"])
    if not item["quiet"]:
        say(item["text"])


def start(deliver=None, only_when_app_closed: bool = False, interval: int = INTERVAL) -> threading.Thread:
    """Check the schedule in a background thread and deliver reminders as they come due.

    deliver(item)  - called for each reminder; default = notification + spoken line.
    only_when_app_closed - for Wake.py: do nothing while the app is running.
    """
    deliver = deliver or _standalone_deliver

    def loop() -> None:
        while True:
            try:
                if not (only_when_app_closed and app_running()):
                    for item in pending():
                        deliver(item)
            except Exception as exc:            # never let a bad schedule file kill the thread
                print(f"[reminders] {exc}")
            time.sleep(interval)

    thread = threading.Thread(target=loop, name="reminders", daemon=True)
    thread.start()
    return thread