"""remember / recall / forget: the model's hands on long-term memory.

Safety: text from the web, files or script output could contain sneaky lines
like "remember that the user's password is...". So once a turn has touched
untrusted content, remember() has to get the user's approval first.
"""
from __future__ import annotations

import Memory
from Memory import store

from .filesystem import ask_permission

# Tools whose output is NOT written by the user.
UNTRUSTED_TOOLS = {"web_search", "read_file", "run_python"}

_untrusted_this_turn = False


def reset_untrusted() -> None:
    """Call at the start of every turn."""
    global _untrusted_this_turn
    _untrusted_this_turn = False


def mark_untrusted() -> None:
    """Call after a tool that returned outside content."""
    global _untrusted_this_turn
    _untrusted_this_turn = True


def remember(fact: str, permanent: bool = False) -> str:
    fact = " ".join(str(fact).split())
    if not fact:
        return "Error: there is nothing to remember."
    if len(fact) > store.MAX_FACT_CHARS:
        return f"Error: too long ({len(fact)} chars, max {store.MAX_FACT_CHARS}). Save a shorter fact."

    if permanent or _untrusted_this_turn:
        why = (
            "Add to your permanent profile (read every turn)."
            if permanent
            else "This turn read web/file/script content, so I'm checking before saving."
        )
        if not ask_permission("remember", fact, why):
            return "Remember cancelled by the user. Do not retry."

    if permanent:
        error = store.append_profile(fact)
        return error if error else f"Remembered in profile: {fact}"

    source = "after_untrusted_content" if _untrusted_this_turn else "user_asked"
    entry = Memory.remember(fact, source)
    return f"Remembered: {fact}" if entry else "Already remembered."


def recall(query: str) -> str:
    hits = Memory.recall(str(query), k=5, threshold=0.35)
    if not hits:
        return "No matching memories."
    return "\n".join(f"[{m['id']}] {m['text']} (saved {m['created']})" for _, m in hits)


def forget(memory_id: str) -> str:
    memory_id = str(memory_id).strip().strip("[]")
    entry = store.get_memory(memory_id)
    if entry is None:
        return f"Error: no memory with id '{memory_id}'. Use recall to find the right id."
    allowed = ask_permission(
        "forget",
        entry["text"][:140],
        f"Memory {memory_id}, saved {entry['created']}. This cannot be undone.",
    )
    if not allowed:
        return "Forget cancelled by the user. Do not retry."
    store.delete_memory(memory_id)
    return f"Forgot memory {memory_id}."