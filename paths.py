"""Where everything lives. Code and personal data are kept apart, so an update (or a packaged app,
whose code folder is read-only) never touches your schedule, memories or logs.

    ROOT          the project folder (the code)
    SANDBOX       Test/ inside the project: the only folder the assistant's file tools may use
    DATA_ROOT     where personal data lives. For now this is the project folder itself, exactly
                  where your data already is. Set IRIS_DATA_DIR to move it (the V1.0 app will use
                  ~/Library/Application Support/Iris on macOS and %APPDATA%\\Iris on Windows).
    MEMORY_DIR    long-term memory         (DATA_ROOT/memory_data)
    SCHEDULE_DIR  schedule, notes, timers  (DATA_ROOT/Schedule_data)
    LOG_DIR       the Log Book             (DATA_ROOT/logs)

Read these through the module (paths.SCHEDULE_DIR), not with "from paths import ...", so that
use_data_root() (used by the tests) is seen everywhere.
"""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SANDBOX = (ROOT / "Test").resolve()

DATA_ROOT: Path
MEMORY_DIR: Path
SCHEDULE_DIR: Path
LOG_DIR: Path


def use_data_root(folder) -> None:
    """Point every data folder at a new place (the tests use a temporary folder)."""
    global DATA_ROOT, MEMORY_DIR, SCHEDULE_DIR, LOG_DIR
    DATA_ROOT = Path(folder).expanduser().resolve()
    MEMORY_DIR = DATA_ROOT / "memory_data"
    SCHEDULE_DIR = DATA_ROOT / "Schedule_data"
    LOG_DIR = DATA_ROOT / "logs"


use_data_root(os.getenv("IRIS_DATA_DIR") or ROOT)
