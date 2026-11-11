"""The schedule functions the model can call (a thin layer over the Schedule package, like
memory_tools.py is over Memory). The engine itself lives in Schedule/."""
from __future__ import annotations

from Schedule import (
    add_event,
    add_task,
    delete_task,
    list_tasks,
    log_task_progress,
    update_task,
    add_note,
    adjust_homework,
    cancel_timer,
    clear_day,
    clear_notes,
    complete_note,
    delete_event,
    list_notes,
    list_schedule,
    list_timers,
    notes_view,
    place_event,
    plan_week,
    set_day_off,
    set_goal,
    set_timer,
    update_event,
)

__all__ = [
    "list_schedule", "add_event", "update_event", "delete_event", "place_event", "clear_day",
    "set_goal", "plan_week", "adjust_homework", "set_day_off",
    "add_note", "list_notes", "complete_note", "clear_notes", "notes_view",
    "set_timer", "cancel_timer", "list_timers",
    "add_task", "list_tasks", "update_task", "log_task_progress", "delete_task",
]
