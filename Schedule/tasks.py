"""Tasks with deadlines: "I have a history essay due Friday, it'll take about 4 hours."

A task has a due date, an estimate and a priority. Iris splits the work that is left into sessions
(normal flexible events linked to the task) across your free time before the due date, and keeps
that plan up to date:

  * progress ("I did 45 minutes of the essay") lowers what is left; a session that passed without
    progress counts as missed, so its time is planned again later;
  * priority is the higher of what you said (importance) and how urgent the task has become
    (urgency rises as the due date gets close, or when the work left is large compared with the
    free time left);
  * anything that would take time away from a task (deleting or moving a session, clearing a day,
    putting an event on top of a session) is checked against the deadline first, and risky or
    impossible changes ask before they happen.

Planning is incremental: sessions that are already planned stay where they are; only missing time
is added (or surplus removed), so the plan does not jump around every time it is checked.
"""
from __future__ import annotations

import math
import re
import uuid
from datetime import date, datetime, timedelta

from . import permission
from .rules import _bumpable, _busy, _free, _off, _shows
from .store import _load, _lock, _save
from .timeparse import _fmt, _hhmm, _pretty_day, _to_date, _to_min

LEVELS = ["low", "normal", "high"]
RANK = {name: i for i, name in enumerate(LEVELS)}

DEFAULTS = {
    "daily_cap_minutes": 180,      # at most this much task work planned on one day (all tasks together)
    "min_session_minutes": 30,     # never plan a session shorter than this (except the very last bit)
    "max_session_minutes": 90,
    "buffer_days": {"high": 1, "normal": 1, "low": 0},   # finish this many days before the due date
    "urgent_days": 2,              # due within this many days -> treated as high priority
    "soon_days": 4,                # due within this many days -> at least normal
    "behind_ratio": 0.6,           # work left > 60% of the free time left -> treated as high
}


# --- helpers --------------------------------------------------------------------------------
def _settings(data: dict) -> dict:
    cfg = dict(DEFAULTS)
    cfg.update((data.get("settings") or {}).get("tasks") or {})
    buf = dict(DEFAULTS["buffer_days"])
    buf.update(cfg.get("buffer_days") or {})
    cfg["buffer_days"] = buf
    return cfg


def _now() -> tuple[date, int]:
    now = datetime.now()
    return now.date(), now.hour * 60 + now.minute


def _open(data: dict) -> list[dict]:
    return [t for t in data.get("tasks", []) if t.get("status", "open") == "open"]


def _remaining(task: dict) -> int:
    return max(0, int(task.get("estimate", 0)) - int(task.get("done", 0)))


def _due(task: dict) -> date:
    return date.fromisoformat(task["due"])


def _due_label(task: dict, today: date) -> str:
    d = _due(task)
    word = "today" if d == today else "tomorrow" if d == today + timedelta(days=1) else _pretty_day(d)
    return word + (f" {_fmt(_to_min(task['due_time']))}" if task.get("due_time") else "")


def _hours(minutes: int) -> str:
    """90 -> '1.5 hours', 60 -> '1 hour', 45 -> '45 minutes'."""
    if minutes < 60:
        return f"{minutes} minutes"
    h = minutes / 60
    text = f"{h:.1f}".rstrip("0").rstrip(".")
    return f"{text} hour{'s' if h != 1 else ''}"


def _session_len(data: dict, task: dict) -> int:
    cfg = _settings(data)
    want = int(task.get("session") or (data.get("settings") or {}).get("session_minutes", 60) or 60)
    return max(cfg["min_session_minutes"], min(cfg["max_session_minutes"], want))


def _window(data: dict, day: date, today: date, now_min: int) -> tuple[int, int]:
    windows = data["settings"]["study_window"]
    key = "weekend" if (day.weekday() >= 5 or _off(data, day)) else "weekday"
    lo, hi = (_to_min(x) for x in windows[key])
    if day == today:
        lo = max(lo, math.ceil(now_min / 15) * 15)
    return lo, hi


