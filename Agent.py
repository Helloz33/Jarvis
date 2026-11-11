"""The agent: builds the prompt, runs the model's tool-calling loop, and remembers the turn.

    ToolSchemas.py  the tools the model may call (TOOLS) and the function behind each (FUNCTIONS)
    QuickPaths.py   common requests handled directly by rules, before the model is asked
    Config.py       the model, name, voice and other settings
"""
from __future__ import annotations

import json
import re
import threading
from typing import Any

import ollama

import Config
import Llm
import Memory
import QuickPaths
from Personality import build_system_prompt, search_announcement
from QuickPaths import phrase as _phrase
from QuickPaths import quick_reply
from ToolSchemas import FUNCTIONS, TOOLS
from Tools import (
    SANDBOX,
    UNTRUSTED_TOOLS,
    listen,
    mark_untrusted,
    now_line,
    reset_untrusted,
    speak,
)

MODEL = Config.MODEL
MAX_TOOL_CALLS = 8


# --- Spoken status ("Searching for ...") --------------------------------
# The UI registers a handler that speaks short status lines while a slow tool
# runs. With no handler (terminal use) it just prints.
_status_handler = None


def set_status_handler(handler) -> None:
    """handler(text) -> None; it may block while the text is spoken."""
    global _status_handler
    _status_handler = handler


def _announce(text: str) -> None:
    print(f"[status] {text}")
    if _status_handler is not None:
        try:
            _status_handler(text)
        except Exception:
            pass


# Small models sometimes SAY they are searching instead of calling the tool.
_PROMISE_RE = re.compile(
    r"\b(searching|search the web|search for|look(ing)? (it |that |this )?up|"
    r"let me (check|look|find|search|pull)|checking the web|pulling up)\b",
    re.IGNORECASE,
)



_SCHEDULE_TOOLS = {"add_task", "update_task", "log_task_progress", "delete_task", "add_event", "place_event", "clear_day", "add_note", "complete_note", "clear_notes", "update_event", "delete_event", "set_goal", "set_day_off", "plan_week"}

# The model says it changed the schedule ("I've added...") without calling a tool.
_CLAIM_RE = re.compile(
    r"\b(i('| ha)?ve|i|we|has been|have been|is now|are now|now)\b[^.?!]{0,40}"
    r"\b(added|scheduled|booked|put|placed|moved|rescheduled|updated|removed|deleted|"
    r"cancel(l)?ed|set|confirmed)\b|\b(added|scheduled|booked) (it|that|them)\b",
    re.IGNORECASE,
)


_CHANGE_ASK = re.compile(r"\b(add|remove|delete|cancel|clear|move|reschedule|rename|schedule|book|set|drop|mark)\b", re.I)
_BARE_OK = re.compile(r"^\W*(?:done|all\s+set|all\s+done|okay|ok|sure|got\s+it|taken\s+care\s+of|consider\s+it\s+done)"
                      r"(?:[,.!]?\s*(?:sir|ma'am))?\W*$", re.I)


def _claims_schedule_change(content: str, user_text: str = "") -> bool:
    if bool(content) and _BARE_OK.match(content) and _CHANGE_ASK.search(user_text or ""):
        return True                      # "Done." to "remove the essay" without calling a tool
    return bool(content) and len(content) < 400 and "?" not in content and bool(_CLAIM_RE.search(content))


def _promises_search(content: str) -> bool:
    return bool(content) and len(content) < 300 and bool(_PROMISE_RE.search(content))


def _make_call(name: str, arguments: dict):
    class FunctionCall:
        pass

    class Call:
        pass

    call = Call()
    call.function = FunctionCall()
    call.function.name = name
    call.function.arguments = arguments
    return call


