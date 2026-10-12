"""Jarvis long-term memory (V0.5).

Layers:
  1. history      - last few turns of this conversation (short-term)
  2. profile.md   - curated facts, always in the prompt
  3. memories     - episodic facts, retrieved by similarity each turn
  4. summaries    - a short note saved when a session ends
"""
from __future__ import annotations

import threading
import time

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

    With a small store every memory goes into the prompt, so Jarvis uses them
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


def end_session(model: str, on_done=None) -> bool:
    """Summarize the finished conversation in the background and clear history.

    Returns True if a summary job was started.
    """
    turns = history.snapshot()
    history.clear()
    if len(turns) < MIN_TURNS:
        return False

    def work() -> None:
        try:
            text = _trim(summarize(turns, model))
            if text:
                entry = store.add_memory(
                    f"Session {time.strftime('%Y-%m-%d')}: {text}",
                    "session_summary",
                    embeddings.embed(text),
                )
                _event("summary", entry["text"] if entry else "duplicate, skipped")
        except Exception as exc:
            _event("summary_error", str(exc))
        finally:
            if on_done:
                on_done()

    threading.Thread(target=work, daemon=True).start()
    return True


def stats() -> dict:
    return {"memories": store.count(), "profile_words": store.profile_words()}


__all__ = [
    "history", "remember", "recall", "forget", "context_for", "end_session",
    "set_event_handler", "stats", "store", "embeddings",
    "RECALL_K", "RECALL_THRESHOLD", "INCLUDE_ALL_BELOW",
]