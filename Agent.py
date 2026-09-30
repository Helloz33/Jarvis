from __future__ import annotations

import json
from typing import Any

import ollama

from Tools import (
    SANDBOX,
    create_file,
    delete_file,
    edit_file,
    list_files,
    read_file,
    run_python,
    web_search,
)


MODEL = "qwen2.5-coder:7b"
MAX_TOOL_CALLS = 8


SYSTEM_PROMPT = f"""
You are Jarvis V0.2.5, a simple local coding and research assistant.

You may ONLY access files through the provided tools, and only inside:
{SANDBOX}

Rules:
- Never use shell commands.
- Only use a tool when the user's request requires it.
- Use web_search when the user asks for current information,
  documentation, research, news, or information from the internet.
- When using web_search, pass the user's request as a clear search query.
- Do not claim to have searched the web if you did not use web_search.
- If the user asks to create one file, call create_file once and stop.
- Do not list/read a file just to verify a successful create or edit.
- Do not edit or delete unless the user explicitly asks.
- Never delete a file just to recreate or "fix" it.
- If a write tool (create_file, edit_file, delete_file) succeeds, give the
  user the result instead of making more tool calls.
- run_python can execute a .py file that already exists in the sandbox, so
  you can check that code you wrote actually works before reporting back.
"""


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
]


FUNCTIONS = {
    "list_files": list_files,
    "read_file": read_file,
    "create_file": create_file,
    "edit_file": edit_file,
    "delete_file": delete_file,
    "run_python": run_python,
    "web_search": web_search,
}


def run_turn(user_text: str) -> str:
    """Run one request through Ollama's native tool-calling loop."""

    messages: list[dict[str, Any]] = [
        {
            "role": "system",
            "content": SYSTEM_PROMPT,
        },
        {
            "role": "user",
            "content": user_text,
        },
    ]

    calls_used = 0

    while calls_used < MAX_TOOL_CALLS:
        response = ollama.chat(
            model=MODEL,
            messages=messages,
            tools=TOOLS,
        )

        message = response.message
        calls = message.tool_calls or []

        # Some local Qwen/Ollama combinations return a tool call as JSON
        # in message.content instead of populating message.tool_calls.
        # Detect that format and turn it into the same internal tool call.
        if not calls:
            content = (message.content or "").strip()

            try:
                parsed = json.loads(content)

                if (
                    isinstance(parsed, dict)
                    and parsed.get("name") in FUNCTIONS
                    and isinstance(parsed.get("arguments"), dict)
                ):
                    class FunctionCall:
                        pass

                    class Call:
                        pass

                    call = Call()
                    call.function = FunctionCall()
                    call.function.name = parsed["name"]
                    call.function.arguments = parsed["arguments"]
                    calls = [call]

                else:
                    return content or "Done."

            except (json.JSONDecodeError, TypeError):
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

                    result = FUNCTIONS[name](**arguments)

                except Exception as exc:
                    result = f"Error executing {name}: {exc}"

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
                    )
                ):
                    return result + "."

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
        ollama.show(MODEL)

    except Exception:
        print(
            f"Error: model '{MODEL}' is not installed: {MODEL}"
        )
        return False

    return True


def main() -> None:
    """Start the interactive Jarvis terminal."""

    SANDBOX.mkdir(parents=True, exist_ok=True)

    print("Jarvis V0.2.5")
    print(f"Model:   {MODEL}")
    print(f"Sandbox: {SANDBOX}")
    print("Type 'exit' or 'quit' to close.\n")

    if not check_ollama():
        return

    while True:
        try:
            user_text = input("You: ").strip()

        except (KeyboardInterrupt, EOFError):
            print("\nGoodbye.")
            break

        if user_text.lower() in {"exit", "quit"}:
            print("Goodbye.")
            break

        if not user_text:
            continue

        try:
            print(f"Jarvis: {run_turn(user_text)}")

        except Exception as exc:
            print(f"Jarvis error: {exc}")


if __name__ == "__main__":
    main()