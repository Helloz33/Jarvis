from __future__ import annotations

import subprocess
import sys

from .filesystem import SANDBOX, safe_path

PYTHON_TIMEOUT_SECONDS = 10
MAX_OUTPUT_CHARS = 4000


def run_python(path: str, args: list[str] | None = None, timeout: int | None = None) -> str:
    """Run an existing .py file inside Test/ and return its output.

    NOTE: this restricts *which file* can be run (must be inside the
    sandbox), but the script itself still runs with full Python privileges
    (network, etc.). Treat it as a convenience for testing your own code,
    not a security sandbox for untrusted code.
    """
    try:
        target = safe_path(path, must_exist=True)

        if target.is_dir():
            return "Error: that path is a directory."
        if target.suffix != ".py":
            return "Error: run_python can only execute .py files."

        args = args or []
        if not isinstance(args, list) or not all(isinstance(a, str) for a in args):
            return "Error: args must be a list of strings."

        run_timeout = timeout or PYTHON_TIMEOUT_SECONDS

        completed = subprocess.run(
            [sys.executable, "-I", str(target), *args],
            cwd=SANDBOX,
            capture_output=True,
            text=True,
            timeout=run_timeout,
        )

        def trim(text: str) -> str:
            if len(text) > MAX_OUTPUT_CHARS:
                return text[:MAX_OUTPUT_CHARS] + "\n...[output truncated]"
            return text

        parts = [f"Exit code: {completed.returncode}"]
        if completed.stdout.strip():
            parts.append(f"stdout:\n{trim(completed.stdout.strip())}")
        if completed.stderr.strip():
            parts.append(f"stderr:\n{trim(completed.stderr.strip())}")
        return "\n\n".join(parts)

    except subprocess.TimeoutExpired:
        return f"Error: script timed out after {timeout or PYTHON_TIMEOUT_SECONDS}s."
    except (ValueError, FileNotFoundError, PermissionError, OSError) as exc:
        return f"Error: {exc}"