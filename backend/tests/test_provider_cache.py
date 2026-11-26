"""Persistent provider cache bounds and expiry behavior."""
import time

from app.services import provider_cache as provider_cache_module
from app.services.provider_cache import ProviderResponseCache


def test_cache_round_trip_and_key_normalization(tmp_path):
    cache = ProviderResponseCache(tmp_path / "provider.sqlite3")
    key1 = cache.make_key("tmdb", "/search/movie", {"q": "Alien", "page": 1})
    key2 = cache.make_key("tmdb", "/search/movie", {"page": 1, "q": "Alien"})
    assert key1 == key2

    assert cache.set(key1, "tmdb", "/search/movie", {"results": [{"id": 1}]}, 60)
    cached = cache.get(key1)
    assert cached == ({"results": [{"id": 1}]}, False)
    assert cache.stats()["hits"] == 1
    assert cache.stats()["writes"] == 1


def test_cache_returns_stale_only_when_requested(tmp_path):
    cache = ProviderResponseCache(tmp_path / "provider.sqlite3")
    key = cache.make_key("tmdb", "/search/movie", {"q": "Alien"})
    cache.set(key, "tmdb", "/search/movie", {"results": []}, 60)

    with cache._connection() as connection:
        connection.execute(
            "UPDATE provider_response_cache SET expires_at=? WHERE cache_key=?",
            (int(time.time()) - 1, key),
        )

    assert cache.get(key) is None
    stale = cache.get(key, allow_stale=True)
    assert stale == ({"results": []}, True)


def test_cache_rejects_oversized_entries(tmp_path):
    cache = ProviderResponseCache(tmp_path / "provider.sqlite3")
    key = cache.make_key("tmdb", "/detail", {"id": 1})
    assert not cache.set(key, "tmdb", "/detail", {"blob": "x" * (1024 * 1024 + 1)}, 60)
    assert cache.get(key) is None


def test_cache_stats_and_expiry_cleanup(tmp_path):
    cache = ProviderResponseCache(tmp_path / "provider.sqlite3")
    key = cache.make_key("tmdb", "/search", {"q": "x"})
    cache.set(key, "tmdb", "/search", {"results": []}, 60)
    assert cache.stats()["entries"] == 1
    assert cache.stats()["bytes"] > 0

    with cache._connection() as connection:
        connection.execute(
            "UPDATE provider_response_cache SET stale_until=? WHERE cache_key=?",
            (int(time.time()) - 1, key),
        )
    assert cache.clear_expired() == 1
    assert cache.stats()["entries"] == 0



def test_has_favorite_checks_only_the_requested_provider_identity(tmp_path):
    cache = ProviderResponseCache(tmp_path / "provider.sqlite3")
    cache.save_favorite("movie", 550, {"title": "Fight Club"})
    cache.save_favorite("tv", 123, {"title": "Test Series"})

    assert cache.has_favorite("movie", 550)
    assert cache.has_favorite("tv", 123)
    assert not cache.has_favorite("movie", 123)
    assert not cache.has_favorite("tv", 550)


def test_delete_favorite_by_imdb_removes_only_the_matching_media_identity(tmp_path):
    cache = ProviderResponseCache(tmp_path / "provider.sqlite3")
    cache.save_favorite("movie", 10, {"title": "Film", "imdb_id": "tt1234567"})
    cache.save_favorite("movie", 11, {"title": "Other Film", "imdb_id": "tt7654321"})
    cache.save_favorite("tv", 10, {"title": "Series", "imdb_id": "tt1234567"})

    assert cache.delete_favorite_by_imdb("movie", "tt1234567")
    assert not cache.has_favorite("movie", 10)
    assert cache.has_favorite("movie", 11)
    assert cache.has_favorite("tv", 10)


def test_external_favorites_survive_cache_eviction(tmp_path):
    cache = ProviderResponseCache(tmp_path / "provider.sqlite3")
    saved = cache.save_favorite(
        "movie", 550,
        {"title": "Fight Club", "year": 1999, "poster_path": "/fight.jpg"},
        "rewatch",
    )
    assert saved["provider_id"] == 550
    assert saved["snapshot"]["title"] == "Fight Club"

    cache.set("search-cache-key", "tmdb", "/search", {"results": []}, 1)
    with cache._connection() as connection:
        connection.execute("DELETE FROM provider_response_cache")

    favorites = cache.list_favorites()
    assert len(favorites) == 1
    assert favorites[0]["provider_id"] == 550
    assert favorites[0]["note"] == "rewatch"
    assert cache.delete_favorite("movie", 550)
    assert cache.list_favorites() == []




def test_cache_evicts_least_recently_used_rows_at_hard_limit(tmp_path, monkeypatch):
    monkeypatch.setattr(provider_cache_module, "MAX_CACHE_ROWS", 5)
    cache = ProviderResponseCache(tmp_path / "provider.sqlite3")
    keys = []
    for index in range(8):
        key = cache.make_key("tmdb", "/search", {"q": str(index)})
        keys.append(key)
        cache.set(key, "tmdb", "/search", {"results": [{"id": index}]}, 3600)
        with cache._connection() as connection:
            connection.execute(
                "UPDATE provider_response_cache SET accessed_at=? WHERE cache_key=?",
                (1000 + index, key),
            )
    assert cache.stats()["entries"] == 5
    assert cache.get(keys[0]) is None
    assert cache.get(keys[-1]) is not None

def test_daily_backup_preserves_external_favorites(tmp_path):
    cache = ProviderResponseCache(tmp_path / "source" / "discovery.sqlite3")
    cache.save_favorite(
        "tv", 1234,
        {"title": "Test Series", "year": 2025, "poster_path": "/series.jpg"},
    )
    backup_path = cache.backup_daily(tmp_path / "backups")
    restored = ProviderResponseCache(backup_path)
    favorites = restored.list_favorites()
    assert len(favorites) == 1
    assert favorites[0]["media_type"] == "tv"
    assert favorites[0]["snapshot"]["title"] == "Test Series"



def test_forced_daily_backup_refreshes_after_favorite_write(tmp_path):
    cache = ProviderResponseCache(tmp_path / "source" / "discovery.sqlite3")
    backup_dir = tmp_path / "backups"
    first = cache.backup_daily(backup_dir)
    cache.save_favorite("movie", 77, {"title": "New Favorite"})
    refreshed = cache.backup_daily(backup_dir, force=True)

    assert first == refreshed
    restored = ProviderResponseCache(refreshed)
    assert restored.list_favorites()[0]["snapshot"]["title"] == "New Favorite"



def test_cache_max_age_rejects_an_entry_even_when_its_ttl_is_still_fresh(tmp_path):
    cache = ProviderResponseCache(tmp_path / "provider.sqlite3")
    key = cache.make_key("tmdb", "/movie/1", {"language": "zh-CN"})
    cache.set(key, "tmdb", "/movie/1", {"vote_average": 7.8}, 7 * 86400)

    with cache._connection() as connection:
        connection.execute(
            "UPDATE provider_response_cache SET fetched_at=? WHERE cache_key=?",
            (int(time.time()) - 7 * 3600, key),
        )

    assert cache.get(key) == ({"vote_average": 7.8}, False)
    assert cache.get(key, max_age_seconds=6 * 3600) is None
    assert cache.get(key, allow_stale=True, max_age_seconds=6 * 3600) is None