def _last_day(task: dict, today: date, buffer: int) -> date:
    """The last day work may be planned on. Due 'Friday' (no time) means finished before Friday."""
    last = _due(task) - timedelta(days=0 if task.get("due_time") else 1)
    return max(today, last - timedelta(days=buffer)) if buffer else last


def _hi_on_due_day(task: dict, day: date, hi: int) -> int:
    if task.get("due_time") and day == _due(task):
        return min(hi, _to_min(task["due_time"]))
    return hi


def _sessions(data: dict, task_id: str) -> list[dict]:
    return [ev for ev in data["events"] if ev.get("task") == task_id]


def _future(ev: dict, today: date, now_min: int) -> bool:
    d = date.fromisoformat(ev["date"])
    return d > today or (d == today and _to_min(ev["end"]) > now_min)


def _planned(data: dict, task: dict, today: date, now_min: int) -> int:
    """Minutes of this task's sessions that are still ahead (an ongoing session counts too)."""
    total = 0
    for ev in _sessions(data, task["id"]):
        if _future(ev, today, now_min):
            start = _to_min(ev["start"])
            if ev["date"] == today.isoformat():
                start = max(start, now_min)
            total += max(0, _to_min(ev["end"]) - start)
    return total


def _task_minutes_on(data: dict, day: date) -> int:
    iso = day.isoformat()
    return sum(_to_min(ev["end"]) - _to_min(ev["start"]) for ev in data["events"]
               if ev.get("task") and ev.get("date") == iso)


def _blocked(task: dict, day: date) -> list[tuple[int, int]]:
    """Slots the user removed this task from: never plan it there again."""
    iso = day.isoformat()
    return [(_to_min(b["start"]), _to_min(b["end"])) for b in task.get("blocked", []) if b.get("date") == iso]


def _gaps(data: dict, task: dict, day: date, today: date, now_min: int, bump: bool = False) -> list[tuple[int, int]]:
    lo, hi = _window(data, day, today, now_min)
    hi = _hi_on_due_day(task, day, hi)
    if hi <= lo:
        return []
    if bump:
        # A high-priority task may push automatically planned goal sessions (e.g. physics self-study)
        # aside, never your own appointments or anything fixed.
        data = dict(data, events=[e for e in data["events"] if not _goal_session(e)])
    gaps = _free(data, day, lo, hi)
    for b_start, b_end in _blocked(task, day):
        cut = []
        for a, b in gaps:
            if b_end <= a or b_start >= b:
                cut.append((a, b))
                continue
            if a < b_start:
                cut.append((a, b_start))
            if b_end < b:
                cut.append((b_end, b))
        gaps = cut
    return [(a, b) for a, b in gaps if b > a]


def _goal_session(ev: dict) -> bool:
    """An automatically planned goal session (not homework, not a task, not something you added)."""
    return bool(ev.get("auto")) and not ev.get("task") and _bumpable(ev)


def _days(task: dict, today: date, last: date) -> list[date]:
    skip = set(task.get("skip_dates", []))
    return [today + timedelta(days=i) for i in range((last - today).days + 1)
            if (today + timedelta(days=i)).isoformat() not in skip]


def _capacity(data: dict, task: dict, today: date, now_min: int, last: date) -> int:
    """Free minutes this task could still use up to `last` (gaps of 30+ minutes, daily cap)."""
    cfg = _settings(data)
    total = 0
    for day in _days(task, today, last):
        room = max(0, cfg["daily_cap_minutes"] - _task_minutes_on(data, day))
        free = sum(b - a for a, b in _gaps(data, task, day, today, now_min) if b - a >= cfg["min_session_minutes"])
        total += min(room, free)
    return total


# --- priority -------------------------------------------------------------------------------
def effective_priority(data: dict, task: dict, today: date | None = None, now_min: int | None = None) -> str:
    """The higher of the importance the user gave and the urgency the task has reached."""
    if today is None or now_min is None:
        today, now_min = _now()
    cfg = _settings(data)
    importance = RANK.get(task.get("importance", "normal"), 1)
    left = _remaining(task)
    days_left = (_due(task) - today).days
    urgency = 0
    if left > 0:
        free = _planned(data, task, today, now_min) + _capacity(data, task, today, now_min, _last_day(task, today, 0))
        if days_left <= cfg["urgent_days"] or left > cfg["behind_ratio"] * max(free, 1):
            urgency = 2
        elif days_left <= cfg["soon_days"]:
            urgency = 1
    return LEVELS[max(importance, urgency)]


