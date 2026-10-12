"""Turn text into embeddings (via Ollama) and search them with plain numpy.

No vector database: for a personal assistant (hundreds to a few thousand
memories) comparing one vector against all of them takes milliseconds.
If the embedding model isn't installed we fall back to keyword matching, so
memory still works (just less smartly).
"""
from __future__ import annotations

import os
import re

import numpy as np
import ollama

EMBED_MODEL = os.getenv("JARVIS_EMBED_MODEL", "nomic-embed-text")


def embed(text: str) -> list[float] | None:
    """Return an embedding, or None if the embedding model is unavailable."""
    try:
        response = ollama.embed(model=EMBED_MODEL, input=text)
        return list(response.embeddings[0])
    except Exception:
        return None


def embedding_ready() -> bool:
    return embed("ping") is not None


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9']+", text.lower()) if len(w) > 2}


def search(query: str, memories: list[dict], k: int, threshold: float,
           query_vec: list[float] | None = None) -> list[tuple[float, dict]]:
    """Return up to k (score, memory) pairs, best first."""
    if not memories:
        return []

    if query_vec is None:
        query_vec = embed(query)

    scored: list[tuple[float, dict]] = []

    if query_vec is not None:
        q = np.asarray(query_vec, dtype=np.float32)
        qn = np.linalg.norm(q)
        if qn > 0:
            for m in memories:
                vec = m.get("embedding")
                if not vec or len(vec) != len(q):
                    continue
                v = np.asarray(vec, dtype=np.float32)
                vn = np.linalg.norm(v)
                if vn == 0:
                    continue
                score = float(np.dot(q, v) / (qn * vn))
                if score >= threshold:
                    scored.append((score, m))

    if not scored:
        # Keyword fallback: used when there is no embedding model, or when
        # older memories were saved without an embedding.
        qw = _words(query)
        if qw:
            for m in memories:
                overlap = len(qw & _words(m["text"]))
                if overlap:
                    scored.append((overlap / len(qw), m))

    scored.sort(key=lambda pair: pair[0], reverse=True)
    return scored[:k]