"""
Intel Sweep — Web Searcher

Thin wrapper around search APIs. Returns normalized results.
Providers: Google Custom Search, Serper, Brave, Tavily.
"""

import logging
import os
from abc import ABC, abstractmethod
from datetime import datetime, timedelta, timezone

logger = logging.getLogger("intel-sweep.searcher")


class WebSearcher:
    """Delegates to configured search provider."""

    def __init__(self, config: dict):
        provider = config.get("provider", "google")
        self._searcher = _build_searcher(provider)

    async def search(
        self, query: str, max_results: int = 5, lookback_hours: int = 168
    ) -> list[dict]:
        """
        Search and return normalized results.
        Each result: {url, title, snippet, source, published_at}
        """
        results = await self._searcher.search(query, max_results, lookback_hours)
        logger.debug(f"Search '{query}': {len(results)} results")
        return results


class BaseSearchProvider(ABC):
    @abstractmethod
    async def search(
        self, query: str, max_results: int, lookback_hours: int
    ) -> list[dict]: ...


class SerperSearcher(BaseSearchProvider):
    """serper.dev — reliable, cheap, good for production."""

    def __init__(self):
        self.api_key = os.environ["SEARCH_API_KEY"]

    async def search(
        self, query: str, max_results: int, lookback_hours: int
    ) -> list[dict]:
        import aiohttp

        url = "https://google.serper.dev/search"
        headers = {"X-API-KEY": self.api_key, "Content-Type": "application/json"}

        tbs = _lookback_to_tbs(lookback_hours)
        payload = {"q": query, "num": max_results}
        if tbs:
            payload["tbs"] = tbs

        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, headers=headers) as resp:
                resp.raise_for_status()
                data = await resp.json()

        return [
            {
                "url": r.get("link", ""),
                "title": r.get("title", ""),
                "snippet": r.get("snippet", ""),
                "source": r.get("source", ""),
                "published_at": r.get("date"),
            }
            for r in data.get("organic", [])
        ]


class TavilySearcher(BaseSearchProvider):
    """Tavily — AI-optimized search, good relevance."""

    def __init__(self):
        self.api_key = os.environ["SEARCH_API_KEY"]

    async def search(
        self, query: str, max_results: int, lookback_hours: int
    ) -> list[dict]:
        import aiohttp

        url = "https://api.tavily.com/search"
        payload = {
            "api_key": self.api_key,
            "query": query,
            "max_results": max_results,
            "search_depth": "basic",
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload) as resp:
                resp.raise_for_status()
                data = await resp.json()

        return [
            {
                "url": r.get("url", ""),
                "title": r.get("title", ""),
                "snippet": r.get("content", ""),
                "source": r.get("url", "").split("/")[2] if r.get("url") else "",
                "published_at": r.get("published_date"),
            }
            for r in data.get("results", [])
        ]


class BraveSearcher(BaseSearchProvider):
    """Brave Search API."""

    def __init__(self):
        self.api_key = os.environ["SEARCH_API_KEY"]

    async def search(
        self, query: str, max_results: int, lookback_hours: int
    ) -> list[dict]:
        import aiohttp

        url = "https://api.search.brave.com/res/v1/web/search"
        headers = {"X-Subscription-Token": self.api_key, "Accept": "application/json"}
        params = {"q": query, "count": max_results}

        if lookback_hours <= 24:
            params["freshness"] = "pd"
        elif lookback_hours <= 168:
            params["freshness"] = "pw"
        elif lookback_hours <= 720:
            params["freshness"] = "pm"

        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params, headers=headers) as resp:
                resp.raise_for_status()
                data = await resp.json()

        return [
            {
                "url": r.get("url", ""),
                "title": r.get("title", ""),
                "snippet": r.get("description", ""),
                "source": r.get("url", "").split("/")[2] if r.get("url") else "",
                "published_at": r.get("age"),
            }
            for r in data.get("web", {}).get("results", [])
        ]


def _build_searcher(provider: str) -> BaseSearchProvider:
    searchers = {
        "serper": SerperSearcher,
        "tavily": TavilySearcher,
        "brave": BraveSearcher,
        "google": SerperSearcher,  # default to serper as Google CSE wrapper
    }
    if provider not in searchers:
        raise ValueError(f"Unknown search provider: {provider}. Use: {list(searchers)}")
    return searchers[provider]()


def _lookback_to_tbs(hours: int) -> str | None:
    """Convert lookback hours to Google tbs parameter."""
    if hours <= 24:
        return "qdr:d"
    elif hours <= 168:
        return "qdr:w"
    elif hours <= 720:
        return "qdr:m"
    return None
