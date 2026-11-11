"""Direct paths: common requests (timers, reminders, adding / placing / clearing events, days off,
homework, renames) are understood by rules and run straight away, without the model. They are
fast and always reliable; anything they do not recognise goes to the model as usual."""
from __future__ import annotations

import re

import Config
import Llm
import Memory
import Strings
from Personality import PERSONA, PHRASE_PROMPT
from Schedule import (
    find_rename_target,
    is_confirmation,
    parse_add_request,
    parse_clear_request,
    parse_day_off_request,
    parse_homework_request,
    parse_note_request,
    parse_place_request,
    parse_task_request,
    parse_timer_request,
    sounds_like_add,
)
from ToolSchemas import FUNCTIONS

PERSONA_ON_WRITES = True   # one extra short model call so write results sound in character


def _quick_schedule(user_text: str) -> str | None:
    """Plain 'add ... at 3 pm' requests are handled directly (see parse_add_request)."""
    try:
        previous = next((m["content"] for m in reversed(Memory.history.messages())
                         if m.get("role") == "user"), "")
    except Exception:
        previous = ""
    task = _quick_tasks(user_text, previous)
    if task:
        return task
    noted = _quick_notes(user_text)
    if noted:
        return noted
    off = _quick_dayoff(user_text, previous)
    if off:
        return off
    cleared = _quick_clear(user_text)
    if cleared:
        return cleared
    placed = _quick_place(user_text)
    if placed:
        return placed
    try:
        args = parse_add_request(user_text, previous)
    except Exception:
        return None
    if not args:
        other = _quick_homework(user_text) or _quick_rename(user_text)
        if other:
            return other
        if sounds_like_add(user_text):
            return ("I could not make out the time. Say it in one go, for example: "
                    "add a study session from 6:10 to 6:40 PM.")
        return None
    result = FUNCTIONS["add_event"](**args)
    if not isinstance(result, str):
        return None
    if result.startswith("Added"):
        return phrase(result)
    if result.startswith("Error: that conflicts with " + args["title"]):
        return Strings.already_scheduled(args["title"])
    return "I could not add that. " + result.removeprefix("Error: ")


_TEST_WORDS = re.compile(r"\b(test|exam|quiz|midterm|final)s?\b", re.I)


def _no_ids(text: str) -> str:
    return re.sub(r"\s*\[[0-9a-f]{4}\]", "", text)


def _quick_tasks(user_text: str, previous: str = "") -> str | None:
    """'I have a history essay due Friday, it'll take about 4 hours', 'what's due this week?',
    'I did 45 minutes of the essay', 'the essay is done' -> tasks with deadlines, handled directly."""
    from Schedule import tasks as task_engine
    try:
        parsed = parse_task_request(user_text, previous)
    except Exception:
        return None
    if not parsed:
        return None
    action = parsed["action"]
    if action == "add":
        if not parsed["minutes"]:
            name = parsed["title"].lower()
            if _TEST_WORDS.search(name):
                return f"How many hours of studying do you want for the {name}?"
            return f"How long do you think the {name} will take?"
        result = str(FUNCTIONS["add_task"](title=parsed["title"], due=parsed["due"], minutes=parsed["minutes"],
                                           importance=parsed["importance"], due_time=parsed["due_time"]))
        if not result.startswith("Added task"):
            return "I could not add that task. " + result.removeprefix("Error: ")
        task_id = re.search(r"\[([0-9a-f]{4})\]", result).group(1)
        head = _no_ids(result.split(". ")[0]).replace("Added task: ", "Added ") + "."
        warnings = [s.strip() for s in re.split(r"(?<=\.)\s+", result)
                    if any(k in s for k in ("does not fit", "only fits", "Moved to make room"))
                    or ("treating it" in s and s.startswith(parsed["title"]))]
        return " ".join([head, task_engine.spoken_plan(task_id)] + warnings)
    if action in ("list", "left"):
        result = _no_ids(str(FUNCTIONS["list_tasks"]()))
        if action == "left":
            want = [w for w in re.findall(r"[a-z0-9]+", parsed["task"].lower()) if w not in ("the", "my")]
            parts = [p for p in result.split("; ") if all(w in p.split(":")[0].lower() for w in want)]
            result = parts[0] if parts else result
        return result
    if action == "done":
        result = str(FUNCTIONS["log_task_progress"](task=parsed["task"], done=True))
    elif action == "progress":
        result = str(FUNCTIONS["log_task_progress"](task=parsed["task"], minutes=parsed["minutes"]))
    elif action == "priority":
        result = str(FUNCTIONS["update_task"](task=parsed["task"], importance=parsed["importance"]))
    else:
        result = str(FUNCTIONS["delete_task"](task=parsed["task"]))
    if result.startswith("Error: "):
        return "I could not do that. " + _no_ids(result.removeprefix("Error: "))
    return _no_ids(result)


