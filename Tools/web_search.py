import os
import time

from tavily import TavilyClient

# Connection hiccups (an SSL error, a timeout, a dropped connection) are usually gone a second
# later, so a failed search is quietly tried once more before giving up.
RETRY_DELAY = 1.5


def _plain_reason(exc: Exception) -> str:
    text = f"{type(exc).__name__} {exc}".lower()
    if "ssl" in text or "certificate" in text:
        return "a secure-connection (SSL) problem"
    if "timeout" in text or "timed out" in text:
        return "the search service took too long to answer"
    if any(w in text for w in ("connect", "network", "resolve", "unreachable", "dns")):
        return "the search service could not be reached (is the internet on?)"
    if any(w in text for w in ("401", "403", "unauthorized", "invalid api key", "forbidden")):
        return "the Tavily API key was refused (check TAVILY_API_KEY in .env)"
    if "429" in text or "rate limit" in text or "usage limit" in text:
        return "the search limit was reached for now"
    return "the search service returned an error"


def _transient(exc: Exception) -> bool:
    reason = _plain_reason(exc)
    return reason.startswith(("a secure-connection", "the search service took", "the search service could not",
                              "the search service returned"))


def web_search(query: str):
    """Search the web using Tavily."""

    api_key = os.getenv("TAVILY_API_KEY")

    if not api_key:
        raise RuntimeError(
            "web search is not set up: add TAVILY_API_KEY to the .env file."
        )

    if not isinstance(query, str) or not query.strip():
        raise ValueError(
            "Search query must be a non-empty string."
        )

    client = TavilyClient(api_key=api_key)

    for attempt in (1, 2):
        try:
            response = client.search(
                query=query,
                search_depth="basic",
                max_results=5,
            )
            break
        except Exception as exc:
            if attempt == 1 and _transient(exc):
                time.sleep(RETRY_DELAY)
                continue
            raise RuntimeError(f"the web search did not work: {_plain_reason(exc)}.") from exc

    results = []

    for result in response.get("results", []):
        results.append({
            "title": result.get("title", ""),
            "url": result.get("url", ""),
            "description": result.get("content", ""),
        })

    return results
