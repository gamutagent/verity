import pytest
from src.authenticity import SourceReputation, ContentHeuristics, AuthenticityResult, AuthenticityEngine

@pytest.fixture
def rep_config():
    return {
        "tier_1": ["reuters.com", "bloomberg.com"],
        "tier_2": ["techcrunch.com"],
        "tier_3": ["randomblog.net"],
        "blocklist": ["spam.com"]
    }

def test_source_reputation_score(rep_config):
    rep = SourceReputation(rep_config)
    assert rep.score("https://reuters.com/article/1") == 1.0
    assert rep.score("http://TECHCRUNCH.com/news") == 0.8
    assert rep.score("https://randomblog.net/post") == 0.5
    assert rep.score("http://unknown-domain.com") == 0.3
    assert rep.score("https://spam.com/offer") == 0.0

def test_subdomain_resolution(rep_config):
    rep = SourceReputation(rep_config)
    assert rep.score("https://blog.reuters.com/news") == 1.0
    assert rep.score("https://www.bloomberg.com/markets") == 1.0

def test_content_heuristics_analyze():
    h = ContentHeuristics()
    # Clean human text
    human_text = "The company announced its Series A funding today. The CEO stated they plan to expand. \"This is a big step,\" she said in 2026."
    assert h.analyze(human_text, "Startups") >= 0.85
    
    # AI generated text
    ai_text = "It is important to note that this is a testament to their growth. In conclusion, it is worth noting that they are expanding."
    assert h.analyze(ai_text, "Startups") < 0.6
    
    # Clickbait title
    assert h.analyze(human_text, "You won't believe this shocking secret") < 0.8

def test_authenticity_result_to_dict():
    res = AuthenticityResult(1.0, 0.8, None, 0.9)
    d = res.to_dict()
    assert d["source_score"] == 1.0
    assert d["composite_score"] == 0.9
    assert d["emoji"] == "✅ HIGH"

@pytest.mark.asyncio
async def test_composite_score_calculation(rep_config):
    engine = AuthenticityEngine({"source_reputation": rep_config}, None)
    res = await engine.evaluate("https://reuters.com", "Clean human text with a quote \". Year 2026.", "Good Title")
    # source(1.0)*0.45 + heuristic(~0.9)*0.55 = ~0.945
    assert res.composite_score > 0.9
