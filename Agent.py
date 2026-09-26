from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import ollama

MODEL = "qwen2.5-coder:7b"
SANDBOX = (Path.home() / "Jarvis" / "test").resolve()
MAX_TOOL_CALLS = 8


SYSTEM_PROMPT = f"""
You are Jarvis V0.1, a simple local file assistant.

You may ONLY access files through the provided tools, and only inside:
{SANDBOX}

Rules:
- Never use shell commands.
- Only use a tool when the user's request requires it.
- If the user asks to create one file, call create_file once and stop.
- Do not list/read a file just to verify a successful create or edit.
- Do not edit or delete unless the user explicitly asks.
- Never delete a file just to recreate or "fix" it.
- If a write tool succeeds, give the user the result instead of making more tool calls.
"""


def safe_path(relative_path: str, must_exist: bool = False) -> Path:
    """Resolve a relative path and prove it stays inside the sandbox."""
    if not isinstance(relative_path, str) or not relative_path.strip():
        raise ValueError("Path must be a non-empty relative path.")

    raw = Path(relative_path).expanduser()

    if raw.is_absolute():
        raise ValueError("Absolute paths are not allowed.")

    target = (SANDBOX / raw).resolve(strict=False)

    try:
        target.relative_to(SANDBOX)
    except ValueError as exc:
        raise ValueError("Path is outside the testing/ sandbox.") from exc

    if must_exist and not target.exists():
        raise FileNotFoundError(f"{relative_path} does not exist.")

    return target


def list_files() -> str:
    """List files and directories directly inside testing/."""
    try:
        items = []
        for path in sorted(SANDBOX.iterdir(), key=lambda p: p.name.lower()):
            kind = "dir" if path.is_dir() else "file"
            items.append(f"{kind}: {path.name}")
        return "\n".join(items) if items else "testing/ is empty."
    except PermissionError:
        return "Error: permission denied."


def read_file(path: str) -> str:
    """Read a UTF-8 text file inside testing/."""
    try:
        target = safe_path(path, must_exist=True)
        if target.is_dir():
            return "Error: that path is a directory."
        return target.read_text(encoding="utf-8")
    except (ValueError, FileNotFoundError, PermissionError, UnicodeDecodeError) as exc:
        return f"Error: {exc}"


def create_file(path: str, content: str) -> str:
    """Create a new file without overwriting an existing file."""
    try:
        target = safe_path(path)

        if target.exists():
            return f"Error: {path} already exists. It was NOT overwritten."

        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return f"Created testing/{target.relative_to(SANDBOX)}"
    except (ValueError, PermissionError, OSError) as exc:
        return f"Error: {exc}"


def edit_file(path: str, content: str) -> str:
    """Replace the contents of an existing text file."""
    try:
        target = safe_path(path, must_exist=True)

        if target.is_dir():
            return "Error: that path is a directory."

        target.write_text(content, encoding="utf-8")
        return f"Edited testing/{target.relative_to(SANDBOX)}"
    except (ValueError, FileNotFoundError, PermissionError, OSError) as exc:
        return f"Error: {exc}"


def delete_file(path: str) -> str:
    """Delete one file after explicit confirmation."""
    try:
        target = safe_path(path, must_exist=True)

        if target.is_dir():
            return "Error: deleting directories is not supported."

        relative = target.relative_to(SANDBOX)
        answer = input(
            f'Jarvis wants to delete "testing/{relative}". Continue? [y/N]: '
        ).strip().lower()

        if answer not in {"y", "yes"}:
            return "Deletion cancelled by the user. Do not retry the deletion."

        target.unlink()
        return f"Deleted testing/{relative}"
    except (ValueError, FileNotFoundError, PermissionError, OSError) as exc:
        return f"Error: {exc}"


TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "list_files",
            "description": "List files and directories inside testing/.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read a text file inside testing/. Use a relative path.",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_file",
            "description": "Create a new text file inside testing/. Never overwrite an existing file.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "edit_file",
            "description": "Replace the contents of an existing text file inside testing/.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_file",
            "description": "Delete a file inside testing/. Always ask the user for confirmation.",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
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
}


def run_turn(user_text: str) -> str:
    """Run one request through Ollama's native tool-calling loop."""
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_text},
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

            print(f"[tool] {name}: {result}")

            messages.append({
                "role": "tool",
                "tool_name": name,
                "content": result,
            })

            calls_used += 1

            # IMPORTANT:
            # Once a write/delete operation succeeds, end this turn.
            # This prevents the small model from doing:
            # create -> list -> read -> edit -> delete -> recreate...
            if name in {"create_file", "edit_file", "delete_file"}:
                if result.startswith(
                    ("Created ", "Edited ", "Deleted ", "Deletion cancelled")
                ):
                    return result + "."

            if calls_used >= MAX_TOOL_CALLS:
                return "I stopped because the tool-call safety limit was reached."

    return "I stopped because the tool-call safety limit was reached."


def check_ollama() -> bool:
    """Check that Ollama is running and the selected model is installed."""
    try:
        ollama.list()
    except Exception as exc:
        print(f"Error: Ollama is not running or is unreachable: {exc}")
        return False

    try:
        ollama.show(MODEL)
    except Exception:
        print(f"Error: model '{MODEL}' is not installed: {MODEL}")
        return False

    return True


def main() -> None:
    """Start the interactive Jarvis terminal."""
    SANDBOX.mkdir(parents=True, exist_ok=True)

    print("Jarvis V0.1")
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