def _calls_from_content(content: str) -> list:
    """Some Qwen/Ollama combinations return a tool call as JSON in
    message.content instead of populating message.tool_calls."""
    try:
        parsed = json.loads(content)
    except (json.JSONDecodeError, TypeError):
        return []

    if (
        isinstance(parsed, dict)
        and parsed.get("name") in FUNCTIONS
        and isinstance(parsed.get("arguments"), dict)
    ):
        return [_make_call(parsed["name"], parsed["arguments"])]

    return []


def plain_error(name: str, exc: Exception) -> str:
    """A tool crashed: describe it in plain words the model can pass on, and stop it retrying."""
    reason = " ".join(str(exc).split()) or type(exc).__name__
    if name == "web_search":
        return (f"Error: {reason} Tell the user plainly in one short sentence and do not try "
                "the search again this turn.")
    return f"Error: {name.replace('_', ' ')} did not work ({reason}). Tell the user plainly."


def run_turn(user_text: str) -> str:
    """Run one request: build memory context, run the tool loop, remember it."""

    reset_untrusted()

    quick = quick_reply(user_text)
    if quick:
        Memory.history.add_turn(user_text, quick)
        return quick

    try:
        profile, memories = Memory.context_for(user_text)
    except Exception:
        profile, memories = "", []

    messages: list[dict[str, Any]] = [
        {
            "role": "system",
            "content": build_system_prompt(SANDBOX, profile, memories, now_line()),
        },
        *Memory.history.messages(),
        {
            "role": "user",
            "content": user_text,
        },
    ]

    reply = _run_loop(messages, user_text)
    Memory.history.add_turn(user_text, reply)
    return reply



def _run_loop(messages: list[dict[str, Any]], user_text: str = "") -> str:
    """Ollama's native tool-calling loop."""

    calls_used = 0
    web_called = False
    search_forced = False
    sched_called = False
    sched_nudged = False

    while calls_used < MAX_TOOL_CALLS:
        response = Llm.chat(MODEL, messages, TOOLS)

        message = response.message
        calls = message.tool_calls or []

        if not calls:
            content = (message.content or "").strip()
            calls = _calls_from_content(content)

            if not calls:
                # The model announced a search but never called the tool.
                # Run the search for it instead of ending the turn.
                if (
                    user_text
                    and not web_called
                    and not search_forced
                    and _promises_search(content)
                ):
                    search_forced = True
                    calls = [_make_call("web_search", {"query": user_text})]
                elif (
                    not sched_called
                    and not sched_nudged
                    and _claims_schedule_change(content, user_text)
                ):
                    # It claimed a schedule change without calling a tool. Make it
                    # actually do it (or admit nothing changed) instead of lying.
                    sched_nudged = True
                    messages.append(message)
                    messages.append({
                        "role": "user",
                        "content": (
                            "You said the schedule was changed, but you did not call a tool, "
                            "so nothing changed. If I asked for a change, call add_event, "
                            "update_event, delete_event, delete_task, set_goal or set_day_off now with exact "
                            "values (title, date YYYY-MM-DD or 'today', start and end as HH:MM). "
                            "If something is missing, ask me one short question instead."
                        ),
                    })
                    continue
                else:
                    return content or "Done."

        messages.append(message)

        for call in calls:
            name = call.function.name
            arguments = call.function.arguments

            if name not in FUNCTIONS:
                result = f"Error: unknown tool '{name}'."

            else:
                try:
                    if not isinstance(arguments, dict):
                        arguments = json.loads(arguments)

                    if name == "web_search":
                        web_called = True
                        _announce(search_announcement(arguments.get("query", "")))

                    if name in _SCHEDULE_TOOLS:
                        sched_called = True

                    result = FUNCTIONS[name](**arguments)

                except Exception as exc:
                    result = plain_error(name, exc)

                # Outside content (web pages, files, script output) must not be
                # able to write to memory without the user's approval.
                if name in UNTRUSTED_TOOLS:
                    mark_untrusted()

            # Tavily/web_search returns structured data (a list of dicts),
            # while Ollama expects tool message content to be a string.
            if not isinstance(result, str):
                result = json.dumps(result, indent=2)

            print(f"[tool] {name}: {result}")

            messages.append(
                {
                    "role": "tool",
                    "tool_name": name,
                    "content": result,
                }
            )

            calls_used += 1

            # IMPORTANT:
            # Once a write/delete operation succeeds, end this turn.
            # This prevents the small model from doing:
            # create -> list -> read -> edit -> delete -> recreate...
            #
            # run_python and web_search are not in this set because they
            # don't modify files and may reasonably be used during the
            # same turn.
            if name in {"create_file", "edit_file", "delete_file"}:
                if result.startswith(
                    (
                        "Created ",
                        "Edited ",
                        "Deleted ",
                        "Deletion cancelled",
                        "Edit cancelled",
                    )
                ):
                    return _phrase(result)

            if calls_used >= MAX_TOOL_CALLS:
                return (
                    "I stopped because the tool-call safety limit "
                    "was reached."
                )

    return "I stopped because the tool-call safety limit was reached."


