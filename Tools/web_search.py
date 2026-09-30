import os

from tavily import TavilyClient


def web_search(query: str):
    """Search the web using Tavily."""

    api_key = os.getenv("TAVILY_API_KEY")

    if not api_key:
        raise RuntimeError(
            "TAVILY_API_KEY is not set."
        )

    if not isinstance(query, str) or not query.strip():
        raise ValueError(
            "Search query must be a non-empty string."
        )

    client = TavilyClient(api_key=api_key)

    response = client.search(
        query=query,
        search_depth="basic",
        max_results=5,
    )

    results = []

    for result in response.get("results", []):
        results.append({
            "title": result.get("title", ""),
            "url": result.get("url", ""),
            "description": result.get("content", ""),
        })

    return results