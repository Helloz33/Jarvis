"""Reminders tab: short "don't forget" notes, kept in Schedule_data/notes.json.

    "remind me to bring my charger tomorrow"     -> a dated note
    "remind me at 7 pm to call dad"              -> a timed note (spoken or notified like any reminder)
    "don't let me forget the permission slip"    -> an undated note
    "cross off the charger" / "what do I need to remember?" / "clear my done reminders"

Timed and dated notes are delivered by Tools/reminders.py through due_notes(); the quiet hours in
the schedule settings apply (a note that falls inside quiet hours only gets a silent notification).
Everything here is plain text in, plain text out, so it can be called by the model or directly.
"""
from __future__ import annotations

import json
import os
import re
import threading
import uuid
from datetime import date, datetime, timedelta

from . import schedule as S

_lock = threading.RLock()
MORNING = 7 * 60 + 30      # a note with a day but no time is delivered at 7:30


# --- storage --------------------------------------------------------------------------
def _file():
    return S.DATA_DIR / "notes.json"


def _load() -> dict:
    with _lock:
        try:
            data = json.loads(_file().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {"notes": []}
        data.setdefault("notes", [])
        return data


def _save(data: dict) -> None:
    S.DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = _file().with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    os.replace(tmp, _file())


def _new_id(data: dict) -> str:
    used = {n["id"] for n in data["notes"]}
    while True:
        nid = uuid.uuid4().hex[:4]
        if nid not in used:
            return nid


def _when(note: dict, today: date | None = None) -> str:
    """'today 7:00 PM', 'Tue Nov 3', '' (no day)."""
    today = today or date.today()
    if not note.get("date"):
        return ""
    d = date.fromisoformat(note["date"])
    word = ("today" if d == today else "tomorrow" if d == today + timedelta(days=1) else S._pretty_day(d))
    if note.get("time"):
        word += " " + S._fmt(S._to_min(note["time"]))
    return word


def _match(data: dict, key: str) -> list[dict]:
    key = " ".join(str(key).lower().split())
    if not key:
        return []
    exact = [n for n in data["notes"] if n["id"] == key]
    if exact:
        return exact
    hits = [n for n in data["notes"] if key in n["text"].lower() or n["text"].lower() in key]
    open_hits = [n for n in hits if not n.get("done")]
    return open_hits or hits


# --- tools -----------------------------------------------------------------------------
def add_note(text: str, date: str = "", time: str = "") -> str:      # noqa: A002 - tool argument names
    """Save a reminder note. date = today, tomorrow, a weekday or YYYY-MM-DD (optional);
    time = e.g. 7 pm (optional). With a time it is announced when it comes due."""
    try:
        text = " ".join(str(text).split()).strip(" .,;")
        if not text:
            return "Error: the note needs some text."
        day = S._to_date(date).isoformat() if str(date or "").strip() else ""
        clock = S._hhmm(S._to_min(time)) if str(time or "").strip() else ""
        if clock and not day:
            now = datetime.now()
            day = (now.date() if S._to_min(clock) > now.hour * 60 + now.minute
                   else now.date() + timedelta(days=1)).isoformat()
        text = text[0].upper() + text[1:]
        with _lock:
            data = _load()
            same = next((n for n in data["notes"] if not n.get("done") and n["text"].lower() == text.lower()
                         and n.get("date") == day and n.get("time") == clock), None)
            if same:
                return f"That is already on your list: {same['text']}."
            note = {"id": _new_id(data), "text": text, "date": day, "time": clock, "done": False,
                    "created": datetime.now().isoformat(timespec="seconds")}
            data["notes"].append(note)
            _save(data)
        when = _when(note)
        return f"Noted: {text}" + (f" ({when})" if when else "") + "."
    except (ValueError, RuntimeError) as exc:
        return f"Error: {exc}"


def list_notes(include_done: bool = False) -> str:
    """The open reminder notes, soonest first."""
    data = _load()
    items = [n for n in _sorted(data["notes"]) if include_done or not n.get("done")]
    if not items:
        return "You have no reminders."
    lines = []
    for n in items:
        when = _when(n)
        lines.append(f"{n['text']}" + (f" ({when})" if when else "") + (" [done]" if n.get("done") else "")
                     + f" [{n['id']}]")
    count = len(items)
    return f"You have {count} reminder{'s' if count != 1 else ''}: " + "; ".join(lines)


def complete_note(note: str, remove: bool = False) -> str:
    """Cross a note off (or remove it entirely with remove=True). note = its id or some of its words."""
    with _lock:
        data = _load()
        hits = _match(data, note)
        if not hits:
            return f"Error: I could not find a reminder matching '{note}'."
        if len(hits) > 1:
            names = ", ".join(f"{n['text']} [{n['id']}]" for n in hits[:5])
            return f"Error: several reminders match; say which one: {names}"
        item = hits[0]
        if remove:
            data["notes"].remove(item)
        else:
            item["done"] = True
        _save(data)
    return f"{'Removed' if remove else 'Crossed off'}: {item['text']}."


def delete_note(note_id: str) -> bool:
    """Remove one note by id (the UI's delete button)."""
    with _lock:
        data = _load()
        keep = [n for n in data["notes"] if n["id"] != note_id]
        if len(keep) == len(data["notes"]):
            return False
        data["notes"] = keep
        _save(data)
    return True


def toggle_note(note_id: str) -> bool:
    """Check or uncheck one note by id (the UI's checkbox)."""
    with _lock:
        data = _load()
        for n in data["notes"]:
            if n["id"] == note_id:
                n["done"] = not n.get("done")
                _save(data)
                return True
    return False


def clear_notes(done_only: bool = True) -> str:
    """Remove the crossed-off notes (default) or every note (asks first)."""
    with _lock:
        data = _load()
        gone = [n for n in data["notes"] if n.get("done") or not done_only]
        if not gone:
            return "There is nothing to clear."
        if not done_only and not S.ask_permission("clear all reminders", f"{len(gone)} notes",
                                                  "; ".join(n["text"] for n in gone[:8])):
            return "The user declined this time, so nothing changed. If they ask again, call clear_notes again."
        data["notes"] = [n for n in data["notes"] if n not in gone]
        _save(data)
    return f"Cleared {len(gone)} reminder{'s' if len(gone) != 1 else ''}."


# --- view for the UI -------------------------------------------------------------------
def _key(n: dict):
    return (bool(n.get("done")), n.get("date") or "9999", n.get("time") or "99:99", n.get("created", ""))


def _sorted(notes: list[dict]) -> list[dict]:
    return sorted(notes, key=_key)


def upcoming_alerts(now: datetime | None = None, limit: int = 6) -> list[dict]:
    """The next scheduled alerts: events that remind you, over the coming week."""
    now = now or datetime.now()
    try:
        data = S._load()
    except RuntimeError:
        return []
    lead = int((data["settings"].get("reminders") or {}).get("lead_minutes", 15))
    out = []
    for offset in range(7):
        day = now.date() + timedelta(days=offset)
        label = "Today" if offset == 0 else "Tomorrow" if offset == 1 else S._pretty_day(day)
        for ev in data["events"]:
            if ev.get("remind") is False or not S._shows(data, ev, day):
                continue
            start = S._to_min(ev["start"])
            if offset == 0 and start <= now.hour * 60 + now.minute:
                continue
            out.append({"sort": (offset, start), "when": f"{label} {S._fmt(start)}", "title": ev["title"],
                        "lead": lead})
    out.sort(key=lambda x: x["sort"])
    return [{"when": o["when"], "title": o["title"], "lead": o["lead"]} for o in out[:limit]]


def notes_view() -> dict:
    today = date.today()
    items = []
    for n in _sorted(_load()["notes"]):
        d = date.fromisoformat(n["date"]) if n.get("date") else None
        items.append({"id": n["id"], "text": n["text"], "done": bool(n.get("done")),
                      "when": _when(n, today), "overdue": bool(d and d < today and not n.get("done")),
                      "timed": bool(n.get("time"))})
    return {"type": "notes", "notes": items, "upcoming": upcoming_alerts()}


# --- delivery (called by Tools/reminders.py) ----------------------------------------------
def due_notes(now: datetime | None = None) -> list[dict]:
    """Notes that should be announced right now (the caller remembers which it already gave)."""
    now = now or datetime.now()
    today, nm = now.date().isoformat(), now.hour * 60 + now.minute
    try:
        cfg = (S._load()["settings"].get("reminders") or {})
    except RuntimeError:
        cfg = {}
    quiet_s = (cfg.get("quiet_until") or {}).get(S.DAY_CODES[now.weekday()])
    quiet = S._to_min(quiet_s) if quiet_s else 0
    out = []
    for n in _load()["notes"]:
        if n.get("done") or n.get("date") != today:
            continue
        timed = bool(n.get("time"))
        at = S._to_min(n["time"]) if timed else MORNING
        end = at + 180 if timed else 22 * 60
        if at <= nm <= end:
            text = (f"Sir, a reminder: {n['text']}." if timed else f"Sir, don't forget: {n['text']}.")
            out.append({"key": f"note|{n['id']}|{n['date']}|{n.get('time', '')}", "title": n["text"],
                        "start": S._fmt(at), "quiet": at < quiet, "text": text})
    return out


# --- plain-speech parser -------------------------------------------------------------------
_ADD = [
    re.compile(r"\bremind\s+me\b\s*(?:to|about|that|of)?\s*(?P<t>.+)", re.I),
    re.compile(r"\b(?:don'?t|do\s+not|dont|never)\s+(?:let\s+me\s+)?forget\b\s*(?:to|about|that)?\s*(?P<t>.+)", re.I),
    re.compile(r"\b(?:make\s+sure|ensure)\s+(?:that\s+)?(?:i|we)\s+(?:don'?t|do\s+not|dont)\s+forget\b\s*(?:to|about)?\s*(?P<t>.+)", re.I),
    re.compile(r"\b(?:add|make|create|put|set|write)\s+(?:me\s+)?(?:a\s+|another\s+)?(?:new\s+)?(?:note|reminder|sticky\s*note)\b"
               r"(?:\s+for\s+me)?\s*(?:to|that|about|saying|called|for|:)?\s*(?P<t>.+)", re.I),
    re.compile(r"\b(?:add|put)\s+(?P<t>.+?)\s+(?:to|on|onto|in)\s+(?:my\s+|the\s+)?(?:reminders?|notes?|reminder\s+list|to-?do\s+list)\b", re.I),
]
_DONE = [
    re.compile(r"\b(?:cross|check|tick)\s+off\s+(?:the\s+|my\s+)?(?P<n>.+?)(?:\s+(?:from|on|off)\s+(?:my\s+|the\s+)?(?:list|reminders?|notes?))?\W*$", re.I),
    re.compile(r"\bmark\s+(?:the\s+|my\s+)?(?P<n>.+?)\s+(?:as\s+)?(?:done|complete|completed|finished|checked)\W*$", re.I),
]
_DELETE = re.compile(r"\b(?:remove|delete|get\s+rid\s+of|take)\s+(?:the\s+|my\s+)?(?P<n>.+?)\s+(?:from|off|on)\s+"
                     r"(?:my\s+|the\s+)?(?:reminders?|notes?|reminder\s+list|list)\b", re.I)
_CLEAR = re.compile(r"\b(?:clear|remove|delete|wipe|empty)\s+(?:all\s+)?(?:of\s+)?(?:my\s+|the\s+)?"
                    r"(?P<done>done\s+|completed\s+|finished\s+|checked\s+|crossed[- ]off\s+)?(?:reminders?|notes?)\b", re.I)
_LIST = re.compile(r"\b(?:what(?:'s|\s+is|\s+are|\s+do|\s+have)?|read|show|list|tell\s+me|do\s+i\s+have)\b[^.?!]{0,30}?"
                   r"\b(?:reminders?|notes?|remember|to-?do|forgetting)\b", re.I)
_NUM = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "ten": 10, "fifteen": 15,
        "twenty": 20, "thirty": 30, "forty": 40, "half": 0.5}
