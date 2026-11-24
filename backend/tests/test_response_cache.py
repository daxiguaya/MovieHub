"""Tests for bounded persistent upstream-response caching."""

import sqlite3

from app.services.response_cache import SQLiteResponseCache, build_cache_key


def _database(path):
    connection = sqlite3.connect(str(path))
    connection.executescript(
        """
        CREATE TABLE external_api_cache (
            cache_key VARCHAR(64) PRIMARY KEY, provider VARCHAR(32) NOT NULL,
            endpoint VARCHAR(128) NOT NULL, params_json TEXT NOT NULL,
            response_json TEXT NOT NULL, fetched_at INTEGER NOT NULL,
            expires_at INTEGER NOT NULL, last_accessed_at INTEGER NOT NULL,
            payload_bytes INTEGER NOT NULL, hit_count INTEGER NOT NULL DEFAULT 0
        );
        CREATE INDEX ix_external_api_cache_expires_at ON external_api_cache(expires_at);
        CREATE INDEX ix_external_api_cache_last_accessed_at ON external_api_cache(last_accessed_at);
        """
    )
    connection.close()


def test_cache_key_is_stable_and_namespaced_by_type():
    a = build_cache_key("tmdb", "/search/movie", {"query": "Alien", "page": 1})
    b = build_cache_key("TMDB", "/search/movie", {"page": 1, "query": "Alien"})
    c = build_cache_key("tmdb", "/search/tv", {"query": "Alien", "page": 1})
    assert a == b
    assert a != c


def test_cache_round_trip_and_hit_accounting(tmp_path):
    path = tmp_path / "cache.db"
    _database(path)
    cache = SQLiteResponseCache(path)
    key = build_cache_key("tmdb", "/search/movie", {"query": "Alien"})
    assert cache.set(key, "tmdb", "/search/movie", {"query": "Alien"}, {"results": [{"id": 1}]}, 60)
    assert cache.get(key) == {"results": [{"id": 1}]}
    assert cache.stats()["hits"] == 1


def test_cache_rejects_oversized_payload(tmp_path):
    path = tmp_path / "cache.db"
    _database(path)
    cache = SQLiteResponseCache(path, max_entry_bytes=256)
    key = build_cache_key("tmdb", "/search/movie", {"query": "big"})
    assert cache.set(key, "tmdb", "/search/movie", {}, {"results": ["x" * 400]}, 60) is False
    assert cache.stats()["entries"] == 0


def test_cache_evicts_least_recently_used_at_entry_limit(tmp_path):
    path = tmp_path / "cache.db"
    _database(path)
    cache = SQLiteResponseCache(path, max_entries=2, max_bytes=4096)
    keys = [build_cache_key("tmdb", "/search/movie", {"query": str(i)}) for i in range(3)]
    for index, key in enumerate(keys):
        cache.set(key, "tmdb", "/search/movie", {"q": index}, {"id": index}, 600)
    assert cache.stats()["entries"] == 2
    assert cache.get(keys[0]) is None
    assert cache.get(keys[1]) == {"id": 1}
    assert cache.get(keys[2]) == {"id": 2}


def test_expired_cleanup_is_bounded(tmp_path):
    path = tmp_path / "cache.db"
    _database(path)
    cache = SQLiteResponseCache(path)
    connection = sqlite3.connect(str(path))
    for index in range(5):
        connection.execute(
            "INSERT INTO external_api_cache VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (str(index), "tmdb", "/search/movie", "{}", "{}", 1, 1, 1, 2, 0),
        )
    connection.commit()
    connection.close()
    assert cache.clear_expired(batch_size=2) == 2
    assert cache.stats()["entries"] == 3