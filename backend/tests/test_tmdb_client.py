"""TMDB client response sanitization and cache resilience tests."""
import asyncio
import sqlite3

from app.services import tmdb_client as tmdb_module
from app.services.tmdb_client import _strip_unapproved_synopsis


def test_tmdb_overview_is_removed_recursively_before_persistence():
    payload = {
        "id": 10,
        "title": "Example",
        "overview": "Do not persist this synopsis",
        "results": [
            {"id": 11, "title": "Nested", "overview": "Also remove this"},
            {"id": 12, "title": "No synopsis"}
        ],
        "credits": {"cast": [{"name": "Actor", "overview": "Nested arbitrary text"}]}
    }
    sanitized = _strip_unapproved_synopsis(payload)

    assert "overview" not in sanitized
    assert all("overview" not in item for item in sanitized["results"])
    assert "overview" not in sanitized["credits"]["cast"][0]
    assert sanitized["results"][0]["title"] == "Nested"



def test_cache_read_failure_does_not_block_upstream_response(monkeypatch):
    client = tmdb_module.TMDBClient()

    def broken_cache_read(*args, **kwargs):
        raise sqlite3.OperationalError("simulated cache I/O failure")

    async def fake_fetch(key, endpoint, params, ttl):
        return {"results": [{"id": 42, "title": "Alien"}]}

    monkeypatch.setattr(tmdb_module.provider_response_cache, "get", broken_cache_read)
    monkeypatch.setattr(client, "_fetch_and_cache", fake_fetch)

    result = asyncio.run(client.get_json("/search/movie", {"query": "Alien"}))
    assert result["results"][0]["id"] == 42


def test_cache_write_failure_does_not_discard_successful_upstream_payload(monkeypatch):
    client = tmdb_module.TMDBClient()

    def broken_cache_write(*args, **kwargs):
        raise sqlite3.OperationalError("simulated disk full")

    monkeypatch.setattr(tmdb_module.provider_response_cache, "set", broken_cache_write)
    asyncio.run(client._cache_set("cache-key", "/search/movie", {"results": []}, 900))



def test_cancelling_one_waiter_does_not_cancel_shared_upstream(monkeypatch):
    import contextlib

    client = tmdb_module.TMDBClient()

    async def scenario():
        started = asyncio.Event()
        release = asyncio.Event()
        calls = 0

        async def no_cache(key, allow_stale=False):
            return None

        async def fake_fetch(key, endpoint, params, ttl):
            nonlocal calls
            calls += 1
            started.set()
            await release.wait()
            return {"results": [{"id": 99}]}

        monkeypatch.setattr(client, "_cache_get", no_cache)
        monkeypatch.setattr(client, "_fetch_and_cache", fake_fetch)

        first = asyncio.create_task(client.get_json("/search/movie", {"query": "cancel-safe"}))
        await started.wait()
        second = asyncio.create_task(client.get_json("/search/movie", {"query": "cancel-safe"}))
        await asyncio.sleep(0)
        first.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await first
        release.set()
        result = await second
        assert result == {"results": [{"id": 99}]}
        assert calls == 1

    asyncio.run(scenario())
