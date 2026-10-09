from __future__ import annotations

import difflib
from pathlib import Path

# Jarvis/Tools/filesystem.py -> parent is Jarvis/Tools -> parent.parent is Jarvis/
SANDBOX = (Path(__file__).resolve().parent.parent / "Test").resolve()


# --- Confirmation hook -------------------------------------------------
# The UI registers a handler so edits/deletes show the Yes/No popup.
# With no handler (plain terminal use) we fall back to input().
_confirm_handler = None


def set_confirm_handler(handler) -> None:
    """handler(action, path, detail) -> bool"""
    global _confirm_handler
    _confirm_handler = handler


def _confirm(action: str, relative: str, detail: str = "") -> bool:
    if _confirm_handler is not None:
        return bool(_confirm_handler(action, relative, detail))
    answer = input(
        f'Jarvis wants to {action} "Test/{relative}". Continue? [y/N]: '
    ).strip().lower()
    return answer in {"y", "yes"}


def _normalize_content(content: str) -> str:
    """Fix a common small-model glitch: writing literal backslash-n instead
    of real newlines when it builds multi-line file content for a tool call.

    Only kicks in when there are zero real newlines but literal \\n/\\t
    sequences are present, so it won't touch legitimate code that has an
    actual escape sequence inside a real string literal on its own line.
    """
    if isinstance(content, str) and "\n" not in content and "\\n" in content:
        content = content.replace("\\r\\n", "\n").replace("\\n", "\n").replace("\\t", "\t")
    return content


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
        raise ValueError("Path is outside the Test/ sandbox.") from exc

    if must_exist and not target.exists():
        raise FileNotFoundError(f"{relative_path} does not exist.")

    return target


def list_files() -> str:
    """List files and directories directly inside Test/."""
    try:
        items = []
        for path in sorted(SANDBOX.iterdir(), key=lambda p: p.name.lower()):
            kind = "dir" if path.is_dir() else "file"
            items.append(f"{kind}: {path.name}")
        return "\n".join(items) if items else "Test/ is empty."
    except PermissionError:
        return "Error: permission denied."


def read_file(path: str) -> str:
    """Read a UTF-8 text file inside Test/."""
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
        target.write_text(_normalize_content(content), encoding="utf-8")
        return f"Created Test/{target.relative_to(SANDBOX)}"
    except (ValueError, PermissionError, OSError) as exc:
        return f"Error: {exc}"


def edit_file(path: str, content: str) -> str:
    """Replace the contents of an existing text file."""
    try:
        target = safe_path(path, must_exist=True)

        if target.is_dir():
            return "Error: that path is a directory."

        relative = target.relative_to(SANDBOX)
        new = _normalize_content(content)
        try:
            old = target.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            old = ""

        diff_lines = list(difflib.unified_diff(
            old.splitlines(), new.splitlines(), "before", "after", lineterm="", n=2))
        detail = "\n".join(diff_lines[:40]) or "(no visible changes)"

        if not _confirm("edit", str(relative), detail):
            return "Edit cancelled by the user. Do not retry the edit."

        target.write_text(new, encoding="utf-8")
        return f"Edited Test/{relative}"
    except (ValueError, FileNotFoundError, PermissionError, OSError) as exc:
        return f"Error: {exc}"


def delete_file(path: str) -> str:
    """Delete one file after explicit confirmation."""
    try:
        target = safe_path(path, must_exist=True)

        if target.is_dir():
            return "Error: deleting directories is not supported."

        relative = target.relative_to(SANDBOX)
        size = target.stat().st_size

        if not _confirm("delete", str(relative), f"{size} bytes. This cannot be undone."):
            return "Deletion cancelled by the user. Do not retry the deletion."

        target.unlink()
        return f"Deleted Test/{relative}"
    except (ValueError, FileNotFoundError, PermissionError, OSError) as exc:
        return f"Error: {exc}"