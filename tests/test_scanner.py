"""
Tests for scanner.py — Verity core orchestrator.

All external services (searcher, scorer, store, notifiers, audit) are mocked.
Tests verify the actual pipeline logic in Verity._scan_topic.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


def _make_verity(relevance_score=0.9, auth_score=0.85, gamut_enabled=False):
    """
    Build a Verity instance with all external dependencies mocked.
    Returns (verity, mocks) so tests can inspect call counts and set return values.
    """
    from authenticity import AuthenticityResult

    auth_result = AuthenticityResult(
        source_score=auth_score,
        heuristic_score=auth_score,
        llm_score=None,
        composite_score=auth_score,
    )

    config = {
        "topics": [
            {
                "id": "test_topic",
                "name": "Test Topic",
                "keywords": ["test keyword"],
                "relevance_prompt": "Score this.",
                "priority": "high",
            }
        ],
        "search": {
            "provider": "serper",
            "max_results_per_keyword": 5,
            "lookback_hours": 24,
        },
        "scoring": {
            "provider": "gemini",
            "model": "gemini-2.5-flash",
            "temperature": 0.1,
            "threshold": {"surface": 0.6, "auto_approve": 0.9},
        },
        "authenticity": {
            "min_score": 0.4,
            "auto_approve_min_score": 0.8,
            "use_llm_layer": False,
        },
        "notifications": [],
        "storage": {"backend": "local_json", "local_path": "/tmp/test_items.json"},
        "security": {
            "bind_address": "127.0.0.1",
            "block_domains": [],
            "allow_domains": [],
            "log_all_searches": False,
            "log_scoring_decisions": False,
            "audit_log_path": "/tmp/test_audit.jsonl",
        },
        "gamut": {"enabled": gamut_enabled, "api_base": "https://api.gamutagent.ai/v1", "api_key_env": "GAMUT_API_KEY"},
        "_secrets": None,
    }

    mock_searcher = MagicMock()
    mock_searcher.search = AsyncMock(return_value=[
        {"url": "https://reuters.com/article/1", "title": "Stripe Raises Series I", "snippet": "Stripe raises funding.", "source": "reuters.com"}
    ])

    mock_scorer = MagicMock()
    mock_scorer.score = AsyncMock(return_value=relevance_score)

    mock_store = MagicMock()
    mock_store.seen = MagicMock(return_value=False)
    mock_store.mark_seen = MagicMock()
    mock_store.save = MagicMock()

    mock_notifiers = MagicMock()
    mock_notifiers.notify = AsyncMock()

    mock_audit = MagicMock()
    mock_audit.log_search = MagicMock()
    mock_audit.log_score = MagicMock()
    mock_audit.log_authenticity = MagicMock()

    mock_auth_engine = MagicMock()
    mock_auth_engine.evaluate = AsyncMock(return_value=auth_result)

    with patch("scanner.load_config", return_value=config), \
         patch("scanner.WebSearcher", return_value=mock_searcher), \
         patch("scanner.RelevanceScorer", return_value=mock_scorer), \
         patch("scanner.ItemStore", return_value=mock_store), \
         patch("scanner.NotifierRegistry", return_value=mock_notifiers), \
         patch("scanner.AuditLogger", return_value=mock_audit), \
         patch("scanner.AuthenticityEngine", return_value=mock_auth_engine):

        from scanner import Verity
        verity = Verity.__new__(Verity)
        verity.config = config
        verity.searcher = mock_searcher
        verity.scorer = mock_scorer
        verity.store = mock_store
        verity.notifiers = mock_notifiers
        verity.audit = mock_audit
        verity.security = config["security"]
        verity.authenticity_cfg = config["authenticity"]
        verity.authenticity_engine = mock_auth_engine

    mocks = {
        "searcher": mock_searcher,
        "scorer": mock_scorer,
        "store": mock_store,
        "notifiers": mock_notifiers,
        "audit": mock_audit,
        "auth_engine": mock_auth_engine,
    }
    return verity, mocks


@pytest.mark.asyncio
async def test_integration_happy_path():
    """High relevance + high authenticity → item surfaced and notified."""
    verity, mocks = _make_verity(relevance_score=0.9, auth_score=0.85)
    topic = verity.config["topics"][0]
    stats = {"searched": 0, "scored": 0, "surfaced": 0, "auto_approved": 0}

    result = await verity._scan_topic(topic, stats)

    assert len(result) == 1
    assert stats["surfaced"] == 1
    mocks["store"].save.assert_called_once()
    mocks["notifiers"].notify.assert_called_once()
    mocks["audit"].log_authenticity.assert_called_once()


@pytest.mark.asyncio
async def test_low_relevance_skips_authenticity():
    """If relevance < surface threshold, authenticity is never evaluated."""
    verity, mocks = _make_verity(relevance_score=0.3)
    topic = verity.config["topics"][0]
    stats = {"searched": 0, "scored": 0, "surfaced": 0, "auto_approved": 0}

    result = await verity._scan_topic(topic, stats)

    assert len(result) == 0
    mocks["auth_engine"].evaluate.assert_not_called()
    mocks["store"].mark_seen.assert_called_once_with(
        mocks["store"].mark_seen.call_args[0][0], status="below_threshold"
    )


@pytest.mark.asyncio
async def test_low_authenticity_blocked():
    """Relevance passes but low authenticity → item blocked."""
    verity, mocks = _make_verity(relevance_score=0.8, auth_score=0.2)
    topic = verity.config["topics"][0]
    stats = {"searched": 0, "scored": 0, "surfaced": 0, "auto_approved": 0}

    result = await verity._scan_topic(topic, stats)

    assert len(result) == 0
    assert stats["surfaced"] == 0
    mocks["auth_engine"].evaluate.assert_called_once()
    mocks["store"].save.assert_not_called()
    mocks["notifiers"].notify.assert_not_called()
    # Blocked item is marked seen with correct status
    mocks["store"].mark_seen.assert_called_once_with(
        mocks["store"].mark_seen.call_args[0][0], status="low_authenticity"
    )


@pytest.mark.asyncio
async def test_auto_approval_requires_both_high_scores():
    """Auto-approve only fires when BOTH relevance AND authenticity are high."""
    # Both high → auto_approved
    verity, mocks = _make_verity(relevance_score=0.95, auth_score=0.85)
    topic = verity.config["topics"][0]
    stats = {"searched": 0, "scored": 0, "surfaced": 0, "auto_approved": 0}
    result = await verity._scan_topic(topic, stats)
    assert stats["auto_approved"] == 1
    assert result[0]["status"] == "auto_approved"


@pytest.mark.asyncio
async def test_auto_approval_blocked_by_low_authenticity():
    """High relevance but borderline authenticity → pending, not auto-approved."""
    verity, mocks = _make_verity(relevance_score=0.95, auth_score=0.5)
    topic = verity.config["topics"][0]
    stats = {"searched": 0, "scored": 0, "surfaced": 0, "auto_approved": 0}
    result = await verity._scan_topic(topic, stats)
    # Authenticity passes min_score (0.4) but fails auto_approve_min_score (0.8)
    assert stats["auto_approved"] == 0
    assert result[0]["status"] == "pending"


@pytest.mark.asyncio
async def test_gamut_enrichment_only_when_enabled():
    """Gamut enrichment is called only when config enables it."""
    verity, mocks = _make_verity(relevance_score=0.9, auth_score=0.85, gamut_enabled=False)
    topic = verity.config["topics"][0]
    stats = {"searched": 0, "scored": 0, "surfaced": 0, "auto_approved": 0}

    # Patch _enrich_with_gamut to track calls
    enrich_mock = AsyncMock(side_effect=lambda item: item)
    verity._enrich_with_gamut = enrich_mock

    await verity._scan_topic(topic, stats)
    enrich_mock.assert_not_called()


@pytest.mark.asyncio
async def test_item_includes_authenticity_data():
    """Surfaced items carry authenticity result for downstream use."""
    verity, mocks = _make_verity(relevance_score=0.9, auth_score=0.85)
    topic = verity.config["topics"][0]
    stats = {"searched": 0, "scored": 0, "surfaced": 0, "auto_approved": 0}

    result = await verity._scan_topic(topic, stats)

    assert len(result) == 1
    assert "authenticity" in result[0]
    assert "composite_score" in result[0]["authenticity"]
    assert result[0]["authenticity"]["composite_score"] == 0.85
