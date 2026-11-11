"""Direct paths: plain spoken requests turned into tool arguments without the model."""
from __future__ import annotations

import copy
import math
import re
from datetime import date, datetime, timedelta

from .rules import _applies, _bumpable, _busy, _conflict, _describe, _find, _free, _is_school, _new_id, _off, _shows, _span, _suggest
from .store import DEFAULT, _load, _lock, _save
from .timeparse import DAY_CODES, WEEKDAYS, _MONTHS, _WEEKDAY_NAMES, _fmt, _hhmm, _pretty_day, _to_date, _to_days, _to_min, _week_start


# --- a deterministic shortcut for plain "add ..." requests ---------------------------------
# A small local model sometimes talks about adding an event without calling add_event. For the
# common spoken forms ("add an hour of physics at 2 pm", "set a physics session for 3 to 4 pm")
# the request is parsed here instead, so it always works and is fast.
_INTENT = re.compile(r"\b(add|schedule|set|book|put|create|block|slot|pencil)\b", re.I)
_QUESTION = re.compile(r"^\s*(?:(?:hey|ok|okay|so|and|iris|jarvis|well|yes|yeah)[ ,]+)*"
                       r"(what|when|where|why|how|which|who|did|does|do|is|are)\b", re.I)
_MER = r"(a\.?\s?m\.?|p\.?\s?m\.?)"
_RANGE = re.compile(rf"(\d{{1,2}})(?::(\d\d))?\s*{_MER}?\s*(?:to|until|till|through|-)\s*(\d{{1,2}})(?::(\d\d))?\s*{_MER}?", re.I)
_AT = re.compile(rf"(?:\bat\b|@|\bfrom\b)\s*(\d{{1,2}})(?::(\d\d))?\s*{_MER}?|\b(\d{{1,2}})(?::(\d\d))?\s*{_MER}", re.I)
_DUR = re.compile(r"\b(half an? hour|(?:an?|one|\d+(?:\.\d+)?)[ -]?(?:hours?|hrs?|minutes?|mins?))\b(?:\s+of)?", re.I)
_DAYWORD = re.compile(r"\b(today|tonight|tomorrow|(?:on |this |next )?(?:mon|tues?|wed(?:nes)?|thu(?:rs?)?|fri|sat(?:ur)?|sun)(?:day)?)\b", re.I)
_FILL = {"a", "an", "the", "to", "my", "please", "can", "could", "you", "also", "first", "for", "from",
         "at", "on", "in", "into", "me", "iris", "jarvis", "hey", "ok", "okay", "so", "and", "then", "it",
         "that", "this", "of", "schedule", "calendar", "new", "yes", "yeah", "thanks", "thank", "now",
         "another", "one", "other", "again", "more", "second", "third", "also"}


def _clock(h: str, m: str | None, mer: str | None) -> int:
    """Clock time in minutes. With no am/pm: 6-11 means the next one still ahead today
    (so 'at 7' at 6:30 AM is 7 AM, at 5 PM it is 7 PM); 1-5 is PM; 12 is noon."""
    hour, minute = int(h), int(m or 0)
    if hour >= 13 or hour == 0:
        return hour * 60 + minute                       # already a 24-hour time
    if mer:
        pm = mer.lower().replace(".", "").replace(" ", "").startswith("p")
        return (hour % 12 + (12 if pm else 0)) * 60 + minute
    if hour == 12:
        return 12 * 60 + minute
    now = datetime.now()
    am_ahead = 6 <= hour <= 11 and hour * 60 + minute > now.hour * 60 + now.minute
    return (hour if am_ahead else hour + 12) * 60 + minute


def _dur_minutes(t: str) -> int | None:
    """'a 30-minute session' / 'an hour of' / 'half an hour' -> minutes."""
    dur = _DUR.search(t)
    if not dur:
        return None
    w = dur.group(1).lower()
    if w.startswith("half"):
        return 30
    n = 1.0 if w.split()[0] in ("a", "an", "one") else float(re.match(r"[\d.]+", w).group())
    return int(n * (1 if "min" in w else 60))