# --- planning -------------------------------------------------------------------------------
def _new_id(data: dict) -> str:
    used = {ev.get("id") for ev in data["events"]} | {t.get("id") for t in data.get("tasks", [])}
    while True:
        new = uuid.uuid4().hex[:4]
        if new not in used:
            return new


def _overlaps_other(data: dict, ev: dict) -> bool:
    """Does this task session now sit on top of something else (school is back, an event was added)?"""
    day = date.fromisoformat(ev["date"])
    s, e = _to_min(ev["start"]), _to_min(ev["end"])
    for b_start, b_end, _title in _busy(data, day, ignore=ev["id"]):
        if s < b_end and b_start < e:
            return True
    return False


def _place(data: dict, task: dict, need: int, today: date, now_min: int, last: date, bump: bool,
           placed: list[str], bumped: list[dict]) -> int:
    """Spread `need` minutes over the days up to `last`, one session per day per pass, earliest days
    first. Returns the minutes that could not be placed."""
    cfg = _settings(data)
    session = _session_len(data, task)
    days = _days(task, today, last)
    progress = True
    while need > 0 and progress:
        progress = False
        for day in days:
            if need <= 0:
                break
            room = cfg["daily_cap_minutes"] - _task_minutes_on(data, day)
            want = min(session, need, room)
            smallest = min(cfg["min_session_minutes"], need)
            if want < smallest:
                continue
            gaps = _gaps(data, task, day, today, now_min, bump=bump)
            fits = [(a, b) for a, b in gaps if b - a >= want]
            if fits:
                a, length = fits[0][0], want
            else:
                big = [(a, b) for a, b in gaps if b - a >= smallest]
                if not big:
                    continue
                a, b = max(big, key=lambda g: g[1] - g[0])
                length = min(want, b - a)
            if bump:
                for other in [e for e in data["events"] if _goal_session(e) and e.get("date") == day.isoformat()
                              and _to_min(e["start"]) < a + length and a < _to_min(e["end"])]:
                    data["events"].remove(other)
                    bumped.append(other)
            data["events"].append({"id": _new_id(data), "title": task["title"], "kind": "flexible",
                                   "date": day.isoformat(), "start": _hhmm(a), "end": _hhmm(a + length),
                                   "auto": True, "task": task["id"]})
            placed.append(f"{_pretty_day(day)} {_fmt(a)}-{_fmt(a + length)}")
            need -= length
            progress = True
    return need


def _trim(data: dict, task: dict, surplus: int, today: date, now_min: int) -> None:
    """More time is planned than is left: drop (or shorten) the latest automatic sessions."""
    future = sorted((ev for ev in _sessions(data, task["id"]) if ev.get("auto") and _future(ev, today, now_min)
                     and not (ev["date"] == today.isoformat() and _to_min(ev["start"]) <= now_min)),
                    key=lambda ev: (ev["date"], ev["start"]), reverse=True)
    for ev in future:
        if surplus <= 0:
            break
        length = _to_min(ev["end"]) - _to_min(ev["start"])
        if length <= surplus or length - surplus < 15:
            data["events"].remove(ev)
            surplus -= length
        else:
            ev["end"] = _hhmm(_to_min(ev["end"]) - surplus)
            surplus = 0


def _reflow(data: dict, ev: dict, today: date, now_min: int, moved: list[str], unmet: list[str]) -> None:
    """Give an event that a high-priority task pushed aside a new slot (same day or up to a week later)."""
    length = _to_min(ev["end"]) - _to_min(ev["start"])
    first = date.fromisoformat(ev["date"])
    for offset in range(0, 8):
        day = first + timedelta(days=offset)
        if day < today:
            continue
        lo, hi = _window(data, day, today, now_min)
        fit = [(a, b) for a, b in _free(data, day, lo, hi) if b - a >= length]
        if fit:
            a = fit[0][0]
            data["events"].append(dict(ev, date=day.isoformat(), start=_hhmm(a), end=_hhmm(a + length)))
            moved.append(f"{ev['title']} to {_pretty_day(day)} {_fmt(a)}")
            return
    unmet.append(f"{ev['title']} on {_pretty_day(first)} could not be moved, so I removed it")


