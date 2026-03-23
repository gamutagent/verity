"""
Verity — Main Scanner Entry Point

Runs as a Cloud Function (HTTP trigger) or standalone CLI.
Orchestrates: search → score → authenticity → deduplicate → notify → store
"""

import asyncio
import hashlib
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

from config_loader import load_config
from scorer import RelevanceScorer
from searcher import WebSearcher
from notifier import NotifierRegistry
from store import ItemStore
from audit import AuditLogger
from authenticity import AuthenticityEngine

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("verity")


class Verity:
    """Core scanner orchestrator."""

    def __init__(self, config_path: str = "config.yaml"):
        self.config = load_config(config_path)
        self.searcher = WebSearcher(self.config["search"])
        self.scorer = RelevanceScorer(self.config["scoring"])
        self.store = ItemStore(self.config["storage"])
        self.notifiers = NotifierRegistry(self.config["notifications"])
        self.audit = AuditLogger(self.config["security"])
        self.security = self.config["security"]
        self.authenticity_cfg = self.config.get("authenticity", {})

        # Load source reputation DB (from config/source_reputation.yaml by default)
        rep_config = self._load_source_reputation()
        use_llm = self.authenticity_cfg.get("use_llm_layer", False)
        scorer_for_llm = self.scorer if use_llm else None
        self.authenticity_engine = AuthenticityEngine(
            {
                "source_reputation": rep_config,
                "weights": self.authenticity_cfg.get("weights", {}),
            },
            scorer=scorer_for_llm,
        )

    def _load_source_reputation(self) -> dict:
        """Load source_reputation.yaml from configured path or default location."""
        rep_path = self.authenticity_cfg.get(
            "source_reputation_path",
            str(Path(__file__).parent.parent / "config" / "source_reputation.yaml"),
        )
        try:
            with open(rep_path) as f:
                return yaml.safe_load(f) or {}
        except FileNotFoundError:
            logger.warning(f"source_reputation.yaml not found at {rep_path} — all domains score 0.3")
            return {}


    async def run(self, topic_ids: list[str] | None = None) -> dict:
        """
        Execute a scan cycle for specified topics (or all if None).

        Returns summary stats: {searched, scored, surfaced, auto_approved}
        """
        topics = self.config["topics"]
        if topic_ids:
            topics = [t for t in topics if t["id"] in topic_ids]

        stats = {"searched": 0, "scored": 0, "surfaced": 0, "auto_approved": 0}

        for topic in topics:
            logger.info(f"Scanning topic: {topic['name']}")
            results = await self._scan_topic(topic, stats)
            logger.info(
                f"Topic '{topic['name']}': "
                f"{len(results)} items surfaced"
            )

        return stats

    async def _scan_topic(self, topic: dict, stats: dict) -> list[dict]:
        """Search, score, deduplicate, notify, and store for a single topic."""
        surfaced = []

        for keyword in topic["keywords"]:
            # --- Search ---
            self._check_rate_limit("search")
            raw_results = await self.searcher.search(
                keyword,
                max_results=self.config["search"]["max_results_per_keyword"],
                lookback_hours=self.config["search"]["lookback_hours"],
            )
            stats["searched"] += len(raw_results)
            self.audit.log_search(keyword, len(raw_results))

            for result in raw_results:
                # --- Deduplicate ---
                url_hash = _url_hash(result["url"])
                if self.store.seen(url_hash):
                    logger.debug(f"Skipping already-seen URL: {result['url']}")
                    continue

                # --- Domain filtering ---
                if not self._domain_allowed(result["url"]):
                    logger.debug(f"Blocked domain: {result['url']}")
                    continue

                # --- Score ---
                self._check_rate_limit("scoring")
                score = await self.scorer.score(
                    content=result.get("snippet", ""),
                    title=result.get("title", ""),
                    url=result["url"],
                    relevance_prompt=topic["relevance_prompt"],
                )
                stats["scored"] += 1
                self.audit.log_score(result["url"], score)

                # --- Relevance threshold check ---
                threshold = self.config["scoring"]["threshold"]
                if score < threshold["surface"]:
                    self.store.mark_seen(url_hash, status="below_threshold")
                    continue

                # --- Authenticity check (all three layers) ---
                auth_result = await self.authenticity_engine.evaluate(
                    url=result["url"],
                    text=result.get("snippet", ""),
                    title=result.get("title", ""),
                )
                self.audit.log_authenticity(
                    url=result["url"],
                    composite=auth_result.composite_score,
                    source=auth_result.source_score,
                    heuristic=auth_result.heuristic_score,
                    llm=auth_result.llm_score,
                )

                auth_min = self.authenticity_cfg.get("min_score", 0.4)
                if auth_result.composite_score < auth_min:
                    logger.debug(
                        f"Authenticity below threshold ({auth_result.composite_score:.2f} < {auth_min}): {result['url']}"
                    )
                    self.store.mark_seen(url_hash, status="low_authenticity")
                    continue

                # --- Build item ---
                item = {
                    "id": url_hash,
                    "url": result["url"],
                    "title": result.get("title", ""),
                    "snippet": result.get("snippet", ""),
                    "source": result.get("source", ""),
                    "score": score,
                    "authenticity": auth_result.to_dict(),
                    "topic_id": topic["id"],
                    "topic_name": topic["name"],
                    "keyword": keyword,
                    "discovered_at": datetime.now(timezone.utc).isoformat(),
                    "status": "pending",
                }

                # --- Auto-approve requires BOTH high relevance AND high authenticity ---
                auth_auto = self.authenticity_cfg.get("auto_approve_min_score", 0.8)
                if score >= threshold["auto_approve"] and auth_result.composite_score >= auth_auto:
                    item["status"] = "auto_approved"
                    stats["auto_approved"] += 1

                # --- Gamut verification (optional) ---
                if self.config.get("gamut", {}).get("enabled"):
                    item = await self._enrich_with_gamut(item)

                # --- Store and notify ---
                self.store.save(item)
                await self.notifiers.notify(item, topic)
                surfaced.append(item)
                stats["surfaced"] += 1

        return surfaced

    async def _enrich_with_gamut(self, item: dict) -> dict:
        """
        Extract entity candidates from item title/snippet and verify each
        via the Gamut API. Attaches results under item["gamut_verification"].

        Only called after relevance + authenticity thresholds are met.
        On any API failure, logs warning and returns item unchanged.
        """
        import re
        import aiohttp

        gamut_cfg = self.config.get("gamut", {})
        api_base = gamut_cfg.get("api_base", "").rstrip("/")
        secrets = self.config.get("_secrets")
        api_key_env = gamut_cfg.get("api_key_env", "GAMUT_API_KEY")

        api_key = None
        if secrets:
            try:
                api_key = secrets.resolve(api_key_env)
            except Exception:
                pass
        if not api_key:
            api_key = os.environ.get(api_key_env)

        if not api_base or not api_key:
            logger.warning("Gamut enrichment: api_base or api_key missing — skipping")
            return item

        # Extract capitalised multi-word entity candidates from title + snippet
        text = f"{item.get('title', '')} {item.get('snippet', '')}"
        candidates = list(dict.fromkeys(
            re.findall(r"\b(?:[A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)\b", text)
        ))
        if not candidates:
            return item

        verifications = []
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

        async with aiohttp.ClientSession() as session:
            for entity_name in candidates[:5]:  # cap at 5 entities per item
                try:
                    async with session.post(
                        f"{api_base}/verify",
                        json={"entity_name": entity_name},
                        headers=headers,
                        timeout=aiohttp.ClientTimeout(total=5),
                    ) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            verifications.append({
                                "entity_name": entity_name,
                                "confidence_score": data.get("confidence_score"),
                                "registry_status": data.get("registry_status"),
                                "registry_source": data.get("registry_source"),
                                "verified_at": data.get("verified_at"),
                            })
                        else:
                            logger.warning(
                                f"Gamut API returned {resp.status} for '{entity_name}'"
                            )
                except Exception as e:
                    logger.warning(f"Gamut enrichment failed for '{entity_name}': {e}")

        if verifications:
            item["gamut_verification"] = verifications
            logger.info(
                f"Gamut enrichment: {len(verifications)} entities verified for '{item['title']}'"
            )

        return item

    def _domain_allowed(self, url: str) -> bool:
        """Check URL against allow/block lists."""
        from urllib.parse import urlparse

        domain = urlparse(url).netloc.lower()
        blocked = self.security.get("block_domains", [])
        allowed = self.security.get("allow_domains", [])

        if domain in blocked:
            return False
        if allowed and domain not in allowed:
            return False
        return True

    def _check_rate_limit(self, operation: str) -> None:
        """Enforce per-hour rate limits. Raises if exceeded."""
        # Implementation: track counts in memory or store
        # For now, trust the caller to respect scheduling
        pass


# Backward-compatible alias
IntelSweep = Verity


def _url_hash(url: str) -> str:
    """Deterministic hash for deduplication."""
    return hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]


# --- Cloud Function entry point ---
def handle_request(request):
    """HTTP Cloud Function handler."""
    topic_ids = None
    if request.method == "POST":
        body = request.get_json(silent=True) or {}
        topic_ids = body.get("topics")

    stats = asyncio.run(IntelSweep().run(topic_ids))
    return json.dumps(stats), 200, {"Content-Type": "application/json"}


# --- CLI entry point ---
def main():
    """Run from command line: python scanner.py [topic_id ...]"""
    config_path = os.getenv("INTEL_SWEEP_CONFIG", "config.yaml")
    topic_ids = sys.argv[1:] or None

    sweep = IntelSweep(config_path)
    stats = asyncio.run(sweep.run(topic_ids))

    print(json.dumps(stats, indent=2))


if __name__ == "__main__":
    main()
