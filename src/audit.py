"""
Intel Sweep — Audit Logger

Append-only structured audit log. Every search query and scoring
decision is recorded for security review and debugging.
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger("intel-sweep.audit")


class AuditLogger:
    def __init__(self, security_config: dict):
        self.enabled_search = security_config.get("log_all_searches", True)
        self.enabled_scoring = security_config.get("log_scoring_decisions", True)
        self.log_path = Path(security_config.get("audit_log_path", "./logs/audit.jsonl"))
        self.log_path.parent.mkdir(parents=True, exist_ok=True)

    def log_search(self, query: str, result_count: int) -> None:
        if not self.enabled_search:
            return
        self._write({
            "event": "search",
            "query": query,
            "result_count": result_count,
        })

    def log_score(self, url: str, score: float) -> None:
        if not self.enabled_scoring:
            return
        self._write({
            "event": "score",
            "url": url,
            "score": score,
        })

    def log_authenticity(self, url: str, composite: float, source: float, heuristic: float, llm: float | None) -> None:
        if not self.enabled_scoring:
            return
        self._write({
            "event": "authenticity",
            "url": url,
            "composite_score": composite,
            "source_score": source,
            "heuristic_score": heuristic,
            "llm_score": llm,
        })

    def log_approval(self, item_id: str, action: str) -> None:
        self._write({
            "event": "approval",
            "item_id": item_id,
            "action": action,
        })

    def _write(self, entry: dict) -> None:
        entry["timestamp"] = datetime.now(timezone.utc).isoformat()
        try:
            with open(self.log_path, "a") as f:
                f.write(json.dumps(entry) + "\n")
        except Exception as e:
            logger.error(f"Audit log write failed: {e}")