def _plan(data: dict, today: date, now_min: int, only: str | None = None) -> dict:
    """Bring every open task's plan up to date (in place). Returns what happened, per task id."""
    report: dict[str, dict] = {}
    # 0. Tidy titles saved before the title cleaner existed ("Have a chem lab report" -> "Chem lab report").
    for task in _open(data):
        tidy = clean_title(task["title"])
        if tidy and tidy != task["title"]:
            task["title"] = tidy
            for ev in _sessions(data, task["id"]):
                ev["title"] = tidy
    # 1. Sessions that something else now sits on top of (school is back, an event was added) go.
    for ev in [e for e in data["events"] if e.get("task") and e.get("auto") and _future(e, today, now_min)]:
        if _overlaps_other(data, ev):
            data["events"].remove(ev)
    # 2. Finished or deleted tasks keep no future sessions.
    live = {t["id"] for t in _open(data)}
    data["events"] = [e for e in data["events"] if not (e.get("task") and e["task"] not in live
                                                        and _future(e, today, now_min) and e.get("auto"))]
    # 3. Most urgent first: earliest due date, then the higher priority.
    tasks = sorted(_open(data), key=lambda t: (t["due"], -RANK[effective_priority(data, t, today, now_min)]))
    for task in tasks:
        if only and task["id"] != only:
            continue
        cfg = _settings(data)
        level = effective_priority(data, task, today, now_min)
        need = _remaining(task) - _planned(data, task, today, now_min)
        info = {"placed": [], "moved": [], "unmet": [], "tight": False, "level": level, "short": 0}
        if need < 0:
            _trim(data, task, -need, today, now_min)
        elif need > 0:
            buffer = int(cfg["buffer_days"].get(level, 1))
            if level == "high":
                buffer = max(buffer, 1)
            bumped: list[dict] = []
            left = _place(data, task, need, today, now_min, _last_day(task, today, buffer), False, info["placed"], bumped)
            if left > 0 and buffer:
                info["tight"] = True        # only fits by using the days right before the due date
                left = _place(data, task, left, today, now_min, _last_day(task, today, 0), False, info["placed"], bumped)
            if left > 0 and level == "high":
                left = _place(data, task, left, today, now_min, _last_day(task, today, 0), True, info["placed"], bumped)
                for ev in sorted(bumped, key=lambda e: (e["date"], e["start"])):
                    _reflow(data, ev, today, now_min, info["moved"], info["unmet"])
            info["short"] = max(0, left)
        report[task["id"]] = info
    return report


def _raise_notes(data: dict, today: date, now_min: int) -> list[str]:
    """'The essay is due tomorrow, so I'm treating it as high priority now.' Said once per level."""
    lines = []
    for task in _open(data):
        level = effective_priority(data, task, today, now_min)
        if RANK[level] > RANK.get(task.get("importance", "normal"), 1) and task.get("raised") != level:
            task["raised"] = level
            lines.append(f"{task['title']} is due {_due_label(task, today)}, so I'm treating it as "
                         f"{level} priority now.")
    return lines


def _in_order(placed: list[str]) -> list[str]:
    """'Tue Nov 10 4:30 PM-5:30 PM' strings sorted by day and time."""
    def key(text: str):
        parts = text.split()
        day = datetime.strptime(f"{parts[1]} {parts[2]} {date.today().year}", "%b %d %Y")
        return day.month < date.today().month - 1, day, _to_min(parts[3] + " " + parts[4].split("-")[0].lower())
    try:
        return sorted(placed, key=key)
    except (ValueError, IndexError):
        return placed


