"""
Layer 1 of Gamut Trust Stack: Content Authenticity Detection.
"""

import re
import math
from typing import Dict, Any, Optional
from dataclasses import dataclass
from urllib.parse import urlparse

try:
    from bs4 import BeautifulSoup
    import aiohttp
except ImportError:
    pass # Assume installed via requirements

@dataclass
class AuthenticityResult:
    source_score: float
    heuristic_score: float
    llm_score: Optional[float]
    composite_score: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source_score": self.source_score,
            "heuristic_score": self.heuristic_score,
            "llm_score": self.llm_score,
            "composite_score": self.composite_score,
            "emoji": self.emoji,
        }

    @property
    def emoji(self) -> str:
        if self.composite_score >= 0.8:
            return "✅ HIGH"
        elif self.composite_score >= 0.5:
            return "⚠️ MEDIUM"
        return "❌ LOW"


class SourceReputation:
    """Layer 1: YAML-driven domain tiers."""
    
    def __init__(self, reputation_config: Dict[str, list]):
        self.tier_1 = set(reputation_config.get("tier_1", []))
        self.tier_2 = set(reputation_config.get("tier_2", []))
        self.tier_3 = set(reputation_config.get("tier_3", []))
        self.blocklist = set(reputation_config.get("blocklist", []))
    
    def score(self, url: str) -> float:
        domain = urlparse(url).netloc.lower()
        # Subdomain resolution (e.g. blog.reuters.com -> reuters.com)
        parts = domain.split('.')
        base_domain = domain if len(parts) <= 2 else f"{parts[-2]}.{parts[-1]}"
        
        for d in [domain, base_domain]:
            if d in self.blocklist:
                return 0.0
            if d in self.tier_1:
                return 1.0
            if d in self.tier_2:
                return 0.8
            if d in self.tier_3:
                return 0.5
        
        return 0.3 # Unknown


class ContentHeuristics:
    """Layer 2: Deterministic Python checks."""
    
    AI_HEDGE_WORDS = [
        "it is important to note", "as an ai", "it is worth noting", 
        "delve into", "testament to", "in conclusion", "vital to remember"
    ]
    CLICKBAIT_WORDS = ["you won't believe", "shocking", "mind-blowing", "secret"]

    def analyze(self, text: str, title: str = "") -> float:
        if not text:
            return 0.0
            
        score = 0.8 # Base human assumption
        text_lower = text.lower()
        title_lower = title.lower()
        
        # 1. AI text hedge phrases
        hedge_count = sum(1 for phrase in self.AI_HEDGE_WORDS if phrase in text_lower)
        score -= min(0.4, hedge_count * 0.1)
        
        # 2. Clickbait title penalty
        if any(word in title_lower for word in self.CLICKBAIT_WORDS):
            score -= 0.2
            
        # 3. Uniform sentence length (AI marker)
        sentences = [s.strip() for s in re.split(r'[.!?]+', text) if len(s.strip()) > 5]
        if len(sentences) > 4:
            lengths = [len(s.split()) for s in sentences]
            mean_len = sum(lengths) / len(lengths)
            variance = sum((l - mean_len) ** 2 for l in lengths) / len(lengths)
            if variance < 5.0: # Very uniform
                score -= 0.15
                
        # 4. Good sourcing (quotes, dates)
        if '"' in text or '“' in text:
            score += 0.05
        if re.search(r'\b(20[2-9][0-9]|19[8-9][0-9])\b', text):
            score += 0.05
            
        return max(0.0, min(1.0, float(score)))


class ContentFetcher:
    """Fetches article text."""
    @staticmethod
    async def fetch(url: str) -> str:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=10) as response:
                    if response.status == 200:
                        html = await response.text()
                        soup = BeautifulSoup(html, 'html.parser')
                        for script in soup(["script", "style"]):
                            script.extract()
                        return soup.get_text(separator=' ', strip=True)
            return ""
        except Exception:
            return ""


class LLMAuthenticityDetector:
    """Layer 3: Optional LLM check."""
    def __init__(self, scorer_instance):
        self.scorer = scorer_instance # Typically RelevanceScorer
        self.prompt = (
            "You are an AI content detector. Analyze the following text "
            "and output a JSON with a single key 'authenticity_score' from 0.0 to 1.0 "
            "where 1.0 is highly likely human/authentic and 0.0 is highly likely AI/fake.\n\nText: "
        )

    async def detect(self, text: str) -> float:
        if not text:
            return 0.0
        # Reusing scorer infrastructure but sending own prompt via user message
        try:
            return await self.scorer.score(
                content=text,
                title="",
                url="",
                relevance_prompt=self.prompt
            )
        except Exception:
            return 0.5


class AuthenticityEngine:
    """Orchestrates the 3 layers."""

    # Default composite weights (without LLM and with LLM)
    _DEFAULT_WEIGHTS_NO_LLM = {"source": 0.45, "heuristic": 0.55}
    _DEFAULT_WEIGHTS_LLM    = {"source": 0.30, "heuristic": 0.35, "llm": 0.35}

    def __init__(self, config: Dict[str, Any], scorer=None):
        rep_config = config.get("source_reputation", {})
        self.reputation = SourceReputation(rep_config)
        self.heuristics = ContentHeuristics()
        self.llm_detector = LLMAuthenticityDetector(scorer) if scorer else None

        # Allow caller to override weights via config["weights"]
        user_weights = config.get("weights", {})
        self._w_no_llm = {**self._DEFAULT_WEIGHTS_NO_LLM, **user_weights.get("no_llm", {})}
        self._w_llm    = {**self._DEFAULT_WEIGHTS_LLM,    **user_weights.get("with_llm", {})}

    async def evaluate(self, url: str, text: str, title: str = "") -> AuthenticityResult:
        s_score = self.reputation.score(url)
        h_score = self.heuristics.analyze(text, title)

        l_score = None
        if self.llm_detector:
            l_score = await self.llm_detector.detect(text)

        if l_score is not None:
            w = self._w_llm
            comp = s_score * w["source"] + h_score * w["heuristic"] + l_score * w["llm"]
        else:
            w = self._w_no_llm
            comp = s_score * w["source"] + h_score * w["heuristic"]

        return AuthenticityResult(
            source_score=round(s_score, 3),
            heuristic_score=round(h_score, 3),
            llm_score=round(l_score, 3) if l_score is not None else None,
            composite_score=round(comp, 3)
        )
