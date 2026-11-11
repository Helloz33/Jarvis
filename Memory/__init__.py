"""Long-term memory (V0.5).

Layers:
  1. history      - last few turns of this conversation (short-term)
  2. profile.md   - curated facts, always in the prompt
  3. memories     - episodic facts, retrieved by similarity each turn
  4. summaries    - a short note saved when a session ends
"""
from __future__ import annotations

import json
import os
import threading
import time

import paths

from . import embeddings, store
from .history import History
from .summarizer import MIN_TURNS, summarize

RECALL_K = 4              # how many memories to inject per turn
RECALL_THRESHOLD = 0.4    # minimum cosine similarity (keyword fallback ignores it)
INCLUDE_ALL_BELOW = 12    # while there are this few memories, just include them all

history = History()

_event_handler = None


def set_event_handler(handler) -> None:
    """handler(kind, detail): lets the UI log automatic memory activity."""
    global _event_handler
    _event_handler = handler


def _event(kind: str, detail: str) -> None:
    if _event_handler is not None:
        try:
            _event_handler(kind, detail)
        except Exception:
            pass


# --- operations the tools use -------------------------------------------------
def remember(text: str, source: str = "user_asked") -> dict | None:
    return store.add_memory(text, source, embeddings.embed(text))


def recall(query: str, k: int = RECALL_K, threshold: float = RECALL_THRESHOLD):
    return embeddings.search(query, store.load_memories(), k, threshold)


def forget(memory_id: str) -> bool:
    return store.delete_memory(memory_id)


# --- used by the agent every turn ---------------------------------------------
def context_for(user_text: str) -> tuple[str, list[str]]:
    """Return (profile text, memory lines) for this user message.

    With a small store every memory goes into the prompt, so the assistant uses them
    naturally without being asked. Once the store grows, only the closest
    matches (by meaning) are included.
    """
    profile = store.read_profile()
    items = store.load_memories()

    if len(items) <= INCLUDE_ALL_BELOW:
        chosen = sorted(items, key=lambda m: m["created"], reverse=True)
    else:
        chosen = [m for _, m in recall(user_text)]
        if chosen:
            _event("auto_recall", f"{len(chosen)} memories for: {user_text[:60]}")

    return profile, [f"[{m['id']}] {m['text']}" for m in chosen]


# --- session end ---------------------------------------------------------------
def _trim(text: str, limit: int = 270) -> str:
    """Shorten to whole sentences so a saved summary never ends mid-word."""
    if len(text) <= limit:
        return text
    cut = text[:limit]
    end = max(cut.rfind(". "), cut.rfind("! "), cut.rfind("? "), cut.rfind("."))
    return cut[: end + 1] if end > 40 else cut.rsplit(" ", 1)[0] + "..."


# The session lives on disk while it is going on, so nothing is lost however it ends:
#   memory_data/session_current.json   the conversation in progress (rewritten every turn)
#   memory_data/sessions_pending/      finished sessions waiting for their summary
# A pending file is deleted only after its summary is saved, so a summary that fails
# (Ollama not running, the app closed half-way) is simply tried again next time.
_summary_lock = threading.Lock()


def _session_file():
    return paths.MEMORY_DIR / "session_current.json"


def _pending_dir():
    return paths.MEMORY_DIR / "sessions_pending"


def _write_json(path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data), encoding="utf-8")
    os.replace(tmp, path)          # all or nothing: a crash never leaves half a file


def _persist(data) -> None:
    path = _session_file()
    if data is None:
        path.unlink(missing_ok=True)
    else:
        _write_json(path, data)


history.on_change = _persist


def _queue(data) -> bool:
    """Put a finished session in the pending folder. Returns False if it is too short to keep."""
    if not data or len(data.get("turns", [])) < MIN_TURNS:
        return False
    started = data.get("started") or time.time()
    _write_json(_pending_dir() / f"{int(started * 1000)}.json", data)
    return True


def _summarize_pending(model: str) -> int:
    """Summarize every pending session, oldest first. Returns how many were saved."""
    saved = 0
    with _summary_lock:
        folder = _pending_dir()
        while True:
            files = sorted(folder.glob("*.json")) if folder.exists() else []
            if not files:
                break
            path = files[0]
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                turns = [tuple(t) for t in data.get("turns", [])]
            except (OSError, ValueError):
                path.unlink(missing_ok=True)       # unreadable: drop it rather than retry forever
                continue
            if len(turns) < MIN_TURNS:
                path.unlink(missing_ok=True)
                continue
            text = _trim(summarize(turns, model))   # raises if Ollama is down: the file stays
            day = time.strftime("%Y-%m-%d", time.localtime(data.get("started") or time.time()))
            if text:
                entry = store.add_memory(f"Session {day}: {text}", "session_summary", embeddings.embed(text))
                _event("summary", entry["text"] if entry else "duplicate, skipped")
            path.unlink(missing_ok=True)
            saved += 1
    return saved


def _run_summaries(model: str, on_done=None, wait: bool = False, timeout: float = 60) -> None:
    def work() -> None:
        try:
            _summarize_pending(model)
        except Exception as exc:
            _event("summary_error", f"{exc} (kept, will retry next start)")
        finally:
            if on_done:
                on_done()

    thread = threading.Thread(target=work, daemon=True, name="session-summary")
    thread.start()
    if wait:
        thread.join(timeout)


def end_session(model: str, on_done=None, wait: bool = False, timeout: float = 60) -> bool:
    """The conversation is over (bye, STOP, idle, quit): summarize it into long-term memory
    and start a fresh one. wait=True blocks until the summary is saved (or timeout).

    Returns True if there was a session worth summarizing.
    """
    queued = _queue(history.take())
    if queued or _has_pending():
        _run_summaries(model, on_done, wait, timeout)
    return queued


def _has_pending() -> bool:
    folder = _pending_dir()
    return folder.exists() and any(folder.glob("*.json"))


def recover_session(model: str, on_done=None) -> bool:
    """At startup: summarize a session the app never got to finish (crash, force quit,
    closed window) and any summaries that failed before. Returns True if there was work."""
    path = _session_file()
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = None
        _queue(data)
        path.unlink(missing_ok=True)
    if not _has_pending():
        return False
    _event("recover", "summarizing an unsaved earlier session")
    _run_summaries(model, on_done)
    return True


def stats() -> dict:
    return {"memories": store.count(), "profile_words": store.profile_words()}


__all__ = [
    "history", "remember", "recall", "forget", "context_for", "end_session", "recover_session",
    "set_event_handler", "stats", "store", "embeddings",
    "RECALL_K", "RECALL_THRESHOLD", "INCLUDE_ALL_BELOW",
]