def plan_tasks(only: str = "") -> str:
    """Bring the plan for every open task up to date: add sessions for time that is missing (missed
    sessions, a new task, a bigger estimate), remove surplus, and say what changed."""
    today, now_min = _now()
    with _lock:
        data = _load()
        data.setdefault("tasks", [])
        report = _plan(data, today, now_min, only or None)
        notes = _raise_notes(data, today, now_min)
        _save(data)
    lines = []
    for task in _open(data):
        info = report.get(task["id"])
        if not info:
            continue
        if info["placed"]:
            lines.append(f"{task['title']}: planned {', '.join(_in_order(info['placed']))}.")
        if info["moved"]:
            lines.append("Moved to make room: " + "; ".join(info["moved"]) + ".")
        if info["short"]:
            free = _capacity(data, task, today, now_min, _last_day(task, today, 0))
            lines.append(f"{task['title']} does not fit: {_hours(_remaining(task))} left, but only "
                         f"{_hours(_planned(data, task, today, now_min))} could be planned before it is due "
                         f"({_hours(free)} more free). Move something, allow a longer day, or change the estimate.")
        elif info["tight"] and info["placed"]:
            lines.append(f"{task['title']} only fits by using the last day before it is due.")
    return " ".join(lines + notes)


# --- the impact of a change on deadlines ------------------------------------------------------
def _status(data: dict, task: dict, today: date, now_min: int) -> str:
    """'safe' (fits with the buffer), 'risky' (only without the buffer) or 'impossible'."""
    left = _remaining(task)
    have = _planned(data, task, today, now_min)
    if have >= left:
        return "safe"
    level = effective_priority(data, task, today, now_min)
    buffer = max(int(_settings(data)["buffer_days"].get(level, 1)), 1 if level == "high" else 0)
    if have + _capacity(data, task, today, now_min, _last_day(task, today, buffer)) >= left:
        return "safe"
    if have + _capacity(data, task, today, now_min, _last_day(task, today, 0)) >= left:
        return "risky"
    return "impossible"


def check_change(before: dict, after: dict, action: str) -> tuple[bool, str]:
    """Compare the schedule before and after a change. Returns (ask_first, message). The message
    is '' when no task loses time. High-priority tasks always ask before losing time; the others
    only when the deadline is at risk."""
    today, now_min = _now()
    ask, parts = False, []
    for task in _open(before):
        lost = _planned(before, task, today, now_min) - _planned(after, task, today, now_min)
        if lost <= 0:
            continue
        twin = next((t for t in _open(after) if t["id"] == task["id"]), task)
        level = effective_priority(before, task, today, now_min)
        status = _status(after, twin, today, now_min)
        cap = _capacity(after, twin, today, now_min, _last_day(twin, today, 0)) + _planned(after, twin, today, now_min)
        name, due = task["title"], _due_label(task, today)
        if status == "safe":
            parts.append(f"That takes {_hours(lost)} from {name} (due {due}); it still fits, I'll plan it elsewhere.")
        elif status == "risky":
            parts.append(f"That leaves {_hours(_remaining(task))} of {name} for the last day before it is due "
                         f"({due}). It only fits by cramming.")
        else:
            parts.append(f"{name} could no longer be finished on time: {_hours(_remaining(task))} left and only "
                         f"{_hours(cap)} free before it is due ({due}).")
        if level == "high" or status != "safe":
            ask = True
    return ask, " ".join(parts)


def guard(before: dict, after: dict, action: str, target: str) -> str | None:
    """Ask before a change that takes time from a task, when the rules say so. Returns a refusal
    message if the user said no, else None (go ahead)."""
    ask, message = check_change(before, after, action)
    if ask and not permission.ask(action, target, message + " Still go ahead?"):
        return "The user declined this time, so nothing changed. If they ask again, try again."
    return None


def block_slot(data: dict, ev: dict) -> None:
    """The user removed this session: never plan this task in that slot again."""
    task = next((t for t in data.get("tasks", []) if t["id"] == ev.get("task")), None)
    if task is None:
        return
    keep = [b for b in task.get("blocked", []) if b["date"] >= (date.today() - timedelta(days=7)).isoformat()]
    keep.append({"date": ev["date"], "start": ev["start"], "end": ev["end"]})
    task["blocked"] = keep