def parse_add_request(text: str, previous: str = "") -> dict | None:
    """Turn 'add an hour of physics at 2 pm today' into add_event arguments, or None
    if the sentence is not a clear add request. previous = the user's message before this one,
    used when the intent and the details were said in separate sentences."""
    for raw in (text, f"{previous} {text}".strip() if previous else ""):
        if not raw:
            continue
        if _QUESTION.search(raw if raw is text else text):
            continue
        t = " ".join(raw.replace(",", " ").split())
        t = re.sub(r"\b(?:to|in|on|into|from)?\s*(?:the|my|our)\s+(?:schedule|calendar)\b", " ", t, flags=re.I)
        if not _INTENT.search(t):
            continue
        span = _RANGE.search(t)
        start = end = None
        if span:
            h1, m1, a1, h2, m2, a2 = span.groups()
            if a1 or a2:
                s = _clock(h1, m1, a1 or a2)
                e = _clock(h2, m2, a2 or a1)
                if e <= s and not a1:
                    s -= 12 * 60 if s >= 12 * 60 else 0
            else:
                s, e = _clock(h1, m1, None), _clock(h2, m2, None)
                if e <= s:
                    e += 12 * 60 if e < 12 * 60 else 0
            length = _dur_minutes(t)
            if length and not (0 <= s < e <= 24 * 60 and e - s <= 12 * 60):
                e = s + length        # the spoken end time was garbled; trust "a 30-minute session"
            if not (0 <= s < e <= 24 * 60):
                continue
            start, end = s, e
            cut = span
        else:
            at = None
            for at in _AT.finditer(t):
                pass                     # the last time mentioned
            if not at:
                continue
            g = at.groups()
            h, m, mer = (g[0], g[1], g[2]) if g[0] else (g[3], g[4], g[5])
            start = _clock(h, m, mer)
            minutes = _dur_minutes(t) or 60
            end = start + minutes
            if end > 24 * 60:
                continue
            cut = at

        before = t[:cut.start()]
        after = t[cut.end():]
        verbs = list(_INTENT.finditer(before))
        title_src = before[verbs[-1].end():] if verbs else before
        if not re.sub(r"[^a-z]", "", _DUR.sub("", title_src).lower().replace("jarvis", "").replace("iris", "")):
            title_src = after
        title_src = _DUR.sub(" ", title_src)
        day = _DAYWORD.search(t)
        title_src = _DAYWORD.sub(" ", title_src)
        title_src = re.sub(r"\bto (the|my) schedule\b", " ", title_src, flags=re.I)
        title_src = re.sub(r"\bfor an? (study|practice|prep|review)\b", r"\1", title_src, flags=re.I)
        words = [w for w in re.findall(r"[A-Za-z][A-Za-z'+&-]*", title_src)]
        while words and words[0].lower() in _FILL:
            words.pop(0)
        while words and words[-1].lower() in _FILL:
            words.pop()
        if not words or len(words) > 6:
            continue
        title = " ".join(words)
        title = title[0].upper() + title[1:]
        dayword = day.group(1).lower().replace("tonight", "today") if day else "today"
        dayword = re.sub(r"^(on|this|next) ", "", dayword)
        return {"title": title, "start": _hhmm(start), "end": _hhmm(end), "date": dayword}
    return None


_RENAME = re.compile(r"\b(rename|name|call|label|title|retitle)\b", re.I)


def find_rename_target(text: str) -> tuple[str, str] | str | None:
    """'name that session calculus' / 'rename the 6 to 7 session to chemistry' ->
    (event_id, new_title). A string is a message to say to the user; None = not a rename."""
    t = " ".join(text.replace(",", " ").split())
    if _QUESTION.search(t):
        return None
    verbs = list(_RENAME.finditer(t))
    if not verbs:
        return None
    verb = verbs[-1]
    head, tail = t[:verb.start()], t[verb.end():]

    split = re.match(r"^(.*?)\b(?:to|as|into)\b\s+(?!\d)(.+)$", tail, re.I)   # not "7 to 8"
    if split:                                    # "rename <which> to <new>"
        ref_text, new_src = f"{head} {split.group(1)}", split.group(2)
    else:                                        # "name it <new>" / "label it <new> for the 7 to 8 one"
        ref_text = head + " " + tail
        new_src = re.sub(r"^\s*(?:the\s+)?(?:it|that|this|them|those)\s*(?:one|session|event|block|slot)?\s*", "",
                         tail, flags=re.I)
    new_src = _RANGE.sub(" ", new_src)
    new_src = _AT.sub(" ", new_src)
    new_src = re.split(r"\b(?:or|and|but)\b", new_src, maxsplit=1, flags=re.I)[0]
    words = re.findall(r"[A-Za-z][A-Za-z'+&-]*", new_src)
    stop = _FILL | {"please", "thanks", "pm", "am", "session", "one", "event"}
    while words and words[0].lower() in stop - {"session", "one", "event"}:
        words.pop(0)
    while words and words[-1].lower() in stop:
        words.pop()
    if not words or len(words) > 5:
        return None
    new_title = " ".join(words)
    new_title = new_title[0].upper() + new_title[1:]

    try:
        data = _load()
    except RuntimeError:
        return None
    dayword = _DAYWORD.search(t)
    day = _to_date(re.sub(r"^(on|this|next) ", "", dayword.group(1).lower()).replace("tonight", "today")) \
        if dayword else date.today()
    todays = [ev for ev in data["events"] if _shows(data, ev, day)]

    cands: list[dict] = []
    span = _RANGE.search(ref_text)
    if span:
        h1, m1, a1, h2, m2, a2 = span.groups()
        mer = bool(a1 or a2)
        s1 = _clock(h1, m1, a1 or a2 if mer else None)
        e1 = _clock(h2, m2, a2 or a1 if mer else None)
        cands = [ev for ev in todays if _to_min(ev["start"]) == s1 and _to_min(ev["end"]) == e1] \
            or [ev for ev in todays if _to_min(ev["start"]) == s1]
    else:
        at = _AT.search(ref_text)
        if at:
            g = at.groups()
            h, m, mer = (g[0], g[1], g[2]) if g[0] else (g[3], g[4], g[5])
            cands = [ev for ev in todays if _to_min(ev["start"]) == _clock(h, m, mer)]
    if not cands:
        cands = [ev for ev in todays if ev["title"].lower() in ref_text.lower()]
    if not cands and re.search(r"\b(it|that|this|last|latest)\b", ref_text, re.I):
        recent = [ev for ev in data["events"] if ev.get("kind") != "fixed" and ev.get("date") == day.isoformat()]
        cands = recent[-1:]                       # the one added most recently
    if not cands:
        return "I could not tell which event to rename. Say the time, for example: rename the 6 to 7 PM session to calculus."
    if len(cands) > 1:
        cands = [ev for ev in cands if ev.get("kind") != "fixed"] or cands
    if len(cands) > 1:
        return "More than one event matches. Tell me the exact time, for example 6 to 7 PM."
    return cands[0]["id"], new_title


