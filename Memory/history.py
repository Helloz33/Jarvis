"""Short-term memory: the last few turns of this conversation.

Only the user's words and Jarvis's final reply are kept. Tool calls and raw
tool output are dropped so they don't eat the (small) context window.
"""
from __future__ import annotations

import threading

MAX_TURNS = 10   # one turn = one user message + one Jarvis reply
MAX_CHARS = 700  # each stored message is trimmed to this length


class History:
    def __init__(self, max_turns: int = MAX_TURNS) -> None:
        self.max_turns = max_turns
        self._turns: list[tuple[str, str]] = []
        self._lock = threading.Lock()

    def add_turn(self, user_text: str, reply: str) -> None:
        with self._lock:
            self._turns.append((user_text[:MAX_CHARS], reply[:MAX_CHARS]))
            self._turns = self._turns[-self.max_turns:]

    def messages(self) -> list[dict]:
        with self._lock:
            out: list[dict] = []
            for user_text, reply in self._turns:
                out.append({"role": "user", "content": user_text})
                out.append({"role": "assistant", "content": reply})
            return out

    def snapshot(self) -> list[tuple[str, str]]:
        with self._lock:
            return list(self._turns)

    def clear(self) -> None:
        with self._lock:
            self._turns = []

    def __len__(self) -> int:
        with self._lock:
            return len(self._turns)