def replan_after_change(data: dict) -> str:
    """Called (inside the lock) after the schedule changed: re-plan tasks and say where time went."""
    today, now_min = _now()
    report = _plan(data, today, now_min)
    lines = []
    for task in _open(data):
        info = report.get(task["id"]) or {}
        if info.get("placed"):
            lines.append(f"{task['title']} moved to {', '.join(_in_order(info['placed']))}.")
        if info.get("short"):
            lines.append(f"{task['title']} no longer fits before it is due.")
    return " ".join(lines)


# --- tools the model can call ----------------------------------------------------------------
def _find(data: dict, key: str, include_done: bool = False) -> list[dict]:
    key = " ".join(str(key or "").lower().split())
    key = re.sub(r"^(?:the\s+)?(?:task|assignment|project)\s+(?:called|named)\s+", "", key)
    key = (clean_title(key) or key).lower()
    pool = data.get("tasks", []) if include_done else _open(data)
    if not key:
        return pool if len(pool) == 1 else []
    exact = [t for t in pool if t["id"] == key or t["title"].lower() == key]
    if exact:
        return exact
    words = [w for w in re.findall(r"[a-z0-9]+", key) if w not in ("the", "my", "a", "an", "task", "assignment")]
    def same(t: dict) -> bool:
        title = (clean_title(t["title"]) or t["title"]).lower()
        names = (title, t["title"].lower())
        return any(key in n or n in key for n in names) or bool(words and all(
            re.search(rf"\b{re.escape(w)}\b", title) for w in words))
    hits = [t for t in pool if same(t)]
    return hits


_LEAD_WORDS = re.compile(
    r"^(?:(?:ok|okay|so|hey|um|uh|also|and|well|iris|jarvis)\s+)*"
    r"(?:(?:i|we|you)(?:'ve|'ll|'m|'d)?\s+)?(?:(?:still|also|just|really)\s+)*"
    r"(?:have\s+got\s+to|have\s+to|has\s+to|need\s+to|needs\s+to|got\s+to|gotta|must|should|"
    r"have|has|got|'ve\s+got|there(?:'s|\s+is)|add|create|new|make)?\s*"
    r"(?:(?:do|doing|finish|finishing|complete|write|writing|study\s+for|studying\s+for|prepare\s+for|prep\s+for|"
    r"work\s+on|working\s+on|turn\s+in|hand\s+in|submit)\s+)?"
    r"(?:(?:a|an|the|my|our|this|that)\s+)?(?:(?:new\s+)?task\s*(?::|called|for)?\s*)?(?:(?:a|an|the|my)\s+)?", re.I)


def clean_title(text: str) -> str:
    """'have a chem lab report' / 'I need to finish my history essay' -> 'Chem lab report' / 'History essay'."""
    t = " ".join(str(text or "").replace("’", "'").split()).strip(" .,:;")
    for _ in range(3):                      # 'so I have to finish the ...' takes more than one pass
        new = _LEAD_WORDS.sub("", t, count=1).strip(" .,:;")
        if new == t or not new:
            break
        t = new
    t = re.sub(r"\s+(?:is|are|that's|which\s+is|that\s+is|it's|and|that|which|it)$", "", t, flags=re.I).strip()
    return t[:1].upper() + t[1:] if t else ""


def _minutes_from(hours=0, minutes=0) -> int:
    try:
        return int(round(float(hours or 0) * 60 + float(minutes or 0)))
    except (TypeError, ValueError):
        raise ValueError("give the time as a number of hours or minutes")


def _level(text: str) -> str:
    t = str(text or "normal").strip().lower()
    t = {"medium": "normal", "mid": "normal", "important": "high", "urgent": "high", "top": "high"}.get(t, t)
    if t not in RANK:
        raise ValueError("priority must be high, normal or low")
    return t


