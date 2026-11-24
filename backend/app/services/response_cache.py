"""Small bounded SQLite cache for disposable upstream API responses."""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
import time
from pathlib import Path
from typing import Any

from app.database import get_db_path

logger = logging.getLogger("moviehub.response_cache")

DEFAULT_MAX_ENTRIES = 1000
DEFAULT_MAX_BYTES = 32 * 1024 * 1024
DEFAULT_MAX_ENTRY_BYTES = 512 * 1024


def build_cache_key(
    provider: str,
    endpoint: str,
    params: dict[str, Any] | None = None,
    language: str = "zh-CN",
    region: str = "SG",
) -> str:
    """Hash a canonical provider/endpoint/parameter/language/region tuple."""
    normalized = {
        str(key): value
        for key, value in sorted((params or {}).items(), key=lambda item: str(item[0]))
        if value is not None
    }
    canonical = json.dumps(
        {
            "provider": provider.strip().lower(),
            "endpoint": endpoint.strip(),
            "params": normalized,
            "language": language.strip(),
            "region": region.strip().upper(),
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


class SQLiteResponseCache:
    """SQLite-backed TTL/LRU cache with hard entry and byte ceilings."""

    def __init__(
        self,
        db_path: str | Path | None = None,
        max_entries: int = DEFAULT_MAX_ENTRIES,
        max_bytes: int = DEFAULT_MAX_BYTES,
        max_entry_bytes: int = DEFAULT_MAX_ENTRY_BYTES,
    ) -> None:
        self.db_path = Path(db_path) if db_path else None
        self.max_entries = max(1, int(max_entries))
        self.max_bytes = max(1024, int(max_bytes))
        self.max_entry_bytes = max(256, min(int(max_entry_bytes), self.max_bytes))

    def _connect(self) -> sqlite3.Connection:
        path = self.db_path or Path(get_db_path())
        if not path.is_file():
            raise FileNotFoundError(f"MovieHub database does not exist: {path}")
        connection = sqlite3.connect(str(path), timeout=3)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout=3000")
        return connection

    def get(self, cache_key: str) -> dict[str, Any] | None:
        """Return a live JSON object and update its LRU/hit metadata."""
        now = int(time.time())
        with self._connect() as connection:
            row = connection.execute(
                "SELECT response_json, expires_at FROM external_api_cache WHERE cache_key = ?",
                (cache_key,),
            ).fetchone()
            if row is None:
                return None
            if int(row["expires_at"]) <= now:
                connection.execute("DELETE FROM external_api_cache WHERE cache_key = ?", (cache_key,))
                return None
            try:
                payload = json.loads(row["response_json"])
            except (TypeError, json.JSONDecodeError):
                connection.execute("DELETE FROM external_api_cache WHERE cache_key = ?", (cache_key,))
                return None
            connection.execute(
                "UPDATE external_api_cache SET last_accessed_at = ?, hit_count = hit_count + 1 WHERE cache_key = ?",
                (now, cache_key),
            )
            return payload if isinstance(payload, dict) else None

    def set(
        self,
        cache_key: str,
        provider: str,
        endpoint: str,
        params: dict[str, Any] | None,
        payload: dict[str, Any],
        ttl_seconds: int,
    ) -> bool:
        """Store only successful JSON objects that fit the per-entry ceiling."""
        if not isinstance(payload, dict):
            return False
        response_json = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        payload_bytes = len(response_json.encode("utf-8"))
        if payload_bytes > self.max_entry_bytes:
            logger.info("Skipping oversized upstream cache entry (%s bytes)", payload_bytes)
            return False

        now = int(time.time())
        expires_at = now + max(1, int(ttl_seconds))
        params_json = json.dumps(params or {}, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                INSERT INTO external_api_cache (
                    cache_key, provider, endpoint, params_json, response_json,
                    fetched_at, expires_at, last_accessed_at, payload_bytes, hit_count
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
                ON CONFLICT(cache_key) DO UPDATE SET
                    provider=excluded.provider, endpoint=excluded.endpoint,
                    params_json=excluded.params_json, response_json=excluded.response_json,
                    fetched_at=excluded.fetched_at, expires_at=excluded.expires_at,
                    last_accessed_at=excluded.last_accessed_at,
                    payload_bytes=excluded.payload_bytes, hit_count=0
                """,
                (cache_key, provider, endpoint, params_json, response_json, now, expires_at, now, payload_bytes),
            )
            # The table is hard-capped, so a complete expired sweep is bounded.
            connection.execute("DELETE FROM external_api_cache WHERE expires_at <= ?", (now,))
            rows = connection.execute(
                """
                SELECT cache_key, payload_bytes FROM external_api_cache
                ORDER BY CASE WHEN expires_at <= ? THEN 0 ELSE 1 END,
                         last_accessed_at ASC, fetched_at ASC
                """,
                (now,),
            ).fetchall()
            total_bytes = sum(int(row["payload_bytes"]) for row in rows)
            total_entries = len(rows)
            evict: list[str] = []
            for row in rows:
                if total_entries <= self.max_entries and total_bytes <= self.max_bytes:
                    break
                evict.append(str(row["cache_key"]))
                total_entries -= 1
                total_bytes -= int(row["payload_bytes"])
            if evict:
                placeholders = ",".join("?" for _ in evict)
                connection.execute(
                    f"DELETE FROM external_api_cache WHERE cache_key IN ({placeholders})",
                    evict,
                )
            connection.commit()
            return True
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def clear_expired(self, batch_size: int = 100) -> int:
        """Delete at most batch_size expired rows per invocation."""
        limit = max(1, min(int(batch_size), 500))
        now = int(time.time())
        with self._connect() as connection:
            cursor = connection.execute(
                """
                DELETE FROM external_api_cache
                WHERE cache_key IN (
                    SELECT cache_key FROM external_api_cache
                    WHERE expires_at <= ? ORDER BY expires_at ASC LIMIT ?
                )
                """,
                (now, limit),
            )
            return max(0, cursor.rowcount)

    def stats(self) -> dict[str, int]:
        """Return bounded cache accounting for diagnostics."""
        with self._connect() as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS entries, COALESCE(SUM(payload_bytes), 0) AS bytes, COALESCE(SUM(hit_count), 0) AS hits FROM external_api_cache"
            ).fetchone()
            return {
                "entries": int(row["entries"]),
                "bytes": int(row["bytes"]),
                "hits": int(row["hits"]),
                "max_entries": self.max_entries,
                "max_bytes": self.max_bytes,
            }


response_cache = SQLiteResponseCache()

__all__ = ["SQLiteResponseCache", "build_cache_key", "response_cache"]