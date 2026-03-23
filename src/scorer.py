"""
Intel Sweep — Relevance Scorer

Scores search results against topic-specific relevance prompts.
Returns a float 0.0–1.0. Deterministic-ish via low temperature.
"""

import json
import logging
import os
from abc import ABC, abstractmethod

logger = logging.getLogger("intel-sweep.scorer")

SCORING_SYSTEM_PROMPT = """You are a relevance scoring engine. Given an article title, 
snippet, and URL, score its relevance according to the criteria provided.

Respond with ONLY a JSON object, no markdown, no preamble:
{"score": 0.0 to 1.0, "reason": "one sentence explanation"}

Scoring guide:
- 0.9-1.0: Directly actionable intelligence (competitor funding, product launch, regulatory change)
- 0.7-0.89: Highly relevant context (market analysis, technology shift, adjacent competitor)
- 0.5-0.69: Moderately relevant (industry trend, tangential mention)
- 0.3-0.49: Low relevance (general news with minor connection)
- 0.0-0.29: Not relevant
"""


class RelevanceScorer:
    """Factory that delegates to the configured provider."""

    def __init__(self, config: dict):
        provider = config.get("provider", "gemini")
        self.model = config.get("model", "gemini-2.5-flash")
        self.temperature = config.get("temperature", 0.1)

        self._scorer = _build_scorer(provider, self.model, self.temperature)

    async def score(
        self,
        content: str,
        title: str,
        url: str,
        relevance_prompt: str,
    ) -> float:
        """Score a single result. Returns 0.0–1.0."""
        user_prompt = f"""Relevance criteria:
{relevance_prompt}

Article to score:
Title: {title}
URL: {url}
Snippet: {content[:1000]}
"""
        try:
            result = await self._scorer.call(user_prompt)
            parsed = json.loads(result)
            score = float(parsed.get("score", 0.0))
            reason = parsed.get("reason", "")
            logger.debug(f"Score {score:.2f} for '{title}': {reason}")
            return max(0.0, min(1.0, score))  # clamp
        except (json.JSONDecodeError, KeyError, ValueError) as e:
            logger.warning(f"Scoring parse error for '{title}': {e}")
            return 0.0
        except Exception as e:
            logger.error(f"Scoring API error for '{title}': {e}")
            return 0.0


class BaseScorerProvider(ABC):
    @abstractmethod
    async def call(self, user_prompt: str) -> str:
        """Send prompt to LLM, return raw response text."""
        ...


class GeminiScorer(BaseScorerProvider):
    def __init__(self, model: str, temperature: float):
        self.model = model
        self.temperature = temperature
        self.api_key = os.environ["SCORING_API_KEY"]

    async def call(self, user_prompt: str) -> str:
        import aiohttp

        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{self.model}:generateContent?key={self.api_key}"
        )
        payload = {
            "contents": [{"parts": [{"text": user_prompt}]}],
            "systemInstruction": {"parts": [{"text": SCORING_SYSTEM_PROMPT}]},
            "generationConfig": {"temperature": self.temperature},
        }
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload) as resp:
                resp.raise_for_status()
                data = await resp.json()
                return data["candidates"][0]["content"]["parts"][0]["text"]


class OllamaScorer(BaseScorerProvider):
    def __init__(self, model: str, temperature: float):
        self.model = model
        self.temperature = temperature
        self.base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")

    async def call(self, user_prompt: str) -> str:
        import aiohttp

        url = f"{self.base_url}/api/generate"
        payload = {
            "model": self.model,
            "system": SCORING_SYSTEM_PROMPT,
            "prompt": user_prompt,
            "stream": False,
            "options": {"temperature": self.temperature},
        }
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload) as resp:
                resp.raise_for_status()
                data = await resp.json()
                return data["response"]


class AnthropicScorer(BaseScorerProvider):
    def __init__(self, model: str, temperature: float):
        self.model = model
        self.temperature = temperature
        self.api_key = os.environ["SCORING_API_KEY"]

    async def call(self, user_prompt: str) -> str:
        import aiohttp

        url = "https://api.anthropic.com/v1/messages"
        headers = {
            "x-api-key": self.api_key,
            "content-type": "application/json",
            "anthropic-version": "2023-06-01",
        }
        payload = {
            "model": self.model,
            "max_tokens": 200,
            "temperature": self.temperature,
            "system": SCORING_SYSTEM_PROMPT,
            "messages": [{"role": "user", "content": user_prompt}],
        }
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, headers=headers) as resp:
                resp.raise_for_status()
                data = await resp.json()
                return data["content"][0]["text"]


class OpenAIScorer(BaseScorerProvider):
    def __init__(self, model: str, temperature: float):
        self.model = model
        self.temperature = temperature
        self.api_key = os.environ["SCORING_API_KEY"]

    async def call(self, user_prompt: str) -> str:
        import aiohttp

        url = "https://api.openai.com/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "temperature": self.temperature,
            "messages": [
                {"role": "system", "content": SCORING_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
        }
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, headers=headers) as resp:
                resp.raise_for_status()
                data = await resp.json()
                return data["choices"][0]["message"]["content"]


def _build_scorer(
    provider: str, model: str, temperature: float
) -> BaseScorerProvider:
    scorers = {
        "gemini": GeminiScorer,
        "ollama": OllamaScorer,
        "anthropic": AnthropicScorer,
        "openai": OpenAIScorer,
    }
    if provider not in scorers:
        raise ValueError(f"Unknown scoring provider: {provider}. Use: {list(scorers)}")
    return scorers[provider](model, temperature)