def add_task(title: str, due: str, hours: float = 0, minutes: int = 0, importance: str = "normal",
             due_time: str = "", session_minutes: int = 0) -> str:
    """Add a task with a deadline and an estimate ("history essay due Friday, about 4 hours") and plan
    its sessions into free time before the due date."""
    try:
        title = clean_title(title)
        if not title:
            return "Error: the task needs a title."
        total = _minutes_from(hours, minutes)
        if total <= 0:
            return f"Error: how long will {title} take? Give hours or minutes."
        if total > 100 * 60:
            return "Error: that estimate is over 100 hours; split it into smaller tasks."
        due_day = _to_date(due)
        today, _ = _now()
        if due_day < today:
            return f"Error: {_pretty_day(due_day)} has already passed."
        clock = _hhmm(_to_min(due_time)) if str(due_time or "").strip() else ""
        level = _level(importance)
        title = title[0].upper() + title[1:]
        with _lock:
            data = _load()
            data.setdefault("tasks", [])
            if any(t["title"].lower() == title.lower() for t in _open(data)):
                return f"Error: there is already an open task called {title}. Update it instead."
            task = {"id": _new_id(data), "title": title, "due": due_day.isoformat(), "due_time": clock,
                    "estimate": total, "done": 0, "importance": level, "status": "open",
                    "created": datetime.now().isoformat(timespec="seconds")}
            if session_minutes:
                task["session"] = int(session_minutes)
            data["tasks"].append(task)
            _save(data)
    except (ValueError, RuntimeError) as exc:
        return f"Error: {exc}"
    plan = plan_tasks(task["id"])
    head = (f"Added task: {title}, due {_due_label(task, today)}, about {_hours(total)}, "
            f"{level} priority [{task['id']}].")
    return head + (" " + plan if plan else "")


def list_tasks(include_done: bool = False) -> str:
    """Open tasks, soonest due first: priority, what is left and the next planned session."""
    today, now_min = _now()
    data = _load()
    pool = data.get("tasks", []) if include_done else _open(data)
    if not pool:
        return "You have no tasks with deadlines."
    lines = []
    for t in sorted(pool, key=lambda t: (t.get("status") != "open", t["due"])):
        if t.get("status") != "open":
            lines.append(f"{t['title']} (done) [{t['id']}]")
            continue
        level = effective_priority(data, t, today, now_min)
        nxt = sorted((ev for ev in _sessions(data, t["id"]) if _future(ev, today, now_min)),
                     key=lambda ev: (ev["date"], ev["start"]))
        when = (f", next session {_pretty_day(date.fromisoformat(nxt[0]['date']))} {_fmt(_to_min(nxt[0]['start']))}"
                if nxt else ", nothing planned")
        raised = f" (was {t.get('importance', 'normal')})" if level != t.get("importance", "normal") else ""
        lines.append(f"{t['title']}: due {_due_label(t, today)}, {_hours(_remaining(t))} left of "
                     f"{_hours(int(t['estimate']))}, {level} priority{raised}{when} [{t['id']}]")
    return "; ".join(lines)


def update_task(task: str, title: str = "", due: str = "", hours: float = 0, minutes: int = 0,
                importance: str = "", due_time: str = "") -> str:
    """Change a task: its title, due date, total estimate (hours/minutes = the NEW total) or importance."""
    try:
        with _lock:
            data = _load()
            hits = _find(data, task)
            if not hits:
                return f"Error: no open task matches '{task}'."
            if len(hits) > 1:
                return "Error: several tasks match: " + ", ".join(f"{t['title']} [{t['id']}]" for t in hits)
            t = hits[0]
            changed = []
            if title and clean_title(title):
                t["title"] = clean_title(title)
                for ev in _sessions(data, t["id"]):
                    ev["title"] = t["title"]
                changed.append(f"title {t['title']}")
            if due:
                t["due"] = _to_date(due).isoformat()
                changed.append(f"due {_due_label(t, date.today())}")
            if str(due_time or "").strip():
                t["due_time"] = _hhmm(_to_min(due_time))
            total = _minutes_from(hours, minutes)
            if total > 0:
                t["estimate"] = total
                changed.append(f"estimate {_hours(total)}")
            if importance:
                t["importance"] = _level(importance)
                t.pop("raised", None)
                changed.append(f"{t['importance']} priority")
            if not changed:
                return "Error: nothing to change. Give a new title, due date, estimate or priority."
            _save(data)
    except (ValueError, RuntimeError) as exc:
        return f"Error: {exc}"
    plan = plan_tasks()
    return f"Updated {t['title']}: " + ", ".join(changed) + "." + (" " + plan if plan else "")