_NUMW = {"zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8}
_HW_DUR = re.compile(
    r"\b(?:(an?|one|two|three|four|five|six|seven|eight|\d+(?:\.\d+)?)\s*(?:and a half|and a quarter)?\s*"
    r"(hours?|hrs?|minutes?|mins?)|half an hour|an hour and a half|(\d+)\s*(?:and a half)\s*hours?)\b", re.I)


def parse_homework_request(text: str) -> tuple[str, int, str] | None:
    """'I have 3 hours of homework on thursday' -> ('day', 180, 'thursday');
    'set my homework to 90 minutes' -> ('default', 90, ''). None if it is not about the amount."""
    t = " ".join(text.lower().replace(",", " ").split())
    if not re.search(r"\b(homework|hw)\b", t) or _QUESTION.search(t):
        return None
    if _RANGE.search(t) or re.search(r"\bat\s+\d", t):        # clock times = an add request
        return None
    if re.search(r"\b(no|zero|none|without)\b[^.]{0,12}\b(homework|hw)\b|\b(homework|hw)\b[^.]{0,12}\b(is|are)\s+(zero|none)\b", t):
        minutes = 0
    else:
        m = None
        if "an hour and a half" in t:
            minutes = 90
        elif "half an hour" in t:
            minutes = 30
        else:
            m = re.search(r"\b(an?|one|two|three|four|five|six|seven|eight|\d+(?:\.\d+)?)\s*(and a half\s*)?"
                          r"(hours?|hrs?|minutes?|mins?)\b", t)
            if not m:
                return None
            n = 1.0 if m.group(1) in ("a", "an") else float(_NUMW.get(m.group(1), m.group(1)) if m.group(1) in _NUMW else m.group(1))
            if m.group(2):
                n += 0.5
            minutes = int(round(n * (60 if m.group(3).startswith("h") else 1)))
    day = _DAYWORD.search(t)
    dayword = re.sub(r"^(on|this|next) ", "", day.group(1)).replace("tonight", "today") if day else ""
    if dayword:
        return "day", minutes, dayword
    if re.search(r"\b(set|make|change|update|usually|every|each|per|default|normally|from now on)\b", t):
        return "default", minutes, ""
    return "day", minutes, "today"


_OFF_WORDS = re.compile(
    r"\b(?:days?\s+off|no\s+school|off\s+(?:from\s+)?school|in[- ]?service|school\s+(?:is\s+)?(?:closed|cancell?ed|off)|"
    r"(?:school|class(?:es)?)\s+(?:is\s+|are\s+)?(?:out|canceled)|holiday|snow\s+day|teacher\s+work\s+day)\b", re.I)
_UNDO_WORDS = re.compile(r"\b(undo|remove|cancel\s+(?:the\s+|that\s+)?days?\s+off|never\s*mind|nevermind|is\s+back\s+on|there\s+is\s+school|we\s+have\s+school|"
                         r"actually\s+(?:there|we)|not\s+(?:a\s+)?(?:day|days)\s+off)\b", re.I)
_DATEWORD = re.compile(
    r"\b(today|tonight|tomorrow|(?:(?:this|next)\s+)?(?:mon|tues?|wed(?:nes)?|thu(?:rs?)?|fri|sat(?:ur)?|sun)(?:day)?s?|"
    r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+\d{1,2}(?:st|nd|rd|th)?|\d{1,2}/\d{1,2})\b", re.I)


def _date_ranges(t: str) -> list[tuple[str, str]]:
    """Every day or range of days named in a sentence: 'today and tomorrow', 'monday through
    wednesday', 'november 24 to 28' -> [(start, end)] as YYYY-MM-DD, consecutive days merged."""
    tokens = list(_DATEWORD.finditer(t))
    if not tokens:
        return []
    days: set[date] = set()
    prev_end = None
    expand_next = False
    for i, m in enumerate(tokens):
        nxt = tokens[i + 1] if i + 1 < len(tokens) else None
        if nxt and re.fullmatch(r"\s*", t[m.end():nxt.start()]) and re.match(r"[A-Za-z]{3,}\.?\s+\d|\d+/", nxt.group(1)):
            continue                         # "Thursday Nov 26": the date says it all
        try:
            d = _to_date(re.sub(r"^(this|next) ", "", m.group(1).lower()).replace("tonight", "today"))
        except ValueError:
            continue
        gap = t[prev_end:m.start()] if prev_end is not None else ""
        if expand_next and days:
            last = max(days)
            if d > last:
                days.update(last + timedelta(days=i) for i in range(1, (d - last).days + 1))
        days.add(d)
        expand_next = bool(re.search(r"\b(through|thru|to|until|till)\b|-", t[m.end():m.end() + 12]))
        prev_end = m.end()
    if not days:
        return []
    ordered = sorted(days)
    ranges, start, end = [], ordered[0], ordered[0]
    for d in ordered[1:]:
        if (d - end).days == 1:
            end = d
        else:
            ranges.append((start.isoformat(), end.isoformat()))
            start = end = d
    ranges.append((start.isoformat(), end.isoformat()))
    return ranges


def parse_day_off_request(text: str) -> dict | None:
    """'mark today and tomorrow as days off from school' -> {"ranges": [(start, end)], "title": ..,
    "remove": False}. Dates come back as YYYY-MM-DD. None if it is not about days off."""
    t = " ".join(text.replace(",", " ").split())
    if not t or _QUESTION.search(t) or not _OFF_WORDS.search(t):
        return None
    ranges = _date_ranges(t)
    if not ranges:
        return None
    low = t.lower()
    title = "In-service day" if re.search(r"in[- ]?service", low) else \
            "Snow day" if "snow" in low else "Holiday" if "holiday" in low else "No school"
    return {"ranges": ranges, "title": title, "remove": bool(_UNDO_WORDS.search(t))}


_CLEAR_VERB = re.compile(r"\b(remove|clear|delete|wipe|empty|get\s+rid\s+of|take\s+off|take\s+out|cancel|drop)\b", re.I)
_CLEAR_ALL = re.compile(r"\b(all|everything|every\s+thing|whole|entire)\b", re.I)
_CLEAR_FILL = _FILL | {"remove", "clear", "delete", "wipe", "empty", "cancel", "drop", "get", "rid", "take", "off", "out",
                       "all", "everything", "items", "item", "events", "event", "stuff", "things", "thing", "sessions",
                       "session", "schedule", "schedules", "plans", "plan", "tasks", "task", "activities", "can", "thank",
                       "but", "just", "only", "both", "those", "these", "their", "its", "up", "from", "off"}


def parse_clear_request(text: str) -> dict | None:
    """'remove all items on the Monday schedule' / 'remove the homework and physics stuff and test
    prep on Monday and Tuesday' -> {"ranges": [...], "what": "homework;physics;test prep"} (what ''
    = everything flexible). None when it is not a clear-the-day request or names no day."""
    t = " ".join(text.replace(",", " ").split())
    if not t or _QUESTION.search(t) or not _CLEAR_VERB.search(t) or _OFF_WORDS.search(t):
        return None
    ranges = _date_ranges(t)
    if not ranges:
        return None
    verb = list(_CLEAR_VERB.finditer(t))[-1]
    body = t[verb.end():]
    names_src = _DATEWORD.sub(" ", body)
    names_src = re.sub(r"\b(?:on|for|from|during|in)\s+(?:the\s+)?(?:mondays?|tuesdays?|schedule)\b", " ", names_src, flags=re.I)
    parts = [p for p in re.split(r"\b(?:and|plus|then|as well as)\b", names_src, flags=re.I)]
    names = []
    for part in parts:
        words = re.findall(r"[A-Za-z][A-Za-z'+&-]*", part)
        words = [w for w in words if w.lower() not in _CLEAR_FILL]
        if words:
            names.append(" ".join(words).lower())
    if _CLEAR_ALL.search(body) and not names:
        names = []
    return {"ranges": ranges, "what": ";".join(names)}


_CONFIRM = re.compile(r"^\s*(?:(?:ok|okay|yes|yeah|yep|sure|please|iris|jarvis|just)[ ,]+)*"
                      r"(do it|go ahead|go for it|do that|yes|yeah|yep|sure|confirm(?:ed)?|approve|make it so|try again|again)(?:\s+please)?\W*$", re.I)


def is_confirmation(text: str) -> bool:
    """A bare 'do it' / 'yes' / 'go ahead': the user is answering the last thing they asked."""
    return bool(_CONFIRM.match(text or ""))


_PLACE_HINT = re.compile(
    r"\b(?:(?:how|wherever|whenever|whatever)(?:\s+(?:you|u))?\s+(?:see\s+fit|works?|fits?|is\s+best)|"
    r"as\s+you\s+see\s+fit|where(?:ver)?\s+(?:it\s+)?fits?|wherever|whenever|"
    r"find\s+(?:me\s+)?(?:some\s+|a\s+)?(?:time|spot|slot)|fit\s+(?:it|them|this|that)\s+in|"
    r"you\s+(?:pick|choose|decide)|(?:the\s+)?best\s+(?:time|spot|slot)|any\s?time|anywhere|"
    r"place\s+(?:it|them)|slot\s+(?:it|them)\s+in)\b", re.I)
_ANCHOR = re.compile(r"\b(after|before)\s+(?:my\s+|the\s+|our\s+)?([A-Za-z][A-Za-z'+&-]*)", re.I)
_ANCHOR_SKIP = {"that", "this", "it", "then", "i", "you", "we", "my", "the", "a", "an", "now", "lunch", "bed"}
_ONE_FOR = re.compile(
    r"\b(?:one|1|a\s+(?:session|block|slot))\s+for\s+"
    r"([A-Za-z][A-Za-z'+&-]*(?:\s+(?!and\b|one\b|a\b|then\b|on\b|this\b|next\b|today\b|tomorrow\b|tonight\b|"
    r"after\b|before\b|please\b|called\b|at\b)[A-Za-z][A-Za-z'+&-]*)?)", re.I)
_PLACE_FILL = _FILL | {"session", "sessions", "block", "blocks", "slot", "time", "hour", "hours",
                       "minutes", "week", "which", "how", "see", "fit", "up", "just", "later"}


def parse_place_request(text: str) -> dict | None:
    """'add 2 hours of test prep, one for math and one for chem, place it how you see fit' or
    'on Friday add a 1-hour session after my club called physics prep' -> place_event arguments.
    None when the sentence gives a clock time (parse_add_request handles it) or is not an add."""
    t = " ".join(text.replace(",", " ").split())
    if not t or _QUESTION.search(t):
        return None
    if not (_INTENT.search(t) or re.search(r"\b(?:find|make|get)\s+(?:me\s+)?(?:some\s+|a\s+)?(?:time|room)\b", t, re.I)):
        return None
    if _RANGE.search(t) or _AT.search(t) or re.search(r"\b(homework|hw)\b", t, re.I):
        return None
    anchor = next((m for m in _ANCHOR.finditer(t) if m.group(2).lower() not in _ANCHOR_SKIP), None)
    hint = _PLACE_HINT.search(t)
    total = _dur_minutes(t)
    if not (anchor or hint or total):
        return None

    day = _DAYWORD.search(t)
    dayword = re.sub(r"^(on|this|next) ", "", day.group(1).lower()).replace("tonight", "today") if day else ""
    within = "next week" if re.search(r"\bnext\s+week\b", t, re.I) and not day else "this week"

    subjects = [m.group(1).strip() for m in _ONE_FOR.finditer(t)]
    work = t[:anchor.start()] + " " + t[anchor.end():] if anchor else t
    for rx in (_PLACE_HINT, _DAYWORD, _ONE_FOR):
        work = rx.sub(" ", work)
    work = re.sub(r"\b(?:this|next)\s+week\b|\bfor\s+the\s+week\b", " ", work, flags=re.I)

    called = re.search(r"\b(?:called|named|titled|labell?ed)\s+(.+)$", work, re.I)
    if called:
        src = called.group(1)
    else:
        verbs = list(_INTENT.finditer(work))
        src = work[verbs[-1].end():] if verbs else work
    src = _DUR.sub(" ", src)
    words = re.findall(r"[A-Za-z][A-Za-z'+&-]*", src)
    while words and words[0].lower() in _PLACE_FILL:
        words.pop(0)
    while words and words[-1].lower() in _PLACE_FILL:
        words.pop()
    if len(words) > 6:
        return None
    base = " ".join(words)

    count_dur = len(_DUR.findall(t))
    if len(subjects) >= 2:
        per = total // len(subjects) if total and count_dur < len(subjects) else (total or 60)
        names = [f"{s[0].upper()}{s[1:]} {base}".strip() for s in subjects]
        args = {"titles": ";".join(names), "minutes": per or 60}
    else:
        title = base or "Study session"
        args = {"title": title[0].upper() + title[1:], "minutes": total or 60}
    if dayword:
        args["day"] = dayword
    if anchor:
        args["after" if anchor.group(1).lower() == "after" else "before"] = anchor.group(2).lower()
    if within != "this week":
        args["within"] = within
    return args


def sounds_like_add(text: str) -> bool:
    """An add request with numbers in it that parse_add_request could not read
    (e.g. speech recognition turned 6:40 into '6: 4')."""
    t = " ".join(text.split())
    return bool(_INTENT.search(t)) and bool(re.search(r"\d", t)) and not _QUESTION.search(t) \
        and not re.search(r"\b(homework|hw)\b", t, re.I)


# --- tasks with deadlines -------------------------------------------------------------------
_TASK_LIST = re.compile(r"\b(?:what(?:'s|\s+is|\s+do\s+i\s+have|\s+are|\s+have\s+i\s+got)?|show|list|tell\s+me|read)\b[^.?!]{0,40}?"
                        r"\b(?:due|deadlines?|tasks?|assignments?)\b", re.I)
_TASK_LEFT = re.compile(r"\bhow\s+(?:much|long)\s+(?:time\s+|work\s+)?(?:is\s+|do\s+i\s+have\s+)?left\s+(?:on|for|in)\s+"
                        r"(?:the\s+|my\s+)?(?P<n>.+?)\W*$", re.I)
_TASK_DONE = [
    re.compile(r"\b(?:i(?:'ve|\s+have|'m|\s+am)?\s+)?(?:just\s+)?(?:finished|completed|done\s+with|submitted|turned\s+in|handed\s+in)"
               r"\s+(?:the\s+|my\s+)?(?P<n>.+?)\W*$", re.I),
    re.compile(r"^(?:the\s+|my\s+)?(?P<n>.+?)\s+(?:is|are)\s+(?:all\s+)?(?:done|finished|complete|completed|submitted)\W*$", re.I),
    re.compile(r"\bmark\s+(?:the\s+|my\s+)?(?P<n>.+?)\s+(?:as\s+)?(?:done|finished|complete|completed)\W*$", re.I),
]
_TASK_WORK = re.compile(r"\bi\s+(?:just\s+)?(?:did|worked(?:\s+on)?|spent|put\s+in|got\s+in|studied|wrote|made)\b", re.I)
_TASK_LEVEL = [
    re.compile(r"\bmake\s+(?:the\s+|my\s+)?(?P<n>.+?)\s+(?:a\s+)?(?P<l>high|low|normal|medium|top)[\s-]+priority\b", re.I),
    re.compile(r"^(?:the\s+|my\s+)?(?P<n>.+?)\s+is\s+(?:a\s+)?(?P<l>high|low|normal|medium|top)[\s-]+priority\W*$", re.I),
]
_TASK_DELETE = re.compile(r"\b(?:remove|delete|cancel|drop)\s+(?:the\s+|my\s+)?(?:task\s+)?(?P<n>.+?)(?:\s+(?:task|assignment|project))?"
                          r"(?:\s+from\s+(?:my\s+)?(?:tasks|list))?\W*$", re.I)
_DUE = re.compile(r"\b(?:is\s+|are\s+|that's\s+|that\s+is\s+|which\s+is\s+|it's\s+)?(?:due|deadline\s+is|deadline)\b", re.I)
_TASK_LEAD = re.compile(r"^(?:(?:ok|okay|so|hey|iris|jarvis|also|and|um|uh)\s+)*(?:i\s+have|i've\s+got|i\s+got|i\s+need\s+to\s+(?:do|finish|write|study\s+for)|"
                        r"there's|there\s+is|we\s+have|add|create|new|make)?\s*(?:a\s+|an\s+)?(?:new\s+)?(?:task\s*(?::|called|for)?\s*)?"
                        r"(?:the\s+|my\s+|a\s+|an\s+)?", re.I)
_HIGH = re.compile(r"\b(?:high|top)[\s-]+priority|\bimportant\b|\burgent\b|\b(?:big|huge)\s+(?:\w+\s+)?(?:test|exam|project|deal|essay|presentation)|\bmajor\b|\bfinal\b|"
                   r"\bmidterm\b|\bexam\b|\bcounts?\s+(?:for\s+)?a\s+lot\b", re.I)
_LOW = re.compile(r"\blow[\s-]+priority|\bnot\s+(?:that\s+|very\s+|super\s+)?important\b|\bno\s+rush\b|\boptional\b", re.I)
_PERCENT = re.compile(r"\b(\d{1,3})\s*(?:%|percent)\s*(?:of\s+(?:my|the)\s+(?:grade|mark|final))?", re.I)


def _open_task_titles() -> list[str]:
    try:
        data = _load()
    except RuntimeError:
        return []
    return [t["title"] for t in data.get("tasks", []) if t.get("status", "open") == "open"]


def _matches_task(name: str, titles: list[str]) -> bool:
    from .tasks import clean_title
    name = clean_title(name) or name
    titles = [clean_title(t) or t for t in titles]
    n = " ".join(re.findall(r"[a-z0-9]+", name.lower()))
    n = re.sub(r"^(?:the|my)\s+", "", n)
    words = [w for w in n.split() if w not in ("task", "assignment", "project", "the", "my")]
    if not words:
        return False
    for title in titles:
        low = title.lower()
        if n in low or low in n or all(w in low for w in words):
            return True
    return False


def _importance(t: str) -> str:
    if _LOW.search(t):
        return "low"
    pct = _PERCENT.search(t)
    if _HIGH.search(t) or (pct and int(pct.group(1)) >= 20):
        return "high"
    return "normal"


_TNUM = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
         "nine": 9, "ten": 10, "twelve": 12, "fifteen": 15, "twenty": 20, "thirty": 30, "forty": 40, "forty-five": 45,
         "forty five": 45, "fifty": 50, "ninety": 90, "a couple of": 2, "a couple": 2, "couple of": 2, "a few": 3}
