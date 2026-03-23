"""
Intel Sweep — Config Loader

Loads YAML config with validation. API keys are NEVER in config files —
they are resolved via the secrets resolver (env vars, .env, GCP Secret
Manager, AWS Secrets Manager, or Azure Key Vault).
"""

import logging
import sys
from pathlib import Path

import yaml

from secrets_resolver import SecretsResolver

logger = logging.getLogger("intel-sweep.config")

REQUIRED_SECRETS = {
    "search": {"google": ["SEARCH_API_KEY"], "serper": ["SEARCH_API_KEY"],
               "brave": ["SEARCH_API_KEY"], "tavily": ["SEARCH_API_KEY"]},
    "scoring": {"gemini": ["SCORING_API_KEY"], "openai": ["SCORING_API_KEY"],
                "anthropic": ["SCORING_API_KEY"], "ollama": []},
}


def load_config(path: str = "config.yaml") -> dict:
    """Load and validate configuration."""
    config_path = Path(path)
    if not config_path.exists():
        logger.error(f"Config file not found: {path}")
        logger.error("Copy config.example.yaml to config.yaml and customize.")
        sys.exit(1)

    with open(config_path) as f:
        config = yaml.safe_load(f)

    # Initialize secrets resolver based on configured backend
    secrets = SecretsResolver(config)
    config["_secrets"] = secrets

    _validate_topics(config.get("topics", []))
    _validate_secrets(config, secrets)
    _validate_security(config.get("security", {}))

    return config


def _validate_topics(topics: list[dict]) -> None:
    for i, topic in enumerate(topics):
        required = ["id", "name", "keywords", "relevance_prompt"]
        for field in required:
            if field not in topic:
                raise ValueError(f"Topic {i} missing required field: {field}")
        if not topic["keywords"]:
            raise ValueError(f"Topic '{topic['id']}' has empty keywords list")


def _validate_secrets(config: dict, secrets: SecretsResolver) -> None:
    """Check that required secrets are resolvable. Fail fast, not at runtime."""
    missing = []

    # Search provider
    search_provider = config.get("search", {}).get("provider", "google")
    for var in REQUIRED_SECRETS["search"].get(search_provider, []):
        if not secrets.resolve_optional(var):
            missing.append(f"{var} (required for search provider: {search_provider})")

    # Scoring provider
    scoring_provider = config.get("scoring", {}).get("provider", "gemini")
    for var in REQUIRED_SECRETS["scoring"].get(scoring_provider, []):
        if not secrets.resolve_optional(var):
            missing.append(f"{var} (required for scoring provider: {scoring_provider})")

    # Notification channels
    for notif in config.get("notifications", []):
        for key in ["webhook_env", "bot_token_env", "chat_id_env", "url_env"]:
            env_var = notif.get(key)
            if env_var and not secrets.resolve_optional(env_var):
                missing.append(f"{env_var} (required for {notif['channel']} notifications)")

    # Gamut integration
    if config.get("gamut", {}).get("enabled"):
        env_var = config["gamut"].get("api_key_env", "GAMUT_API_KEY")
        if not secrets.resolve_optional(env_var):
            missing.append(f"{env_var} (required for Gamut integration)")

    if missing:
        backend = config.get("secrets", {}).get("backend", "env")
        logger.error(f"Missing required secrets (backend: {backend}):")
        for var in missing:
            logger.error(f"  - {var}")
        sys.exit(1)


def _validate_security(security: dict) -> None:
    """Warn on insecure defaults."""
    bind = security.get("bind_address", "127.0.0.1")
    if bind == "0.0.0.0":
        logger.warning(
            "SECURITY WARNING: bind_address is 0.0.0.0 — "
            "your instance will be exposed to all network interfaces. "
            "Set to 127.0.0.1 unless you know what you're doing."
        )