def _quick_timer(user_text: str) -> str | None:
    """'set a 25 minute timer', 'cancel the pasta timer', 'how long is left?' -> handled directly."""
    try:
        parsed = parse_timer_request(user_text)
    except Exception:
        return None
    if not parsed:
        return None
    if parsed["action"] == "set":
        result = FUNCTIONS["set_timer"](minutes=parsed["seconds"] / 60, label=parsed["label"])
    elif parsed["action"] == "cancel":
        result = FUNCTIONS["cancel_timer"](timer=parsed["timer"], all_timers=parsed["all"])
    else:
        return str(FUNCTIONS["list_timers"]())
    result = str(result)
    if result.startswith("Error: "):
        return result.removeprefix("Error: ")
    return Strings.with_address(result)


def _quick_notes(user_text: str) -> str | None:
    """'remind me to bring my charger tomorrow', 'cross off the charger', 'what do I need to
    remember?' -> the Reminders tab, handled directly."""
    try:
        parsed = parse_note_request(user_text)
    except Exception:
        return None
    if not parsed:
        return None
    action = parsed["action"]
    if action == "add":
        result = FUNCTIONS["add_note"](text=parsed["text"], date=parsed["date"], time=parsed["time"])
    elif action == "done":
        result = FUNCTIONS["complete_note"](note=parsed["note"])
    elif action == "delete":
        result = FUNCTIONS["complete_note"](note=parsed["note"], remove=True)
    elif action == "clear":
        result = FUNCTIONS["clear_notes"](done_only=parsed["done_only"])
    else:
        result = FUNCTIONS["list_notes"]()
    result = str(result)
    if result.startswith("Error:"):
        return "I could not do that. " + result.removeprefix("Error: ")
    if action == "list":
        return _speak_list(result)
    return result


def _speak_list(result: str) -> str:
    """Drop the [ids] from a list_notes line so it reads well aloud."""
    return re.sub(r"\s*\[[0-9a-f]{4}\]", "", result)


def _quick_clear(user_text: str) -> str | None:
    """'remove all items on the Monday schedule' -> clear_day, handled directly."""
    try:
        parsed = parse_clear_request(user_text)
    except Exception:
        return None
    if not parsed:
        return None
    done, declined, failed = [], False, []
    for start, end in parsed["ranges"]:
        result = str(FUNCTIONS["clear_day"](start_date=start, end_date=end, what=parsed["what"]))
        if result.startswith("Cleared"):
            done.append(result)
        elif result.startswith("There is nothing"):
            done.append(result)
        elif "declined" in result:
            declined = True
        else:
            failed.append(result.removeprefix("Error: "))
    if done:
        return " ".join(done)
    if declined:
        return "Okay, I left your schedule as it was. Say \"do it\" if you want me to ask again."
    return "I could not clear that. " + " ".join(failed)


