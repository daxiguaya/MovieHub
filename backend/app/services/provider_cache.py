"""Bounded persistent cache for external metadata-provider responses.

This cache is deliberately separate from the user/chart database schema. It can
be discarded and rebuilt without affecting favorites or chart snapshots.
"""
from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

from app.config import settings

logger = logging.getLogger("moviehub.provider_cache")

MAX_CACHE_ROWS = 1500
MAX_CACHE_BYTES = 32 * 1024 * 1024
MAX_ENTRY_BYTES = 1024 * 1024
STALE_GRACE_SECONDS = 24 * 60 * 60


class ProviderResponseCache:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or (Path(settings.data_dir) / "cache" / "discovery.sqlite3")
        self._lock = threading.RLock()
        self._initialized = False

    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=5)
        connection.execute("PRAGMA busy_timeout=5000")
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=NORMAL")
        return connection

    def _init(self) -> None:
        if self._initialized:
            return
        with self._lock:
            if self._initialized:
                return
            with self._connect() as connection:
                connection.execute("""
                    CREATE TABLE IF NOT EXISTS provider_response_cache (
                        cache_key TEXT PRIMARY KEY,
                        provider TEXT NOT NULL,
                        endpoint TEXT NOT NULL,
                        response_json TEXT NOT NULL,
                        response_bytes INTEGER NOT NULL,
                        fetched_at INTEGER NOT NULL,
                        expires_at INTEGER NOT NULL,
                        stale_until INTEGER NOT NULL,
                        accessed_at INTEGER NOT NULL
                    )
                """)
                connection.execute("""
                    CREATE INDEX IF NOT EXISTS ix_provider_cache_expiry
                    ON provider_response_cache(expires_at)
                """)
            self._initialized = True

    @staticmethod
    def make_key(provider: str, endpoint: str, params: dict[str, Any]) -> str:
        normalized = json.dumps(params, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        raw = f"{provider}\n{endpoint}\n{normalized}".encode("utf-8")
        return hashlib.sha256(raw).hexdigest()

    def get(self, key: str, allow_stale: bool = False) -> tuple[dict[str, Any], bool] | None:
        self._init()
        now = int(time.time())
        with self._lock, self._connect() as connection:
            row = connection.execute(
                """SELECT response_json, expires_at, stale_until
                   FROM provider_response_cache WHERE cache_key=?""",
                (key,),
            ).fetchone()
            if row is None or (row[1] <= now and (not allow_stale or row[2] <= now)):
                return None
            connection.execute(
                "UPDATE provider_response_cache SET accessed_at=? WHERE cache_key=?",
                (now, key),
            )
            try:
                payload = json.loads(row[0])
            except (TypeError, json.JSONDecodeError):
                connection.execute("DELETE FROM provider_response_cache WHERE cache_key=?", (key,))
                return None
            if not isinstance(payload, dict):
                return None
            return payload, row[1] <= now

    def set(
        self,
        key: str,
        provider: str,
        endpoint: str,
        payload: dict[str, Any],
        ttl_seconds: int,
    ) -> bool:
        self._init()
        serialized = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        size = len(serialized.encode("utf-8"))
        if size > MAX_ENTRY_BYTES:
            logger.info("Skipping oversized provider cache entry (%s bytes)", size)
            return False
        now = int(time.time())
        ttl = max(1, int(ttl_seconds))
        with self._lock, self._connect() as connection:
            connection.execute(
                """INSERT INTO provider_response_cache
                   (cache_key, provider, endpoint, response_json, response_bytes,
                    fetched_at, expires_at, stale_until, accessed_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(cache_key) DO UPDATE SET
                     provider=excluded.provider, endpoint=excluded.endpoint,
                     response_json=excluded.response_json,
                     response_bytes=excluded.response_bytes,
                     fetched_at=excluded.fetched_at, expires_at=excluded.expires_at,
                     stale_until=excluded.stale_until, accessed_at=excluded.accessed_at""",
                (key, provider, endpoint, serialized, size, now, now + ttl,
                 now + ttl + STALE_GRACE_SECONDS, now),
            )
            self._evict(connection)
        return True

    @staticmethod
    def _evict(connection: sqlite3.Connection) -> None:
        now = int(time.time())
        connection.execute("DELETE FROM provider_response_cache WHERE stale_until <= ?", (now,))
        row = connection.execute(
            "SELECT COUNT(*), COALESCE(SUM(response_bytes), 0) FROM provider_response_cache"
        ).fetchone()
        count, total_bytes = int(row[0]), int(row[1])
        while count > MAX_CACHE_ROWS or total_bytes > MAX_CACHE_BYTES:
            oldest = connection.execute(
                """SELECT cache_key, response_bytes FROM provider_response_cache
                   ORDER BY accessed_at ASC, fetched_at ASC LIMIT 1"""
            ).fetchone()
            if oldest is None:
                break
            connection.execute("DELETE FROM provider_response_cache WHERE cache_key=?", (oldest[0],))
            count -= 1
            total_bytes -= int(oldest[1])

    def stats(self) -> dict[str, int]:
        self._init()
        with self._lock, self._connect() as connection:
            row = connection.execute(
                """SELECT COUNT(*), COALESCE(SUM(response_bytes), 0),
                          COALESCE(SUM(CASE WHEN expires_at > ? THEN 1 ELSE 0 END), 0)
                   FROM provider_response_cache""",
                (int(time.time()),),
            ).fetchone()
        return {"entries": int(row[0]), "bytes": int(row[1]), "fresh_entries": int(row[2])}

    def clear_expired(self) -> int:
        self._init()
        with self._lock, self._connect() as connection:
            cursor = connection.execute(
                "DELETE FROM provider_response_cache WHERE stale_until <= ?",
                (int(time.time()),),
            )
            return int(cursor.rowcount)


provider_response_cache = ProviderResponseCache()
