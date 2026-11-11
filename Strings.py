"""Lines the assistant says that do not come from the model (reminders, timers, quick replies).

Kept in one place so they can be changed (or translated later) without hunting through the code.
How the user is addressed ("sir") comes from Config.USER_ADDRESS; with "" the lines simply leave
it out ("We have Physics scheduled for 4:00 PM.").
"""
from __future__ import annotations

import Config


def _lead(rest: str) -> str:
    """'we have X' -> 'Sir, we have X' (or 'We have X' when no form of address is set)."""
    who = Config.USER_ADDRESS.strip()
    if who:
        return f"{who[0].upper()}{who[1:]}, {rest}"
    return rest[0].upper() + rest[1:]


def with_address(text: str) -> str:
    """'Timer set' -> 'Timer set, sir.' (or 'Timer set.')."""
    who = Config.USER_ADDRESS.strip()
    return f"{text}, {who}." if who else f"{text}."


# --- reminders and timers -----------------------------------------------------------------
def event_reminder(title: str, start: str) -> str:
    return _lead(f"we have {title} scheduled for {start}.")


def note_reminder(text: str) -> str:
    return _lead(f"a reminder: {text}.")


def note_morning(text: str) -> str:
    return _lead(f"don't forget: {text}.")


def timer_done(name: str) -> str:
    return _lead(f"your {name} is done.")


def timer_missed(name: str) -> str:
    return _lead(f"your {name} finished while I was closed.")


def task_session(title: str, start: str) -> str:
    return _lead(f"time to work on {title}, {start}.")


# --- quick replies ------------------------------------------------------------------------
def already_scheduled(title: str) -> str:
    return with_address(f"{title} is already on your schedule")