def _quick_dayoff(user_text: str, previous: str = "") -> str | None:
    """'mark today and tomorrow as days off from school' (or a bare 'do it' after a declined
    one) -> set_day_off, handled directly. A declined prompt is never permanent."""
    try:
        parsed = parse_day_off_request(previous if is_confirmation(user_text) else user_text)
    except Exception:
        return None
    if not parsed:
        return None
    done, declined, failed = [], False, []
    for start, end in parsed["ranges"]:
        result = FUNCTIONS["set_day_off"](start_date=start, end_date=end, title=parsed["title"],
                                          remove=parsed["remove"])
        result = str(result)
        if result.startswith(("Marked", "Removed")):
            done.append(result.split(" Run plan_week")[0].rstrip("."))
        elif "declined" in result:
            declined = True
        else:
            failed.append(result.removeprefix("Error: "))
    if done:
        FUNCTIONS["plan_week"]()
        return "; ".join(done) + ". I re-planned the week."
    if declined:
        return "Okay, I left your schedule as it was. Say \"do it\" if you want me to ask again."
    return "I could not change the days off. " + " ".join(failed)


def _quick_place(user_text: str) -> str | None:
    """'add 2 hours of test prep ... place it how you see fit' -> place_event, handled directly."""
    try:
        args = parse_place_request(user_text)
    except Exception:
        return None
    if not args:
        return None
    result = FUNCTIONS["place_event"](**args)
    if not isinstance(result, str):
        return None
    if result.startswith("Placed"):
        return phrase(result)
    return "I could not place that. " + result.removeprefix("Error: ")


def _quick_homework(user_text: str) -> str | None:
    """'I have 3 hours of homework on Thursday' / 'set homework to 90 minutes'."""
    try:
        parsed = parse_homework_request(user_text)
    except Exception:
        return None
    if not parsed:
        return None
    kind, minutes, dayword = parsed
    if kind == "day":
        result = FUNCTIONS["adjust_homework"](minutes=minutes, date=dayword)
    else:
        FUNCTIONS["set_goal"](title="Homework", minutes=minutes, per="day", buffer_minutes=0)
        result = f"Homework is now {minutes} minutes a day.\n" + str(FUNCTIONS["plan_week"]())
    if not isinstance(result, str) or result.startswith("Error"):
        return "I could not change the homework. " + str(result).removeprefix("Error: ")
    first = result.splitlines()[0]
    moved = next((l for l in result.splitlines() if l.startswith("Moved to make room")), "")
    return first + (" " + moved.replace("Moved to make room for homework: ", "I moved ") + "." if moved else "")


def _quick_rename(user_text: str) -> str | None:
    """'name that session calculus' -> update_event, handled directly."""
    try:
        found = find_rename_target(user_text)
    except Exception:
        return None
    if found is None:
        return None
    if isinstance(found, str):
        return found
    event_id, new_title = found
    result = FUNCTIONS["update_event"](event_id=event_id, title=new_title)
    if isinstance(result, str) and result.startswith("Updated"):
        return phrase(result)
    return "I could not rename it. " + str(result).removeprefix("Error: ")



def phrase(result: str) -> str:
    """Say a write result in the assistant's voice. Falls back to the plain result."""

    plain = result + "."

    if not PERSONA_ON_WRITES:
        return plain

    try:
        response = Llm.chat(
            Config.MODEL,
            [
                {"role": "system", "content": PERSONA},
                {"role": "user", "content": PHRASE_PROMPT + result},
            ],
        )
        text = " ".join((response.message.content or "").split())
    except Exception:
        return plain

    # Safety net: keep the plain result if the model rambled or dropped a
    # file name that was in the result.
    names = re.findall(r"[\w./-]+\.\w+", result)
    if not text or len(text) > 300 or any(n not in text for n in names):
        return plain

    return text



def quick_reply(user_text: str) -> str | None:
    """The direct-path reply for this request, or None if the model should handle it."""
    return _quick_timer(user_text) or _quick_schedule(user_text)
