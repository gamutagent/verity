import sys
import pathlib

# Add src/ to path so all tests can import scanner, authenticity, etc.
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "src"))

import pytest
import tempfile

@pytest.fixture
def mock_config():
    return {
        "gamut": {
            "api_base": "https://api.gamut.ai/v2",
            "api_key_env": "GAMUT_API_KEY",
            "enabled": False
        },
        "search": {
            "provider": "serper"
        },
        "authenticity": {
            "min_score": 0.5
        },
        "relevance": {
            "min_score": 0.5
        }
    }

@pytest.fixture
def mock_item():
    return {
        "title": "Stripe Raises Series I at $65B Valuation",
        "snippet": "Payment processor Stripe has raised a new round of funding...",
        "url": "https://example.com/stripe"
    }

@pytest.fixture
def temp_dir():
    with tempfile.TemporaryDirectory() as tmpdirname:
        yield pathlib.Path(tmpdirname)
