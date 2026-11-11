"""End-of-session summary: 2-3 sentences stored as a long-term memory."""
from __future__ import annotations

import Config
import Llm

MIN_TURNS = 2   # don't summarize a one-line chat

PROMPT = (
    "Summarize this conversation between a user and their assistant {name} in "
    "at most 2 short sentences, under 250 characters in total. Capture what the user wanted, what was done, "
    "and any lasting facts, preferences or decisions. Write plain notes in the "
    "third person. Do not list individual schedule entries (they live in the schedule itself) "
    "and only state a change as done if the conversation clearly confirms it. Output only the summary."
)


BUDGET = 9000   # characters of transcript sent to the model (a long session keeps its newest part)


def _transcript(turns: list[tuple[str, str]]) -> str:
    lines, used = [], 0
    for u, a in reversed(turns):
        line = f"User: {u[:400]}\n{Config.NAME}: {a[:400]}"
        if used + len(line) > BUDGET and lines:
            lines.append("(earlier part of the conversation omitted)")
            break
        lines.append(line)
        used += len(line)
    return "\n".join(reversed(lines))


def summarize(turns: list[tuple[str, str]], model: str) -> str:
    transcript = _transcript(turns)
    response = Llm.chat(
        model,
        [
            {"role": "system", "content": PROMPT.format(name=Config.NAME)},
            {"role": "user", "content": transcript},
        ],
    )
    return " ".join((response.message.content or "").split())