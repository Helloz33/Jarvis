from __future__ import annotations

import json
import re
import threading
from typing import Any

import os

import ollama
from dotenv import load_dotenv

load_dotenv()  # reads .env in the current directory, if present

import Llm
import Memory
from Personality import (
    PERSONA,
    PHRASE_PROMPT,
    build_system_prompt,
    search_announcement,
)
from Tools import (
    SANDBOX,
    UNTRUSTED_TOOLS,
    create_file,
    delete_file,
    edit_file,
    forget,
    get_time,
    list_files,
    listen,
    mark_untrusted,
    now_line,
    read_file,
    recall,
    remember,
    reset_untrusted,
    run_python,
    speak,
    web_search,
)

# Change the model here, or without editing code: JARVIS_MODEL=qwen3:8b in .env
MODEL = os.getenv("JARVIS_MODEL", "qwen3.5:9b")
MAX_TOOL_CALLS = 8
PERSONA_ON_WRITES = True   # one extra short model call so write results sound like Jarvis


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
    "remember": remember,
    "recall": recall,
    "forget": forget,
}


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


def run_turn(user_text: str) -> str:
    """Run one request: build memory context, run the tool loop, remember it."""

    reset_untrusted()

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


def _phrase(result: str) -> str:
    """Say a write result in Jarvis's voice. Falls back to the plain result."""

    plain = result + "."

    if not PERSONA_ON_WRITES:
        return plain

    try:
        response = Llm.chat(
            MODEL,
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


def _run_loop(messages: list[dict[str, Any]], user_text: str = "") -> str:
    """Ollama's native tool-calling loop."""

    calls_used = 0
    web_called = False
    search_forced = False

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

                    result = FUNCTIONS[name](**arguments)

                except Exception as exc:
                    result = f"Error executing {name}: {exc}"

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
            f"Run: ollama pull {MODEL}  (or set JARVIS_MODEL in .env)"
        )
        return False

    capabilities = getattr(info, "capabilities", None)
    if capabilities and "tools" not in capabilities:
        print(
            f"Warning: '{MODEL}' does not list tool support, so Jarvis may "
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
    """Start the interactive Jarvis terminal."""

    SANDBOX.mkdir(parents=True, exist_ok=True)

    print("Jarvis V0.5")
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
                    print("Jarvis: Didn't catch that, try again.")
                    continue

                print(f"You (voice): {user_text}")
            else:
                user_text = input("You: ").strip()

        except (KeyboardInterrupt, EOFError):
            print("\nGoodbye.")
            break
        except RuntimeError as exc:
            # listen() raises this if the mic/service itself is unreachable.
            print(f"Jarvis error: {exc}")
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
            print(f"Jarvis: {reply}")
            speak(reply)

        except Exception as exc:
            print(f"Jarvis error: {exc}")


if __name__ == "__main__":
    main()