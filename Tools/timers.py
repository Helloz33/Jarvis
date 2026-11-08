"""Timers: "set a 25 minute timer", "set a pasta timer for 10 minutes", "how long is left?",
"cancel the timer".

Each timer runs on its own background thread and, when it ends, calls the deliver function
(the app speaks it and shows a notification). Running timers are saved in
Schedule_data/timers.json, so a timer still goes off after a restart, and one that ended while
the app was closed is reported when it opens again.
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
import uuid

from . import schedule as S

MAX_SECONDS = 24 * 3600
_lock = threading.Lock()
_timers: dict[str, dict] = {}            # id -> {"id", "label", "seconds", "ends"}
_threads: dict[str, threading.Timer] = {}
_deliver = None                          # deliver(text) when a timer ends


def _file():
    return S.DATA_DIR / "timers.json"


def _save() -> None:
    path = _file()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(list(_timers.values()), indent=1), encoding="utf-8")
        os.replace(tmp, path)
    except OSError:
        pass


def _say_duration(seconds: float) -> str:
    seconds = int(round(seconds))
    h, rest = divmod(seconds, 3600)
    m, s = divmod(rest, 60)
    parts = []
    if h:
        parts.append(f"{h} hour{'s' if h != 1 else ''}")
    if m:
        parts.append(f"{m} minute{'s' if m != 1 else ''}")
    if s and not h:
        parts.append(f"{s} second{'s' if s != 1 else ''}")
    return " and ".join(parts) if parts else "0 seconds"


def _name(t: dict) -> str:
    return f"{t['label']} timer" if t.get("label") else f"{_say_duration(t['seconds'])} timer"


def _fire(timer_id: str) -> None:
    with _lock:
        t = _timers.pop(timer_id, None)
        _threads.pop(timer_id, None)
        _save()
    if t and _deliver:
        _deliver(f"Sir, your {_name(t)} is done.")


def _arm(t: dict) -> None:
    th = threading.Timer(max(0.0, t["ends"] - time.time()), _fire, args=(t["id"],))
    th.daemon = True
    _threads[t["id"]] = th
    th.start()


def start(deliver) -> None:
    """Load saved timers and start them (called once when the app starts)."""
    global _deliver
    _deliver = deliver
    try:
        saved = json.loads(_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        saved = []
    missed = []
    with _lock:
        for t in saved:
            if not isinstance(t, dict) or "ends" not in t or "id" not in t:
                continue
            if t["ends"] <= time.time():
                missed.append(t)
            else:
                _timers[t["id"]] = t
                _arm(t)
        _save()
    for t in missed:
        deliver(f"Sir, your {_name(t)} finished while I was closed.")


# --- tools -------------------------------------------------------------------------------
def set_timer(minutes: float = 0, seconds: float = 0, label: str = "") -> str:
    """Start a countdown timer."""
    try:
        total = float(minutes or 0) * 60 + float(seconds or 0)
    except (TypeError, ValueError):
        return "Error: give the timer length as a number of minutes or seconds."
    if total < 1:
        return "Error: the timer needs a length, for example 25 minutes."
    if total > MAX_SECONDS:
        return "Error: timers can be at most 24 hours. For later than that, add a reminder instead."
    label = " ".join(str(label or "").split())[:40]
    t = {"id": uuid.uuid4().hex[:6], "label": label, "seconds": total, "ends": time.time() + total}
    with _lock:
        if label and any(x["label"].lower() == label.lower() for x in _timers.values()):
            return f"Error: there is already a {label} timer. Cancel it first or pick another name."
        _timers[t["id"]] = t
        _arm(t)
        _save()
    ends = time.strftime("%I:%M %p", time.localtime(t["ends"])).lstrip("0")
    return f"Timer set: {_name(t)}, done at {ends}"


def _match(timer: str) -> list[dict]:
    want = " ".join(str(timer or "").lower().replace("timer", "").split())
    items = sorted(_timers.values(), key=lambda t: t["ends"])
    if not want or want in ("the", "my", "this", "that"):
        return items
    return [t for t in items if want in t["label"].lower() or want == _say_duration(t["seconds"]).lower()
            or t["id"] == want]


def cancel_timer(timer: str = "", all_timers: bool = False) -> str:
    """Cancel a timer by its name, or all of them."""
    with _lock:
        found = sorted(_timers.values(), key=lambda t: t["ends"]) if all_timers else _match(timer)
        if not found:
            return "Error: there is no running timer like that." if _timers else "Error: no timers are running."
        if len(found) > 1 and not all_timers:
            names = ", ".join(_name(t) for t in found)
            return f"Error: which one? Running: {names}. Say its name, or cancel all timers."
        for t in found:
            th = _threads.pop(t["id"], None)
            if th:
                th.cancel()
            _timers.pop(t["id"], None)
        _save()
    if len(found) == 1:
        return f"Cancelled the {_name(found[0])}"
    return f"Cancelled {len(found)} timers"


def list_timers() -> str:
    """Running timers and how long each has left."""
    with _lock:
        items = sorted(_timers.values(), key=lambda t: t["ends"])
    if not items:
        return "No timers are running."
    parts = [f"{_name(t)}: {_say_duration(max(0, t['ends'] - time.time()))} left" for t in items]
    return "; ".join(parts)


def timers_view() -> list[dict]:
    with _lock:
        return [{"id": t["id"], "name": _name(t), "ends": t["ends"]} for t in sorted(_timers.values(), key=lambda t: t["ends"])]


# --- understanding plain requests (no model needed) ---------------------------------------
_NUM_WORDS = {
    "a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
    "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "fifteen": 15, "twenty": 20,
    "thirty": 30, "forty": 40, "forty five": 45, "forty-five": 45, "fifty": 50, "sixty": 60, "ninety": 90,
    "a couple of": 2, "a couple": 2, "couple of": 2, "a few": 3,
}
_NUM = r"(\d+(?:\.\d+)?|" + "|".join(sorted((re.escape(k) for k in _NUM_WORDS), key=len, reverse=True)) + r")"
_UNIT = r"(hours?|hrs?|h|minutes?|mins?|m|seconds?|secs?|s)\b"
_PART = re.compile(_NUM + r"[\s-]*" + _UNIT, re.I)
_HALF_HOUR = re.compile(r"\bhalf (?:an |a )?hour\b", re.I)
_AND_HALF = re.compile(r"\band a half\b", re.I)
_QUARTER = re.compile(r"\b(?:a )?quarter (?:of an |an )?hour\b", re.I)

_TIMER = re.compile(r"\btimers?\b", re.I)
_CANCEL = re.compile(r"\b(cancel|stop|end|delete|remove|kill|turn off|clear|get rid of)\b", re.I)
_LIST = re.compile(r"\b(how (much|long)|time (is )?left|left on|remaining|check|what timers|any timers|which timers|list)\b", re.I)
_SET = re.compile(r"\b(set|start|make|create|put on|add|give me|begin|run)\b|^\s*(a |an )?[\w.\- ]*\btimer\b", re.I)
_LABEL_CALLED = re.compile(r"\b(?:called|named|labell?ed)\s+(?:the |my )?([a-z][a-z' ]{0,30}?)\s*$", re.I)
_LABEL_FOR = re.compile(r"\btimer\b.*?\bfor\s+(?:the |my )?([a-z][a-z' ]{0,30}?)\s*$", re.I)
_LABEL_BEFORE = re.compile(r"(?:\b(?:a|an|the|my)\s+)([a-z][a-z' ]{0,30}?)\s+timer\b", re.I)
_FILLER = re.compile(r"\b(please|now|thanks|thank you|real quick|quickly|ok|okay|for me|right away)\b", re.I)
_NOT_LABEL = re.compile(r"^(?:\d|a|an|the|my|new|quick|short|long|countdown|kitchen)$|(?:hour|minute|min|second|sec)s?\b", re.I)


def _duration(text: str) -> float:
    total = 0.0
    t = text.lower()
    if _HALF_HOUR.search(t):
        total += 1800
        t = _HALF_HOUR.sub(" ", t)
    if _QUARTER.search(t):
        total += 900
        t = _QUARTER.sub(" ", t)
    for m in _PART.finditer(t):
        num, unit = m.group(1).lower(), m.group(2).lower()
        n = float(num) if num[0].isdigit() else float(_NUM_WORDS.get(num, 0))
        mult = 3600 if unit.startswith("h") else 1 if unit.startswith("s") else 60
        total += n * mult
        if _AND_HALF.search(t[m.end():m.end() + 14]):
            total += mult / 2
    return total


def _without_durations(text: str) -> str:
    t = _HALF_HOUR.sub(" ", text)
    t = _QUARTER.sub(" ", t)
    t = _AND_HALF.sub(" ", t)
    t = _PART.sub(" ", t)
    t = _FILLER.sub(" ", t)
    t = re.sub(r"\b(for|and)\s+(?=(for|and|called|named)\b)", " ", t, flags=re.I)
    return " ".join(t.split()).strip(" ,")


def _label(text: str) -> str:
    t = _without_durations(text)
    for rx in (_LABEL_CALLED, _LABEL_FOR, _LABEL_BEFORE):
        m = rx.search(t)
        if m:
            words = [w for w in m.group(1).split() if not _NOT_LABEL.search(w)]
            label = " ".join(w for w in words if w.lower() not in ("a", "an", "the", "my", "for", "and"))
            if label:
                return label.strip()
    return ""


def parse_timer_request(text: str) -> dict | None:
    """'set a 25 minute timer' -> {'action': 'set', 'seconds': 1500, 'label': ''}; None if not about timers."""
    t = " ".join((text or "").replace("’", "'").split()).strip(" .!?")
    if not _TIMER.search(t):
        return None
    if _CANCEL.search(t):
        everything = re.search(r"\ball\b|\btimers\b", t, re.I) is not None
        name = _label(t)
        return {"action": "cancel", "timer": name, "all": everything and not name}
    seconds = _duration(t)
    if seconds and (_SET.search(t) or not _LIST.search(t)):
        return {"action": "set", "seconds": seconds, "label": _label(t)}
    if _LIST.search(t):
        return {"action": "list"}
    return None