_TDUR = re.compile(r"\b(\d+(?:\.\d+)?|" + "|".join(sorted((re.escape(k) for k in _TNUM), key=len, reverse=True))
                   + r")[\s-]*(hours?|hrs?|minutes?|mins?)\b(\s+and\s+a\s+half)?", re.I)


def _task_minutes(t: str) -> int:
    """'about 4 hours' -> 240, 'an hour and a half' -> 90, 'half an hour' -> 30, '45 minutes' -> 45."""
    total = 0.0
    low = t.lower()
    if re.search(r"\bhalf\s+an?\s+hour\b", low):
        total += 30
        low = re.sub(r"\bhalf\s+an?\s+hour\b", " ", low)
    half = re.compile(r"\b(\d+|" + "|".join(k for k in _TNUM if " " not in k) + r")\s+and\s+a\s+half\s+(hours?|hrs?)\b")
    for m in half.finditer(low):
        n = float(m.group(1)) if m.group(1)[0].isdigit() else float(_TNUM[m.group(1)])
        total += (n + 0.5) * 60
    low = half.sub(" ", low)
    for m in _TDUR.finditer(low):
        n = float(m.group(1)) if m.group(1)[0].isdigit() else float(_TNUM[m.group(1)])
        unit = 60 if m.group(2).startswith("h") else 1
        total += n * unit + (unit / 2 if m.group(3) else 0)
    return int(round(total))


