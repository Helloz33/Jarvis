"""One place that talks to Ollama's chat endpoint.

Turns "thinking" off by default: reasoning models (Qwen3 family) otherwise
think for several seconds before answering, which is painful in a voice
assistant. Models or Ollama versions that don't know the `think` option are
handled by retrying without it.
"""
from __future__ import annotations

import ollama

THINK = False


def chat(model: str, messages: list, tools: list | None = None):
    kwargs = {"model": model, "messages": messages}
    if tools:
        kwargs["tools"] = tools
    try:
        return ollama.chat(think=THINK, **kwargs)
    except TypeError:
        # Older ollama Python client: no `think` argument.
        return ollama.chat(**kwargs)
    except Exception as exc:
        if "think" in str(exc).lower():
            # Model doesn't support the think switch.
            return ollama.chat(**kwargs)
        raise