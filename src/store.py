"""
Intel Sweep — Item Storage

Handles deduplication, approval state, and approved-item export.
Backends: Firestore (production), local JSON (dev), SQLite (middle ground).
"""

import json
import logging
import os
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger("intel-sweep.store")


class ItemStore:
    """Factory-backed store with common interface."""

    def __init__(self, config: dict):
        backend = config.get("backend", "local_json")
        self._store = _build_store(backend, config)
        self._approved_output = config.get("approved_output", {})

    def seen(self, url_hash: str) -> bool:
        return self._store.exists(url_hash)

    def mark_seen(self, url_hash: str, status: str = "seen") -> None:
        self._store.upsert(url_hash, {"status": status, "seen_at": _now()})

    def save(self, item: dict) -> None:
        self._store.upsert(item["id"], item)
        if item.get("status") == "auto_approved":
            self._write_approved(item)

    def approve(self, item_id: str) -> None:
        item = self._store.get(item_id)
        if item:
            item["status"] = "approved"
            item["approved_at"] = _now()
            self._store.upsert(item_id, item)
            self._write_approved(item)

    def discard(self, item_id: str) -> None:
        self._store.upsert(item_id, {"status": "discarded", "discarded_at": _now()})

    def get_pending(self) -> list[dict]:
        return self._store.query(status="pending")

    def _write_approved(self, item: dict) -> None:
        """Append approved item to output file for downstream consumption."""
        fmt = self._approved_output.get("format", "jsonl")
        path = self._approved_output.get("path", "./data/approved.jsonl")
        Path(path).parent.mkdir(parents=True, exist_ok=True)

        if fmt in ("jsonl", "both"):
            with open(path, "a") as f:
                f.write(json.dumps(item, default=str) + "\n")

        if fmt in ("markdown", "both"):
            md_path = path.replace(".jsonl", ".md")
            with open(md_path, "a") as f:
                f.write(
                    f"## [{item['title']}]({item['url']})\n"
                    f"- **Score:** {item['score']:.2f} | **Topic:** {item['topic_name']}\n"
                    f"- **Discovered:** {item['discovered_at']}\n"
                    f"- {item.get('snippet', '')}\n\n"
                )


# --- Backend implementations ---

class BaseStoreBackend(ABC):
    @abstractmethod
    def exists(self, key: str) -> bool: ...
    @abstractmethod
    def get(self, key: str) -> dict | None: ...
    @abstractmethod
    def upsert(self, key: str, data: dict) -> None: ...
    @abstractmethod
    def query(self, **filters) -> list[dict]: ...


class LocalJSONStore(BaseStoreBackend):
    """Simple JSON file store. Good for development and single-user."""

    def __init__(self, config: dict):
        self.path = Path(config.get("local_path", "./data/items.json"))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._data: dict[str, dict] = {}
        if self.path.exists():
            with open(self.path) as f:
                self._data = json.load(f)

    def exists(self, key: str) -> bool:
        return key in self._data

    def get(self, key: str) -> dict | None:
        return self._data.get(key)

    def upsert(self, key: str, data: dict) -> None:
        if key in self._data:
            self._data[key].update(data)
        else:
            self._data[key] = data
        self._flush()

    def query(self, **filters) -> list[dict]:
        results = []
        for item in self._data.values():
            if all(item.get(k) == v for k, v in filters.items()):
                results.append(item)
        return results

    def _flush(self) -> None:
        with open(self.path, "w") as f:
            json.dump(self._data, f, indent=2, default=str)


class FirestoreStore(BaseStoreBackend):
    """Google Cloud Firestore backend. Production-grade."""

    def __init__(self, config: dict):
        from google.cloud import firestore

        self.collection_name = config.get("collection", "intel_sweep_items")
        self.db = firestore.Client()
        self.collection = self.db.collection(self.collection_name)

    def exists(self, key: str) -> bool:
        return self.collection.document(key).get().exists

    def get(self, key: str) -> dict | None:
        doc = self.collection.document(key).get()
        return doc.to_dict() if doc.exists else None

    def upsert(self, key: str, data: dict) -> None:
        self.collection.document(key).set(data, merge=True)

    def query(self, **filters) -> list[dict]:
        query = self.collection
        for field, value in filters.items():
            query = query.where(field, "==", value)
        return [doc.to_dict() for doc in query.stream()]


class SQLiteStore(BaseStoreBackend):
    """SQLite backend. Good middle ground — file-based, queryable."""

    def __init__(self, config: dict):
        import sqlite3

        db_path = config.get("sqlite_path", "./data/intel_sweep.db")
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute(
            """CREATE TABLE IF NOT EXISTS items (
                key TEXT PRIMARY KEY,
                data TEXT NOT NULL,
                status TEXT DEFAULT 'pending',
                updated_at TEXT
            )"""
        )
        self.conn.commit()

    def exists(self, key: str) -> bool:
        row = self.conn.execute("SELECT 1 FROM items WHERE key = ?", (key,)).fetchone()
        return row is not None

    def get(self, key: str) -> dict | None:
        row = self.conn.execute("SELECT data FROM items WHERE key = ?", (key,)).fetchone()
        return json.loads(row["data"]) if row else None

    def upsert(self, key: str, data: dict) -> None:
        self.conn.execute(
            """INSERT INTO items (key, data, status, updated_at)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(key) DO UPDATE SET data = ?, status = ?, updated_at = ?""",
            (key, json.dumps(data, default=str), data.get("status", "pending"), _now(),
             json.dumps(data, default=str), data.get("status", "pending"), _now()),
        )
        self.conn.commit()

    def query(self, **filters) -> list[dict]:
        rows = self.conn.execute("SELECT data FROM items WHERE status = ?",
                                  (filters.get("status", "pending"),)).fetchall()
        return [json.loads(row["data"]) for row in rows]


def _build_store(backend: str, config: dict) -> BaseStoreBackend:
    stores = {
        "local_json": LocalJSONStore,
        "firestore": FirestoreStore,
        "sqlite": SQLiteStore,
    }
    if backend not in stores:
        raise ValueError(f"Unknown storage backend: {backend}. Use: {list(stores)}")
    return stores[backend](config)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