_TEST_ON = re.compile(r"\b(?:test|exam|quiz|midterm|final|presentation)s?\s+(?P<on>on|this|next)\b", re.I)


def _parse_task_add(t: str) -> dict | None:
    due = _DUE.search(t)
    if not due:
        # "I have a chem test on Friday": a test date works like a due date
        test = _TEST_ON.search(t)
        if not test or _RANGE.search(t) or re.search(r"\b(?:add|schedule|book|put|block)\b", t, re.I):
            return None
        cut = test.start("on")
        return _parse_task_add(t[:cut] + "due " + t[cut:].removeprefix("on ").removeprefix("On "))
    after = t[due.end():]
    day = _DATEWORD.search(after)
    if not day:
        return None
    title_src = t[:due.start()]
    if re.search(r"\b(homework|hw)\b", title_src, re.I) or re.search(r"\bremind\s+me\b", t, re.I):
        return None
    from .tasks import clean_title
    title_src = clean_title(title_src)
    title_src = re.sub(r"\b(?:which|that|it)\s*$", "", title_src.strip(), flags=re.I)
    words = re.findall(r"[A-Za-z0-9][A-Za-z0-9'+&-]*", title_src)
    while words and words[-1].lower() in ("is", "are", "that's", "it's", "which", "that", "it", "and"):
        words.pop()
    if not words or len(words) > 7:
        return None
    while words and words[0].lower() in ("big", "huge", "major", "important", "small", "quick", "little", "short", "long"):
        words.pop(0)
    if not words:
        return None
    title = " ".join(words)
    tok = re.sub(r"^this\s+", "", day.group(1).lower()).replace("tonight", "today")
    weekday = re.fullmatch(r"(mon|tues?|wed(?:nes)?|thu(?:rs?)?|fri|sat(?:ur)?|sun)(?:day)?s?", tok)
    if weekday and tok.endswith("days"):
        tok = tok[:-1]
    due_time = ""
    at = _AT.search(after[day.end():day.end() + 25]) or _AT.search(after[:day.start()])
    if at:
        g = at.groups()
        h, m, mer = (g[0], g[1], g[2]) if g[0] else (g[3], g[4], g[5])
        due_time = _hhmm(_clock(h, m, mer))
    rest = t[:due.start()] + " " + after[day.end():]
    rest = _AT.sub(" ", rest)
    return {"action": "add", "title": title[0].upper() + title[1:], "due": tok, "due_time": due_time,
            "minutes": _task_minutes(rest), "importance": _importance(t)}


