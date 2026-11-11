"""Short-term memory: this conversation.

Two views of the same conversation:
  * the window: the last few turns, given to the model every turn (small context);
  * the full transcript: every turn of the session, used for the end-of-session summary.

Only the user's words and the assistant's final reply are kept. Tool calls and raw
tool output are dropped so they don't eat the (small) context window.

Every change is passed to on_change (set by Memory), which writes the session to disk,
so a session survives STOP, closing the window, a crash or a power cut.
"""
from __future__ import annotations

import threading
import time

MAX_TURNS = 10        # one turn = one user message + one reply (the model's window)
MAX_CHARS = 700       # each stored message is trimmed to this length
MAX_FULL_TURNS = 120  # the transcript kept for the summary


class History:
    def __init__(self, max_turns: int = MAX_TURNS) -> None:
        self.max_turns = max_turns
        self._turns: list[tuple[str, str]] = []
        self._full: list[tuple[str, str]] = []
        self.started: float | None = None
        self.last: float = 0.0
        self.on_change = None          # on_change(dict | None)
        self._lock = threading.Lock()

    def _dump(self) -> dict | None:
        if not self._full:
            return None
        return {"started": self.started, "last": self.last, "turns": [list(t) for t in self._full]}

    def _changed(self, data: dict | None) -> None:
        if self.on_change is not None:
            try:
                self.on_change(data)
            except Exception:
                pass

    def add_turn(self, user_text: str, reply: str) -> None:
        turn = (user_text[:MAX_CHARS], reply[:MAX_CHARS])
        with self._lock:
            now = time.time()
            self.started = self.started or now
            self.last = now
            self._turns.append(turn)
            self._turns = self._turns[-self.max_turns:]
            self._full.append(turn)
            self._full = self._full[-MAX_FULL_TURNS:]
            data = self._dump()
        self._changed(data)

    def messages(self) -> list[dict]:
        with self._lock:
            out: list[dict] = []
            for user_text, reply in self._turns:
                out.append({"role": "user", "content": user_text})
                out.append({"role": "assistant", "content": reply})
            return out

    def snapshot(self) -> list[tuple[str, str]]:
        """The whole session so far (not just the model's window)."""
        with self._lock:
            return list(self._full)

    def take(self) -> dict | None:
        """Hand over the session (for summarizing) and start a new, empty one."""
        with self._lock:
            data = self._dump()
            self._turns, self._full = [], []
            self.started, self.last = None, 0.0
        self._changed(None)
        return data

    def clear(self) -> None:
        self.take()

    def __len__(self) -> int:
        with self._lock:
            return len(self._full)