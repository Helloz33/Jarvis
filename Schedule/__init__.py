"""Schedule: fixed commitments, protected time, study goals, a planner, reminder notes and timers.

The schedule is plain data in Schedule_data/schedule.json (gitignored, and easy
to edit by hand). All the rules live here in code, not in the AI model:

  * fixed events (school, club, gym...) are locked: changing them asks you first
  * protected time (sleep, dinner) can never be scheduled over
  * flexible events can be added, moved and deleted freely, but never overlap
    anything else; a conflict comes back with free times so the model can retry
  * goals ("Physics 2 h per week") are placed into real free time by plan_week

How the package is split (other files import from here, the front door):

    timeparse.py   times, dates, weekdays          store.py     load / save schedule.json
    rules.py       busy, free, conflicts            view.py      the SCHEDULE tab's data
    events.py      add, change, delete, place,      planner.py   goals, plan_week, homework,
                   clear a day                                   days off
    alerts.py      which reminders are due          parsers.py   plain speech -> tool arguments
    tasks.py       tasks with deadlines: priority, planning, warnings before losing time
    notes.py       the REMINDERS tab                timers.py    countdown timers
    permission.py  the Yes/No popup hook
"""
from __future__ import annotations

from . import alerts, events, notes, parsers, permission, planner, rules, store, tasks, timeparse, timers, view
from .alerts import due_reminders
from .events import add_event, clear_day, delete_event, list_schedule, place_event, update_event
from .notes import add_note, clear_notes, complete_note, list_notes, notes_view, parse_note_request
from .parsers import (
    find_rename_target,
    is_confirmation,
    parse_add_request,
    parse_clear_request,
    parse_day_off_request,
    parse_homework_request,
    parse_place_request,
    parse_task_request,
    sounds_like_add,
)
from .planner import adjust_homework, plan_week, set_day_off, set_goal
from .tasks import add_task, delete_task, list_tasks, log_task_progress, plan_tasks, update_task
from .timeparse import DAY_CODES, WEEKDAYS
from .timers import cancel_timer, list_timers, parse_timer_request, set_timer
from .view import week_view

__all__ = [
    "list_schedule", "add_event", "update_event", "delete_event", "place_event", "clear_day",
    "set_goal", "plan_week", "adjust_homework", "set_day_off", "due_reminders", "week_view",
    "add_note", "list_notes", "complete_note", "clear_notes", "notes_view", "parse_note_request",
    "set_timer", "cancel_timer", "list_timers", "parse_timer_request",
    "parse_add_request", "parse_place_request", "parse_homework_request", "parse_day_off_request",
    "parse_clear_request", "find_rename_target", "is_confirmation", "sounds_like_add", "parse_task_request",
    "add_task", "list_tasks", "update_task", "log_task_progress", "delete_task", "plan_tasks",
    "DAY_CODES", "WEEKDAYS",
]
