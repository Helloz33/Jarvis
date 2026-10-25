"""End-of-session summary: 2-3 sentences stored as a long-term memory."""
from __future__ import annotations

import Llm

MIN_TURNS = 2   # don't summarize a one-line chat

PROMPT = (
    "Summarize this conversation between a user and their assistant Jarvis in "
    "at most 2 short sentences, under 250 characters in total. Capture what the user wanted, what was done, "
    "and any lasting facts, preferences or decisions. Write plain notes in the "
    "third person. Do not list individual schedule entries (they live in the schedule itself) "
    "and only state a change as done if the conversation clearly confirms it. Output only the summary."
)


def summarize(turns: list[tuple[str, str]], model: str) -> str:
    transcript = "\n".join(f"User: {u}\nJarvis: {a}" for u, a in turns)
    response = Llm.chat(
        model,
        [
            {"role": "system", "content": PROMPT},
            {"role": "user", "content": transcript},
        ],
    )
    return " ".join((response.message.content or "").split())