def parse_task_request(text: str, previous: str = "") -> dict | None:
    """Plain speech about tasks with deadlines -> {"action": add|list|left|done|progress|priority|delete, ...}.
    previous = the user's message before this one: "it'll take about 4 hours" can finish an add that
    had no estimate. None if the sentence is not about a task."""
    t = " ".join(text.replace("’", "'").replace(",", " ").split()).strip()
    if not t:
        return None
    titles = _open_task_titles()
    m = _TASK_LEFT.search(t)
    if m and _matches_task(m.group("n"), titles):
        return {"action": "left", "task": m.group("n")}
    if _TASK_LIST.search(t) and _QUESTION.search(t) or re.match(r"^(?:list|show)\s+(?:me\s+)?(?:my\s+)?(?:tasks|deadlines|assignments)\b", t, re.I):
        return {"action": "list"}
    if _QUESTION.search(t):
        return None
    for rx in _TASK_LEVEL:
        m = rx.search(t)
        if m and _matches_task(m.group("n"), titles):
            lvl = m.group("l").lower()
            return {"action": "priority", "task": m.group("n"), "importance": {"medium": "normal", "top": "high"}.get(lvl, lvl)}
    added = _parse_task_add(t)
    if added:
        return added
    if previous and _task_minutes(t) and not _DUE.search(t):
        earlier = parse_task_request(previous)
        if earlier and earlier.get("action") == "add" and not earlier.get("minutes"):
            earlier["minutes"] = _task_minutes(t)
            if _importance(t) != "normal":
                earlier["importance"] = _importance(t)
            return earlier
    for rx in _TASK_DONE:
        m = rx.search(t)
        if m and _matches_task(m.group("n"), titles):
            return {"action": "done", "task": m.group("n")}
    if _TASK_WORK.search(t) and _task_minutes(t):
        rest = _DUR.sub(" ", t[_TASK_WORK.search(t).end():])
        rest = re.sub(r"^\s*(?:on|of|for|at|with|the|my|\s)+", "", rest, flags=re.I)
        rest = re.sub(r"\b(?:today|tonight|just\s+now|so\s+far|already)\b", " ", rest, flags=re.I).strip(" .")
        name = re.sub(r"^(?:on|of|for)\s+(?:the\s+|my\s+)?", "", rest, flags=re.I)
        name = re.sub(r"(?:\s+(?:for|of|on|at|with|and|so|now))+\s*$", "", name, flags=re.I)
        if _matches_task(name, titles):
            return {"action": "progress", "task": name, "minutes": _task_minutes(t)}
    called = re.search(r"\b(?:task|assignment|project)\s+(?:called|named)\s+(?P<n>.+?)(?:\s+(?:could|can|would|please)\b.*)?$", t, re.I)
    if called and re.search(r"\b(remove|delete|cancel|drop|get\s+rid\s+of)\b", t, re.I) and _matches_task(called.group("n"), titles):
        return {"action": "delete", "task": called.group("n")}
    plain = re.search(r"\b(?:remove|delete|cancel|drop|get\s+rid\s+of)\s+(?:the\s+|my\s+)?(?P<n>.+?)"
                      r"(?:\s+(?:tasks?|assignments?|projects?|sessions?))?"
                      r"(?:\s+(?:from|off|on)\s+(?:my\s+|the\s+)?(?:schedule|calendar|list|tasks|plan))?\W*$", t, re.I)
    if plain and not _DATEWORD.search(t) and _matches_task(plain.group("n"), titles):
        return {"action": "delete", "task": plain.group("n")}
    m = _TASK_DELETE.search(t)
    if m and (re.search(r"\b(task|assignment|project)\b", t, re.I) or re.search(r"\bfrom\s+(?:my\s+)?tasks\b", t, re.I)) \
            and not _DATEWORD.search(t) and _matches_task(m.group("n"), titles):
        return {"action": "delete", "task": m.group("n")}
    return None