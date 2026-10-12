"""Disk storage for Jarvis's long-term memory.

Two files live in memory_data/ (gitignored, personal):
  profile.md      - short, curated facts that go in EVERY prompt
  memories.jsonl  - one JSON object per line: id, text, created, source, embedding
"""
from __future__ import annotations

import json
import os
import threading
import time
import uuid
from pathlib import Path

# Jarvis/Memory/store.py -> parent.parent is Jarvis/
DATA_DIR = Path(__file__).resolve().parent.parent / "memory_data"
PROFILE_FILE = DATA_DIR / "profile.md"
MEMORIES_FILE = DATA_DIR / "memories.jsonl"

PROFILE_WORD_CAP = 500      # the profile is sent every turn, so keep it small
MAX_FACT_CHARS = 300        # one memory = one short fact

_lock = threading.RLock()


def _ensure_dir() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)


# --- profile ----------------------------------------------------------------
def read_profile() -> str:
    try:
        return PROFILE_FILE.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def profile_words() -> int:
    return len(read_profile().split())


def append_profile(fact: str) -> str | None:
    """Add a line to the profile. Returns an error string if it won't fit."""
    fact = fact.strip()
    with _lock:
        current = read_profile()
        if len(current.split()) + len(fact.split()) > PROFILE_WORD_CAP:
            return (
                f"The profile is full ({PROFILE_WORD_CAP} words). "
                "Ask the user to trim memory_data/profile.md first."
            )
        _ensure_dir()
        with PROFILE_FILE.open("a", encoding="utf-8") as fh:
            fh.write(("\n" if current else "") + f"- {fact}")
    return None


# --- episodic memories --------------------------------------------------------
def load_memories() -> list[dict]:
    items: list[dict] = []
    with _lock:
        try:
            lines = MEMORIES_FILE.read_text(encoding="utf-8").splitlines()
        except OSError:
            return items
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except ValueError:
            continue                      # skip a corrupt line instead of crashing
        if isinstance(entry, dict) and entry.get("id") and entry.get("text"):
            items.append(entry)
    return items


def _write_all(items: list[dict]) -> None:
    _ensure_dir()
    tmp = MEMORIES_FILE.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        for entry in items:
            fh.write(json.dumps(entry) + "\n")
    os.replace(tmp, MEMORIES_FILE)        # atomic: never leaves a half-written file


def add_memory(text: str, source: str, embedding: list[float] | None) -> dict | None:
    """Store a memory. Returns the entry, or None if an identical one exists."""
    text = " ".join(text.split())[:MAX_FACT_CHARS]
    with _lock:
        items = load_memories()
        if any(m["text"].lower() == text.lower() for m in items):
            return None
        entry = {
            "id": uuid.uuid4().hex[:6],
            "text": text,
            "created": time.strftime("%Y-%m-%d"),
            "source": source,
            "embedding": embedding,
        }
        _ensure_dir()
        with MEMORIES_FILE.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry) + "\n")
    return entry


def get_memory(memory_id: str) -> dict | None:
    for m in load_memories():
        if m["id"] == memory_id:
            return m
    return None


def delete_memory(memory_id: str) -> bool:
    with _lock:
        items = load_memories()
        kept = [m for m in items if m["id"] != memory_id]
        if len(kept) == len(items):
            return False
        _write_all(kept)
    return True


def count() -> int:
    return len(load_memories())