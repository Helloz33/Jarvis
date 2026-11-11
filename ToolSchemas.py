"""The tools the model may call: their descriptions (TOOLS, sent to the model every turn) and
the Python function behind each name (FUNCTIONS). Server.py wraps FUNCTIONS to log every call."""
from __future__ import annotations

from Tools import (
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
    create_file,
    delete_event,
    delete_file,
    edit_file,
    forget,
    get_time,
    list_files,
    list_notes,
    list_schedule,
    list_timers,
    place_event,
    plan_week,
    read_file,
    recall,
    remember,
    run_python,
    set_day_off,
    set_goal,
    set_timer,
    update_event,
    web_search,
)


TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "list_files",
            "description": "List files and directories inside Test/.",
            "parameters": {
                "type": "object",
                "properties": {},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read a text file inside Test/. Use a relative path.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                    },
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_file",
            "description": (
                "Create a new text file inside Test/. "
                "Never overwrite an existing file."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                    },
                    "content": {
                        "type": "string",
                    },
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "edit_file",
            "description": (
                "Replace the contents of an existing text file inside Test/."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                    },
                    "content": {
                        "type": "string",
                    },
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_file",
            "description": (
                "Delete a file inside Test/. "
                "Always ask the user for confirmation."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                    },
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_python",
            "description": (
                "Run an existing .py file inside Test/ and return its exit "
                "code, stdout, and stderr."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                    },
                    "args": {
                        "type": "array",
                        "items": {
                            "type": "string",
                        },
                        "description": (
                            "Optional command-line arguments to pass to "
                            "the script."
                        ),
                    },
                    "timeout": {
                        "type": "integer",
                        "description": (
                            "Optional timeout in seconds (default 10)."
                        ),
                    },
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": (
                "Search the internet for current or external information. "
                "Use this when the user asks for web research, documentation, "
                "news, current information, or information that may not be "
                "available in the model's knowledge."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": (
                            "The search query to send to the web."
                        ),
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_time",
            "description": (
                "Get the current date and time. The user's local time is "
                "already in your instructions, so only use this for a time "
                "in a DIFFERENT place, with an IANA time zone name such as "
                "'America/Los_Angeles' or 'Asia/Tokyo'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "timezone": {
                        "type": "string",
                        "description": "IANA time zone name. Optional.",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_schedule",
            "description": (
                "Show the user's schedule for a day or a range of days "
                "(up to 14). Use for 'what's my day/week like'. Dates: "
                "YYYY-MM-DD, today, tomorrow or a weekday name."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "start_date": {"type": "string", "description": "First day. Default today."},
                    "end_date": {"type": "string", "description": "Last day. Default same as start."},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_event",
            "description": (
                "Add something to the schedule. One-off: give date. "
                "Repeating weekly: give repeat_days such as 'mon,wed,fri' "
                "(date then optionally sets the first day). kind is "
                "'flexible' normally, or 'fixed' for classes, school, work "
                "and other mandatory commitments. Fails with a clear reason "
                "if it overlaps something; then offer the free times it lists."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "start": {"type": "string", "description": "e.g. 15:00 or 3 pm"},
                    "end": {"type": "string", "description": "e.g. 16:30 or 4:30 pm"},
                    "duration_minutes": {"type": "integer", "description": "Use instead of end, e.g. 60 for an hour."},
                    "date": {"type": "string", "description": "YYYY-MM-DD, today, tomorrow or a weekday. Default today."},
                    "repeat_days": {"type": "string"},
                    "kind": {"type": "string", "enum": ["flexible", "fixed"]},
                    "until": {"type": "string", "description": "Last day of a repeating event."},
                },
                "required": ["title", "start"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "place_event",
            "description": (
                "Add one or more flexible events and let the schedule pick the "
                "times. Use this whenever the user does NOT give a clock time: "
                "'add 2 hours of test prep, one for math and one for chem', "
                "'a 1-hour session after my club', 'find time for a chem quiz "
                "review'. Use add_event only when they say a time."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "minutes": {"type": "integer", "description": "Length of each session, e.g. 60."},
                    "count": {"type": "integer", "description": "How many sessions with this title."},
                    "titles": {"type": "string", "description": "Several different sessions at once, separated by ';', e.g. 'Math test prep;Chem test prep'."},
                    "day": {"type": "string", "description": "A weekday, YYYY-MM-DD, today or tomorrow. Leave empty to spread over this week."},
                    "after": {"type": "string", "description": "Name of an event to sit right after, e.g. club."},
                    "before": {"type": "string", "description": "Name of an event to end right before, e.g. dinner."},
                    "within": {"type": "string", "enum": ["this week", "next week"]},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "clear_day",
            "description": (
                "Empty a day or several days: remove the flexible sessions "
                "(homework, physics, test prep...) there and stop the planner "
                "putting those goals back on those days. what = names separated "
                "by ';' or empty for everything flexible. School, club and gym "
                "are never touched. Use this for 'remove everything on Monday'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "start_date": {"type": "string", "description": "YYYY-MM-DD, today, tomorrow or a weekday."},
                    "end_date": {"type": "string", "description": "Last day, if more than one."},
                    "what": {"type": "string", "description": "e.g. 'homework;physics'. Empty = everything flexible."},
                },
                "required": ["start_date"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_timer",
            "description": "Start a countdown timer: 'set a 25 minute timer', 'pasta timer for 10 minutes'. Not for clock times (use add_note for 'remind me at 5').",
            "parameters": {
                "type": "object",
                "properties": {
                    "minutes": {"type": "number", "description": "Length in minutes (1.5 = 90 seconds)."},
                    "seconds": {"type": "number", "description": "Extra seconds. Optional."},
                    "label": {"type": "string", "description": "Optional name, e.g. pasta."},
                },
                "required": ["minutes"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "cancel_timer",
            "description": "Cancel a running timer by its name, or all timers.",
            "parameters": {
                "type": "object",
                "properties": {
                    "timer": {"type": "string", "description": "The timer's name, e.g. pasta. Empty if only one is running."},
                    "all_timers": {"type": "boolean", "description": "true to cancel every timer."},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_timers",
            "description": "Running timers and how much time each has left.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_note",
            "description": (
                "Save a reminder note for the REMINDERS tab: 'remind me to bring "
                "my charger tomorrow', 'don't let me forget the permission slip'. "
                "date and time are optional; with a time the user is alerted then."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "What to remember, e.g. bring my charger."},
                    "date": {"type": "string", "description": "today, tomorrow, a weekday or YYYY-MM-DD. Optional."},
                    "time": {"type": "string", "description": "e.g. 7 pm. Optional."},
                },
                "required": ["text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_notes",
            "description": "Read the user's open reminder notes (the REMINDERS tab).",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "complete_note",
            "description": "Cross a reminder note off (or remove it with remove=true). note = its id or a few of its words.",
            "parameters": {
                "type": "object",
                "properties": {"note": {"type": "string"}, "remove": {"type": "boolean"}},
                "required": ["note"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "clear_notes",
            "description": "Remove crossed-off reminder notes (done_only=true, default) or every note (done_only=false, asks first).",
            "parameters": {"type": "object", "properties": {"done_only": {"type": "boolean"}}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_event",
            "description": (
                "Change a scheduled event: move it, rename it or change its "
                "length. event_id comes from list_schedule (or the exact "
                "title). Only pass the fields that change. Changing a fixed "
                "event asks the user first."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "event_id": {"type": "string"},
                    "title": {"type": "string"},
                    "date": {"type": "string"},
                    "start": {"type": "string"},
                    "end": {"type": "string"},
                    "repeat_days": {"type": "string"},
                    "until": {"type": "string"},
                },
                "required": ["event_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_event",
            "description": (
                "Delete a scheduled event by id (from list_schedule) or "
                "exact title. Deleting a fixed event asks the user first."
            ),
            "parameters": {
                "type": "object",
                "properties": {"event_id": {"type": "string"}},
                "required": ["event_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_goal",
            "description": (
                "Set a recurring time goal such as homework or study, e.g. "
                "title 'Homework', minutes 120, per 'day'; or 'Physics "
                "self-study', 120, per 'week'. minutes=0 removes the goal. "
                "After changing goals, call plan_week."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "minutes": {"type": "integer"},
                    "per": {"type": "string", "enum": ["day", "week"]},
                    "session_minutes": {"type": "integer", "description": "Longest single session."},
                    "days": {"type": "string", "description": "Optional, e.g. 'weekdays'."},
                    "buffer_minutes": {"type": "integer", "description": "Start this long after the day's last fixed commitment."},
                },
                "required": ["title", "minutes"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_day_off",
            "description": (
                "Mark a day or range of days as off school (holiday, break, "
                "snow day). School is skipped on those days. remove=true "
                "undoes it. Afterwards call plan_week."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "start_date": {"type": "string", "description": "e.g. 2026-11-26 or 'friday'."},
                    "end_date": {"type": "string", "description": "Last day off, if more than one."},
                    "title": {"type": "string", "description": "e.g. 'Thanksgiving break'."},
                    "remove": {"type": "boolean"},
                },
                "required": ["start_date"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "adjust_homework",
            "description": (
                "Set how much homework there is on ONE day, e.g. 'I have 3 "
                "hours of homework on Thursday' = minutes 180, date thursday; "
                "'no homework Friday' = 0. Homework has priority: other "
                "flexible events in the way are moved to another day. The "
                "week is re-planned automatically."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "minutes": {"type": "integer"},
                    "date": {"type": "string", "description": "YYYY-MM-DD, today, tomorrow or a weekday. Default today."},
                },
                "required": ["minutes"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "plan_week",
            "description": (
                "Fit all the user's goals (homework, study, test prep) into "
                "the free time of a week. Replaces the earlier automatic "
                "plan for that week. start_date is any day in the week; "
                "default is this week."
            ),
            "parameters": {
                "type": "object",
                "properties": {"start_date": {"type": "string"}},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "remember",
            "description": (
                "Save one short fact about the user to long-term memory. Use "
                "when the user asks you to remember something or states a "
                "lasting fact or preference. Set permanent=true only for core "
                "facts (name, job, main projects); it asks the user first."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "fact": {"type": "string"},
                    "permanent": {"type": "boolean"},
                },
                "required": ["fact"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "recall",
            "description": (
                "Search long-term memory. Use when the user asks what you "
                "know or remember, or to find a memory id."
            ),
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "forget",
            "description": (
                "Delete one memory by its id (from recall). Asks the user "
                "for confirmation. Only when the user asks to forget."
            ),
            "parameters": {
                "type": "object",
                "properties": {"memory_id": {"type": "string"}},
                "required": ["memory_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_task",
            "description": (
                "Add a task with a deadline and an estimate, e.g. 'history essay due Friday, about 4 hours' "
                "or 'chem test on Monday, 3 hours of studying'. The work is split into sessions planned "
                "before the due date. If the user gave no estimate, ask how long it will take first."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "due": {"type": "string", "description": "YYYY-MM-DD, today, tomorrow or a weekday."},
                    "hours": {"type": "number", "description": "Estimated total hours (1.5 = 90 minutes)."},
                    "minutes": {"type": "integer", "description": "Extra minutes, or the estimate in minutes."},
                    "importance": {"type": "string", "enum": ["high", "normal", "low"],
                                   "description": "high for big tests or a big part of the grade; default normal."},
                    "due_time": {"type": "string", "description": "Optional time it is due, e.g. 9 am."},
                },
                "required": ["title", "due"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_tasks",
            "description": "Tasks with deadlines: due date, priority, time left and the next planned session.",
            "parameters": {"type": "object", "properties": {"include_done": {"type": "boolean"}}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_task",
            "description": "Change a task's title, due date, total estimate (hours/minutes = the new total) or importance.",
            "parameters": {
                "type": "object",
                "properties": {
                    "task": {"type": "string", "description": "The task's id or name."},
                    "title": {"type": "string"},
                    "due": {"type": "string"},
                    "hours": {"type": "number"},
                    "minutes": {"type": "integer"},
                    "importance": {"type": "string", "enum": ["high", "normal", "low"]},
                    "due_time": {"type": "string"},
                },
                "required": ["task"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "log_task_progress",
            "description": "Record work done on a task ('I did 45 minutes of the essay') or mark it finished (done=true).",
            "parameters": {
                "type": "object",
                "properties": {
                    "task": {"type": "string"},
                    "minutes": {"type": "integer"},
                    "done": {"type": "boolean"},
                },
                "required": ["task"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_task",
            "description": "Remove a task and its planned sessions (only when the user asks).",
            "parameters": {"type": "object", "properties": {"task": {"type": "string"}}, "required": ["task"]},
        },
    },
]


FUNCTIONS = {
    "list_files": list_files,
    "read_file": read_file,
    "create_file": create_file,
    "edit_file": edit_file,
    "delete_file": delete_file,
    "run_python": run_python,
    "web_search": web_search,
    "get_time": get_time,
    "list_schedule": list_schedule,
    "add_event": add_event,
    "place_event": place_event,
    "clear_day": clear_day,
    "add_note": add_note,
    "set_timer": set_timer,
    "cancel_timer": cancel_timer,
    "list_timers": list_timers,
    "add_task": add_task,
    "list_tasks": list_tasks,
    "update_task": update_task,
    "log_task_progress": log_task_progress,
    "delete_task": delete_task,
    "list_notes": list_notes,
    "complete_note": complete_note,
    "clear_notes": clear_notes,
    "update_event": update_event,
    "delete_event": delete_event,
    "set_goal": set_goal,
    "set_day_off": set_day_off,
    "adjust_homework": adjust_homework,
    "plan_week": plan_week,
    "remember": remember,
    "recall": recall,
    "forget": forget,
}


