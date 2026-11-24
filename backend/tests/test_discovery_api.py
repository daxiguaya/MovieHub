"""TMDB response normalization and discovery endpoint guardrails."""
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.routers import discovery
from app.services.poster_service import poster_cache_service
from app.services.provider_cache import provider_response_cache


def _client(monkeypatch):
    monkeypatch.setattr(poster_cache_service, "clear_expired_cache", lambda: 0)
    monkeypatch.setattr(provider_response_cache, "clear_expired", lambda: 0)
    monkeypatch.setattr(provider_response_cache, "backup_daily", lambda *args, **kwargs: None)
    return TestClient(app)


def test_search_requires_two_character_query(monkeypatch):
    with _client(monkeypatch) as client:
        response = client.get("/api/discovery/search", params={"q": "a"})
    assert response.status_code == 422


def test_search_fetches_only_requested_page(monkeypatch):
    calls = []

    async def fake_get_json(endpoint, params=None, ttl=900):
        calls.append((endpoint, params, ttl))
        return {
            "page": params["page"],
            "total_pages": 999,
            "total_results": 999999,
            "results": [
                {"id": 42, "media_type": "movie", "title": "Alien",
                 "original_title": "Alien", "release_date": "1979-05-25",
                 "vote_average": 8.5, "vote_count": 1000,
                 "poster_path": "/alien.jpg", "genre_ids": [27]},
                {"id": 7, "media_type": "person", "name": "Ridley Scott"},
            ],
        }

    monkeypatch.setattr(discovery.tmdb_client, "get_json", fake_get_json)
    with _client(monkeypatch) as client:
        response = client.get(
            "/api/discovery/search",
            params={"q": "Alien", "page": 3, "media_type": "all"},
        )

    assert response.status_code == 200
    body = response.json()
    assert calls[0][0] == "/search/multi"
    assert calls[0][1]["page"] == 3
    assert body["page"] == 3
    assert body["total_pages"] == 500
    assert len(body["items"]) == 1
    assert body["items"][0]["provider_id"] == 42
    assert body["items"][0]["year"] == 1979


def test_discover_enforces_page_and_vote_threshold_defaults(monkeypatch):
    with _client(monkeypatch) as client:
        response = client.get("/api/discovery/discover", params={"page": 501})
    assert response.status_code == 422