_REL = re.compile(r"\bin\s+(half\s+an?|an?|one|two|three|four|five|six|ten|fifteen|twenty|thirty|forty|\d+(?:\.\d+)?)\s*"
                  r"(hours?|hrs?|minutes?|mins?)\b", re.I)
_FRONT = {"to", "that", "about", "of", "for", "me", "please", "and", "then", "on", "at", "by", "the", "a", "an"}


def _split_when(rest: str, now: datetime | None = None) -> tuple[str, str, str]:
    """'call dad at 7 pm tomorrow' -> ('call dad', '2026-11-03', '19:00'). Missing parts are ''."""
    now = now or datetime.now()
    text, day, clock = rest, "", ""

    rel = _REL.search(text)
    if rel:
        word = rel.group(1).lower()
        n = 0.5 if word.startswith("half") else _NUM.get(word) or float(word)
        minutes = int(round(n * (60 if rel.group(2).lower().startswith("h") else 1)))
        due = now + timedelta(minutes=minutes)
        if due.date() == now.date():
            day, clock = due.date().isoformat(), f"{due.hour:02d}:{due.minute:02d}"
            text = text[:rel.start()] + " " + text[rel.end():]

    if not clock:
        m = re.search(r"\bat\s+noon\b", text, re.I)
        if m:
            clock = "12:00"
            text = text[:m.start()] + " " + text[m.end():]
        else:
            at = S._AT.search(text)
            if at:
                g = at.groups()
                h, mi, mer = (g[0], g[1], g[2]) if g[0] else (g[3], g[4], g[5])
                clock = S._hhmm(S._clock(h, mi, mer))
                text = text[:at.start()] + " " + text[at.end():]

    for m in S._DATEWORD.finditer(text):
        tok = re.sub(r"^(this|next) ", "", m.group(1).lower()).replace("tonight", "today")
        weekday = re.fullmatch(r"(mon|tues?|wed(?:nes)?|thu(?:rs?)?|fri|sat(?:ur)?|sun)(?:day)?s?", tok)
        if weekday and not tok.endswith(("day", "days")) \
                and not re.search(r"\b(on|this|next|for|by|until|before)\s+$", text[:m.start()], re.I):
            continue                       # "sun hat" is not Sunday
        try:
            day = S._to_date(tok.rstrip("s") if weekday and tok.endswith("days") else tok).isoformat()
        except ValueError:
            continue
        text = text[:m.start()] + " " + text[m.end():]
        break

    if clock and not day:
        day = (now.date() if S._to_min(clock) > now.hour * 60 + now.minute else now.date() + timedelta(days=1)).isoformat()
    words = text.split()
    while words and words[0].lower().strip(",") in _FRONT:
        words.pop(0)
    while words and words[-1].lower().strip(",.") in _FRONT | {"tonight", "today", "tomorrow"}:
        words.pop()
    return " ".join(words).strip(" .,;"), day, clock


def parse_note_request(text: str) -> dict | None:
    """Plain speech -> {"action": add|done|delete|clear|list, ...}, or None if it is not about notes."""
    t = " ".join(text.replace("’", "'").split())
    if not t:
        return None
    if not S._QUESTION.search(t):
        for rx in _ADD:
            m = rx.search(t)
            if m:
                what, day, clock = _split_when(m.group("t"))
                if what:
                    return {"action": "add", "text": what, "date": day, "time": clock}
    for rx in _DONE:
        m = rx.search(t)
        if m:
            return {"action": "done", "note": m.group("n").strip(" .,")}
    m = _DELETE.search(t)
    if m:
        return {"action": "delete", "note": m.group("n").strip(" .,")}
    m = _CLEAR.search(t)
    if m and not S._DATEWORD.search(t):
        return {"action": "clear", "done_only": bool(m.group("done"))}
    if _LIST.search(t) and not re.search(r"\bremind\s+me\b", t, re.I):
        return {"action": "list"}
    return None