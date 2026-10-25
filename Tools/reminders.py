"""Spoken and silent schedule reminders: "Sir, we have Physics scheduled for 4:05 PM."

Used in two places, so reminders work whether or not the Jarvis window is open:
  * the Jarvis app (Server.py) starts it and speaks through its own voice;
  * Wake_Jarvis.py starts it too (from Tools import reminders), but it stays quiet while the app
    is running (the app handles reminders then) and otherwise sends a macOS notification and speaks.

The rules (which events, quiet hours, lead time) live in Tools/schedule.py: due_reminders().
Which reminders were already given is remembered in Schedule_data/reminders_sent.json, so a
restart never repeats one.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent      # the Jarvis folder
SENT_FILE = ROOT / "Schedule_data" / "reminders_sent.json"
INTERVAL = 30            # seconds between checks

_lock = threading.Lock()


def _schedule():
    from . import schedule
    return schedule


def _voice() -> str:
    try:
        from Personality import VOICE
        return VOICE
    except Exception:
        return "Daniel"


def _load_sent() -> dict:
    try:
        return json.loads(SENT_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _remember(key: str) -> None:
    cutoff = (datetime.now() - timedelta(days=3)).isoformat()
    sent = {k: v for k, v in _load_sent().items() if v > cutoff}
    sent[key] = datetime.now().isoformat()
    try:
        SENT_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = SENT_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(sent), encoding="utf-8")
        os.replace(tmp, SENT_FILE)
    except OSError:
        pass


def pending(now: datetime | None = None) -> list[dict]:
    """Reminders that are due and not given yet. Each is marked as given as it is returned."""
    out = []
    with _lock:
        sent = _load_sent()
        for item in _schedule().due_reminders(now):
            if item["key"] in sent:
                continue
            _remember(item["key"])
            out.append(item)
    return out


def notify(text: str) -> None:
    """A silent macOS notification (no-op on other systems)."""
    if sys.platform != "darwin":
        return
    script = 'on run argv\ndisplay notification (item 1 of argv) with title "Jarvis"\nend run'
    try:
        subprocess.run(["osascript", "-e", script, text], timeout=10, capture_output=True)
    except (OSError, subprocess.SubprocessError):
        pass


def say(text: str) -> None:
    if sys.platform != "darwin":
        return
    try:
        if subprocess.run(["say", "-v", _voice(), text], timeout=60).returncode != 0:
            subprocess.run(["say", text], timeout=60)
    except (OSError, subprocess.SubprocessError):
        pass


def app_running() -> bool:
    """Is the Jarvis app (App.py) running right now?"""
    try:
        return subprocess.run(["pgrep", "-f", "App.py"], capture_output=True, timeout=5).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def _standalone_deliver(item: dict) -> None:
    notify(item["text"])
    if not item["quiet"]:
        say(item["text"])


def start(deliver=None, only_when_app_closed: bool = False, interval: int = INTERVAL) -> threading.Thread:
    """Check the schedule in a background thread and deliver reminders as they come due.

    deliver(item)  - called for each reminder; default = notification + spoken line.
    only_when_app_closed - for Wake_Jarvis.py: do nothing while the app is running.
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

    thread = threading.Thread(target=loop, name="jarvis-reminders", daemon=True)
    thread.start()
    return thread