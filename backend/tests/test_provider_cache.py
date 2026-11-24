"""Persistent provider cache bounds and expiry behavior."""
import time

from app.services.provider_cache import ProviderResponseCache


def test_cache_round_trip_and_key_normalization(tmp_path):
    cache = ProviderResponseCache(tmp_path / "provider.sqlite3")
    key1 = cache.make_key("tmdb", "/search/movie", {"q": "Alien", "page": 1})
    key2 = cache.make_key("tmdb", "/search/movie", {"page": 1, "q": "Alien"})
    assert key1 == key2

    assert cache.set(key1, "tmdb", "/search/movie", {"results": [{"id": 1}]}, 60)
    cached = cache.get(key1)
    assert cached == ({"results": [{"id": 1}]}, False)


def test_cache_returns_stale_only_when_requested(tmp_path):
    cache = ProviderResponseCache(tmp_path / "provider.sqlite3")
    key = cache.make_key("tmdb", "/search/movie", {"q": "Alien"})
    cache.set(key, "tmdb", "/search/movie", {"results": []}, 60)

    with cache._connect() as connection:
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

    with cache._connect() as connection:
        connection.execute(
            "UPDATE provider_response_cache SET stale_until=? WHERE cache_key=?",
            (int(time.time()) - 1, key),
        )
    assert cache.clear_expired() == 1
    assert cache.stats()["entries"] == 0



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
    with cache._connect() as connection:
        connection.execute("DELETE FROM provider_response_cache")

    favorites = cache.list_favorites()
    assert len(favorites) == 1
    assert favorites[0]["provider_id"] == 550
    assert favorites[0]["note"] == "rewatch"
    assert cache.delete_favorite("movie", 550)
    assert cache.list_favorites() == []
