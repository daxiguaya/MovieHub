"""Bounded persistent cache for external metadata-provider responses.

This cache is deliberately separate from the user/chart database schema. It can
be discarded and rebuilt without affecting favorites or chart snapshots.
"""
from __future__ import annotations

import hashlib
import unicodedata
from contextlib import contextmanager
import json
import logging
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

from app.config import settings
from app.services.imdb_ids import is_valid_imdb_id

logger = logging.getLogger("moviehub.provider_cache")

MAX_CACHE_ROWS = 1500
MAX_CACHE_BYTES = 32 * 1024 * 1024
MAX_CACHE_DB_BYTES = 48 * 1024 * 1024
MAX_ENTRY_BYTES = 1024 * 1024
STALE_GRACE_SECONDS = 24 * 60 * 60


class ProviderResponseCache:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or (Path(settings.data_dir) / "cache" / "discovery.sqlite3")
        self._lock = threading.RLock()
        self._initialized = False
        self._hits = 0
        self._misses = 0
        self._stale_hits = 0
        self._writes = 0

    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=5)
        connection.execute("PRAGMA busy_timeout=5000")
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=NORMAL")
        return connection

    @contextmanager
    def _connection(self):
        connection = self._connect()
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def _init(self) -> None:
        if self._initialized:
            return
        with self._lock:
            if self._initialized:
                return
            with self._connection() as connection:
                if connection.execute("PRAGMA auto_vacuum").fetchone()[0] == 0:
                    connection.execute("PRAGMA auto_vacuum=INCREMENTAL")
                    connection.execute("VACUUM")
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
                connection.execute("""
                    CREATE TABLE IF NOT EXISTS external_favorites (
                        provider TEXT NOT NULL,
                        media_type TEXT NOT NULL,
                        provider_id INTEGER NOT NULL,
                        snapshot_json TEXT NOT NULL,
                        note TEXT NOT NULL DEFAULT '',
                        created_at INTEGER NOT NULL,
                        updated_at INTEGER NOT NULL,
                        PRIMARY KEY (provider, media_type, provider_id)
                    )
                """)
            self._initialized = True

    @staticmethod
    def make_key(provider: str, endpoint: str, params: dict[str, Any]) -> str:
        normalized = json.dumps(params, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        raw = f"{provider}\n{endpoint}\n{normalized}".encode("utf-8")
        return hashlib.sha256(raw).hexdigest()

    def get(self, key: str, allow_stale: bool = False, max_age_seconds: int | None = None) -> tuple[dict[str, Any], bool] | None:
        self._init()
        now = int(time.time())
        with self._lock, self._connection() as connection:
            row = connection.execute(
                """SELECT response_json, expires_at, stale_until, fetched_at
                   FROM provider_response_cache WHERE cache_key=?""",
                (key,),
            ).fetchone()
            if (
                row is None
                or (max_age_seconds is not None and now - row[3] > max(1, int(max_age_seconds)))
                or (row[1] <= now and (not allow_stale or row[2] <= now))
            ):
                self._misses += 1
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
                self._misses += 1
                return None
            if row[1] <= now:
                self._stale_hits += 1
            else:
                self._hits += 1
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
        with self._lock, self._connection() as connection:
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
            self._writes += 1
        self._compact_if_needed()
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
        with self._lock, self._connection() as connection:
            row = connection.execute(
                """SELECT COUNT(*), COALESCE(SUM(response_bytes), 0),
                          COALESCE(SUM(CASE WHEN expires_at > ? THEN 1 ELSE 0 END), 0)
                   FROM provider_response_cache""",
                (int(time.time()),),
            ).fetchone()
        database_bytes = self.path.stat().st_size if self.path.exists() else 0
        wal_path = Path(str(self.path) + "-wal")
        wal_bytes = wal_path.stat().st_size if wal_path.exists() else 0
        return {"entries": int(row[0]), "bytes": int(row[1]), "fresh_entries": int(row[2]),
                "database_bytes": database_bytes, "wal_bytes": wal_bytes,
                "hits": self._hits, "misses": self._misses,
                "stale_hits": self._stale_hits, "writes": self._writes}

    def save_favorite(self, media_type: str, provider_id: int, snapshot: dict[str, Any], note: str = "") -> dict[str, Any]:
        self._init()
        now = int(time.time())
        serialized = json.dumps(snapshot, ensure_ascii=False, separators=(",", ":"))
        if len(serialized.encode("utf-8")) > 16 * 1024:
            raise ValueError("Favorite snapshot is too large")
        with self._lock, self._connection() as connection:
            connection.execute(
                """INSERT INTO external_favorites
                   (provider, media_type, provider_id, snapshot_json, note, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(provider, media_type, provider_id) DO UPDATE SET
                     snapshot_json=excluded.snapshot_json, note=excluded.note, updated_at=excluded.updated_at""",
                ("tmdb", media_type, int(provider_id), serialized, note[:1000], now, now),
            )
            row = connection.execute(
                """SELECT snapshot_json, note, created_at, updated_at FROM external_favorites
                   WHERE provider=? AND media_type=? AND provider_id=?""",
                ("tmdb", media_type, int(provider_id)),
            ).fetchone()
        return {"provider": "tmdb", "media_type": media_type, "provider_id": int(provider_id),
                "snapshot": json.loads(row[0]), "note": row[1], "created_at": row[2], "updated_at": row[3]}

    def has_favorite(self, media_type: str, provider_id: int) -> bool:
        self._init()
        with self._lock, self._connection() as connection:
            row = connection.execute(
                """SELECT 1 FROM external_favorites
                   WHERE provider=? AND media_type=? AND provider_id=? LIMIT 1""",
                ("tmdb", media_type, int(provider_id)),
            ).fetchone()
        return row is not None

    def list_favorites(self) -> list[dict[str, Any]]:
        self._init()
        with self._lock, self._connection() as connection:
            rows = connection.execute(
                """SELECT media_type, provider_id, snapshot_json, note, created_at, updated_at
                   FROM external_favorites WHERE provider=? ORDER BY created_at DESC, provider_id DESC""",
                ("tmdb",),
            ).fetchall()
        return [{"provider": "tmdb", "media_type": row[0], "provider_id": row[1],
                 "snapshot": json.loads(row[2]), "note": row[3], "created_at": row[4], "updated_at": row[5]}
                for row in rows]

    def delete_favorite_by_imdb(
        self,
        media_type: str,
        imdb_id: str,
        title: str,
        original_title: str | None = None,
        year: int | None = None,
    ) -> bool:
        """Delete only IMDb-linked snapshots whose title and year also agree.

        IMDb IDs are cross-provider links, not the external-favorite primary
        key. Require corroborating catalogue metadata before removing a
        potentially mis-mapped TMDB favorite.
        """
        if not imdb_id or len(imdb_id) > 32 or not title or year is None:
            return False

        def normalize(value: object) -> str:
            if not isinstance(value, str):
                return ""
            normalized = unicodedata.normalize("NFKC", value).casefold()
            return "".join(char for char in normalized if char.isalnum())

        local_titles = {
            normalize(value) for value in (title, original_title) if normalize(value)
        }
        if not local_titles:
            return False

        self._init()
        with self._lock, self._connection() as connection:
            rows = connection.execute(
                """SELECT provider_id, snapshot_json FROM external_favorites
                   WHERE provider=? AND media_type=?""",
                ("tmdb", media_type),
            ).fetchall()
            matching_ids = []
            for provider_id, snapshot_json in rows:
                try:
                    snapshot = json.loads(snapshot_json)
                except (TypeError, json.JSONDecodeError):
                    continue
                if not isinstance(snapshot, dict) or snapshot.get("imdb_id") != imdb_id:
                    continue
                if snapshot.get("year") != year:
                    continue
                snapshot_titles = {
                    normalize(snapshot.get("title")),
                    normalize(snapshot.get("original_title")),
                } - {""}
                if local_titles.intersection(snapshot_titles):
                    matching_ids.append(int(provider_id))
            for provider_id in matching_ids:
                connection.execute(
                    """DELETE FROM external_favorites
                       WHERE provider=? AND media_type=? AND provider_id=?""",
                    ("tmdb", media_type, provider_id),
                )
        return bool(matching_ids)


    def delete_favorite(self, media_type: str, provider_id: int) -> bool:
        self._init()
        with self._lock, self._connection() as connection:
            cursor = connection.execute(
                """DELETE FROM external_favorites
                   WHERE provider=? AND media_type=? AND provider_id=?""",
                ("tmdb", media_type, int(provider_id)),
            )
            return cursor.rowcount > 0

    def backup_daily(self, backup_dir: Path, keep_days: int = 7, force: bool = False) -> Path:
        """Create one verified SQLite backup per day, retaining a short history."""
        self._init()
        import os

        backup_dir.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%d", time.localtime())
        destination = backup_dir / ("discovery-cache-" + stamp + ".sqlite3")
        if destination.exists() and not force:
            probe = sqlite3.connect(destination, timeout=5)
            try:
                integrity = probe.execute("PRAGMA integrity_check").fetchone()
            finally:
                probe.close()
            if integrity and integrity[0] == "ok":
                self._prune_backups(backup_dir, keep_days)
                return destination
            destination.unlink(missing_ok=True)

        temporary = backup_dir / (".discovery-cache-" + stamp + ".tmp")
        temporary.unlink(missing_ok=True)
        source = self._connect()
        target = sqlite3.connect(temporary, timeout=10)
        try:
            source.backup(target)
            integrity = target.execute("PRAGMA integrity_check").fetchone()
            if not integrity or integrity[0] != "ok":
                raise RuntimeError("Discovery cache backup failed SQLite integrity_check")
            target.commit()
            target.close()
            source.close()
            os.replace(temporary, destination)
        except Exception:
            try:
                target.close()
            finally:
                source.close()
                temporary.unlink(missing_ok=True)
            raise
        self._prune_backups(backup_dir, keep_days)
        return destination

    @staticmethod
    def _prune_backups(backup_dir: Path, keep_days: int) -> None:
        cutoff = time.time() - max(1, keep_days) * 86400
        for candidate in backup_dir.glob("discovery-cache-????????.sqlite3"):
            try:
                if candidate.stat().st_mtime < cutoff:
                    candidate.unlink()
            except OSError:
                logger.warning("Unable to prune old discovery cache backup: %s", candidate)

    def clear_expired(self) -> int:
        self._init()
        with self._lock, self._connection() as connection:
            cursor = connection.execute(
                "DELETE FROM provider_response_cache WHERE stale_until <= ?",
                (int(time.time()),),
            )
            removed = int(cursor.rowcount)
        self._compact_if_needed()
        return removed

    def _compact_if_needed(self) -> None:
        if not self.path.exists():
            return
        wal_path = Path(str(self.path) + "-wal")
        total_bytes = self.path.stat().st_size + (wal_path.stat().st_size if wal_path.exists() else 0)
        if total_bytes <= MAX_CACHE_DB_BYTES:
            return
        with self._lock, self._connection() as connection:
            connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            connection.execute("PRAGMA incremental_vacuum")
            if self.path.stat().st_size > MAX_CACHE_DB_BYTES:
                connection.execute("VACUUM")


provider_response_cache = ProviderResponseCache()