def log_task_progress(task: str, minutes: int = 0, done: bool = False) -> str:
    """Record work on a task ("I did 45 minutes of the essay") or mark it finished (done=True)."""
    try:
        with _lock:
            data = _load()
            hits = _find(data, task)
            if not hits:
                return f"Error: no open task matches '{task}'."
            if len(hits) > 1:
                return "Error: several tasks match: " + ", ".join(f"{t['title']} [{t['id']}]" for t in hits)
            t = hits[0]
            if done:
                t["status"] = "done"
                t["done"] = max(int(t.get("done", 0)), int(t["estimate"]))
                t["finished"] = datetime.now().isoformat(timespec="seconds")
                _save(data)
            else:
                add = int(minutes or 0)
                if add <= 0:
                    return "Error: how many minutes did you work on it?"
                t["done"] = int(t.get("done", 0)) + add
                if t["done"] >= int(t["estimate"]):
                    t["status"] = "done"
                    t["finished"] = datetime.now().isoformat(timespec="seconds")
                _save(data)
    except (ValueError, RuntimeError) as exc:
        return f"Error: {exc}"
    plan_tasks()                     # finished: future sessions go; progress: surplus sessions go
    if t["status"] == "done":
        return f"Marked {t['title']} as done."
    return f"Logged {_hours(int(minutes))} on {t['title']}; {_hours(_remaining(t))} left."


def delete_task(task: str) -> str:
    """Remove a task and its planned sessions."""
    with _lock:
        data = _load()
        hits = _find(data, task, include_done=True)
        if not hits:
            return f"Error: no task matches '{task}'."
        if len(hits) > 1:
            return "Error: several tasks match: " + ", ".join(f"{t['title']} [{t['id']}]" for t in hits)
        t = hits[0]
        today, now_min = _now()
        data["tasks"].remove(t)
        data["events"] = [e for e in data["events"] if not (e.get("task") == t["id"] and _future(e, today, now_min))]
        _save(data)
    return f"Removed the task {t['title']} and its planned sessions."


def tasks_view() -> list[dict]:
    """The open tasks (and ones finished in the last week) for the SCHEDULE tab."""
    today, now_min = _now()
    try:
        data = _load()
    except RuntimeError:
        return []
    out = []
    week_ago = (today - timedelta(days=7)).isoformat()
    for t in sorted(data.get("tasks", []), key=lambda t: (t.get("status") != "open", t["due"])):
        if t.get("status") != "open" and str(t.get("finished", ""))[:10] < week_ago:
            continue
        open_ = t.get("status", "open") == "open"
        level = effective_priority(data, t, today, now_min) if open_ else t.get("importance", "normal")
        out.append({"id": t["id"], "title": t["title"], "due": _due_label(t, today), "done": not open_,
                    "estimate": int(t["estimate"]), "progress": min(int(t.get("done", 0)), int(t["estimate"])),
                    "planned": _planned(data, t, today, now_min) if open_ else 0,
                    "priority": level, "raised": open_ and level != t.get("importance", "normal"),
                    "status": _status(data, t, today, now_min) if open_ else "done"})
    return out


def spoken_plan(task_id: str) -> str:
    """'I planned 4 sessions before it's due, the first on Mon Nov 9 at 4:30 PM.'"""
    today, now_min = _now()
    data = _load()
    sessions = sorted((ev for ev in _sessions(data, task_id) if _future(ev, today, now_min)),
                      key=lambda ev: (ev["date"], ev["start"]))
    if not sessions:
        return "I could not plan any sessions for it yet."
    first = sessions[0]
    day = date.fromisoformat(first["date"])
    word = "today" if day == today else "tomorrow" if day == today + timedelta(days=1) else f"on {_pretty_day(day)}"
    n = len(sessions)
    return (f"I planned {n} session{'s' if n != 1 else ''} before it's due, the first {word} at "
            f"{_fmt(_to_min(first['start']))}.")