def check_ollama() -> bool:
    """Check that Ollama is running and the selected model is installed."""

    try:
        ollama.list()

    except Exception as exc:
        print(
            "Error: Ollama is not running or is unreachable: "
            f"{exc}"
        )
        return False

    try:
        info = ollama.show(MODEL)

    except Exception:
        print(
            f"Error: model '{MODEL}' is not installed. "
            f"Run: ollama pull {MODEL}  (or set IRIS_MODEL in .env)"
        )
        return False

    capabilities = getattr(info, "capabilities", None)
    if capabilities and "tools" not in capabilities:
        print(
            f"Warning: '{MODEL}' does not list tool support, so {Config.NAME} may "
            "not be able to use its tools with it."
        )

    if Memory.embeddings.embed("ping") is None:
        print(
            f"Note: embedding model '{Memory.embeddings.EMBED_MODEL}' is not "
            f"installed, so memory falls back to keyword search. "
            f"Run: ollama pull {Memory.embeddings.EMBED_MODEL}"
        )

    return True


def save_session(wait: bool = False) -> None:
    """Summarize this conversation into long-term memory (background job)."""

    done = threading.Event()
    started = Memory.end_session(MODEL, on_done=done.set)

    if started and wait:
        print("Saving what I learned...")
        done.wait(timeout=90)


def main() -> None:
    """Start the interactive terminal version."""

    SANDBOX.mkdir(parents=True, exist_ok=True)

    print(f"{Config.NAME} (terminal)")
    print(f"Model:   {MODEL}")
    print(f"Sandbox: {SANDBOX}")
    print(
        "Type 'exit', 'quit', or 'bye' to close. Type 'voice' as your first "
        "message to stay in voice mode for the rest of this chat.\n"
    )

    if not check_ollama():
        return

    EXIT_WORDS = {"exit", "quit", "bye"}
    voice_mode = False

    while True:
        try:
            if voice_mode:
                user_text = listen()

                if not user_text:
                    print(f"{Config.NAME}: Didn't catch that, try again.")
                    continue

                print(f"You (voice): {user_text}")
            else:
                user_text = input("You: ").strip()

        except (KeyboardInterrupt, EOFError):
            print("\nGoodbye.")
            break
        except RuntimeError as exc:
            # listen() raises this if the mic/service itself is unreachable.
            print(f"{Config.NAME} error: {exc}")
            continue

        if user_text.lower() == "voice" and not voice_mode:
            voice_mode = True
            print(
                "Voice mode on for the rest of this chat. "
                "Say 'exit', 'quit', or 'bye' to end.\n"
            )
            continue

        if user_text.lower() in EXIT_WORDS:
            print("Goodbye.")
            save_session(wait=True)
            break

        if not user_text:
            continue

        try:
            reply = run_turn(user_text)
            print(f"{Config.NAME}: {reply}")
            speak(reply)

        except Exception as exc:
            print(f"{Config.NAME} error: {exc}")


if __name__ == "__main__":
    main()