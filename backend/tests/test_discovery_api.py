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
        if endpoint.endswith("/external_ids"):
            return {"id": 42, "imdb_id": "tt0000042"}
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

def test_discover_accepts_vote_count_sort(monkeypatch):
    calls = []

    async def fake_get_json(endpoint, params=None, ttl=900):
        calls.append((endpoint, params))
        return {"page": 1, "total_pages": 1, "total_results": 0, "results": []}

    monkeypatch.setattr(discovery.tmdb_client, "get_json", fake_get_json)
    with _client(monkeypatch) as client:
        response = client.get("/api/discovery/discover", params={
            "media_type": "movie", "sort_by": "vote_count.desc", "min_votes": 0
        })

    assert response.status_code == 200
    assert calls[0][0] == "/discover/movie"
    assert calls[0][1]["sort_by"] == "vote_count.desc"


def test_detail_returns_transient_overview(monkeypatch):
    calls = []

    async def fake_get_json(endpoint, params=None, ttl=900, include_overview=False):
        calls.append((endpoint, include_overview))
        return {
            "id": 42,
            "title": "Alien",
            "original_title": "Alien",
            "release_date": "1979-05-25",
            "overview": "A commercial spaceship crew encounters a deadly organism.",
            "vote_average": 8.5,
            "vote_count": 1000,
            "genres": [{"id": 27, "name": "恐怖"}],
            "production_countries": [{"iso_3166_1": "US", "name": "美国"}],
        }

    monkeypatch.setattr(discovery.tmdb_client, "get_json", fake_get_json)
    with _client(monkeypatch) as client:
        response = client.get("/api/discovery/movie/42")

    assert response.status_code == 200
    assert response.json()["overview"].startswith("A commercial spaceship")
    assert calls == [("/movie/42", True)]



def test_local_imdb_rating_is_attached_only_by_exact_tmdb_identity():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from app.database import Base, Movie
    from app.routers.discovery import _attach_local_imdb_ratings

    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(Movie(
            tmdb_id="278",
            imdb_id="tt0111161",
            title="肖申克的救赎",
            type="movie",
            imdb_rating=9.3,
            imdb_rating_count=3000000,
        ))
        db.commit()
        items = [
            {"provider_id": 278, "media_type": "movie"},
            {"provider_id": 999999, "media_type": "movie"},
        ]
        result = _attach_local_imdb_ratings(db, items)
        assert result[0]["imdb_id"] == "tt0111161"
        assert result[0]["imdb_rating"] == 9.3
        assert result[0]["imdb_rating_count"] == 3000000
        assert result[1]["imdb_rating"] is None
        assert result[1]["imdb_rating_count"] is None
    engine.dispose()



def test_search_enriches_non_catalogue_results_from_full_imdb_index(monkeypatch):
    async def fake_get_json(endpoint, params=None, ttl=900):
        if endpoint == "/search/multi":
            return {
                "page": 1, "total_pages": 1, "total_results": 1,
                "results": [{
                    "id": 999, "media_type": "movie", "title": "New title",
                    "release_date": "2024-01-01", "vote_average": 7.1, "vote_count": 88,
                }],
            }
        if endpoint == "/movie/999/external_ids":
            return {"id": 999, "imdb_id": "tt1234567"}
        raise AssertionError(f"Unexpected TMDB endpoint: {endpoint}")

    monkeypatch.setattr(discovery.tmdb_client, "get_json", fake_get_json)
    monkeypatch.setattr(discovery, "lookup_ratings", lambda ids: {"tt1234567": (8.4, 12345)})
    with _client(monkeypatch) as client:
        response = client.get("/api/discovery/search", params={"q": "New title"})
    assert response.status_code == 200
    item = response.json()["items"][0]
    assert item["imdb_id"] == "tt1234567"
    assert item["imdb_rating"] == 8.4
    assert item["imdb_rating_count"] == 12345


def test_discover_enriches_results_with_full_imdb_index(monkeypatch):
    async def fake_get_json(endpoint, params=None, ttl=900):
        if endpoint == "/discover/movie":
            return {
                "page": 1, "total_pages": 1, "total_results": 1,
                "results": [{"id": 777, "title": "Discover title", "release_date": "2020-01-01"}],
            }
        if endpoint == "/movie/777/external_ids":
            return {"id": 777, "imdb_id": "tt7654321"}
        raise AssertionError(f"Unexpected TMDB endpoint: {endpoint}")

    monkeypatch.setattr(discovery.tmdb_client, "get_json", fake_get_json)
    monkeypatch.setattr(discovery, "lookup_ratings", lambda ids: {"tt7654321": (7.9, 9876)})
    with _client(monkeypatch) as client:
        response = client.get("/api/discovery/discover", params={"media_type": "movie", "min_votes": 0})
    assert response.status_code == 200
    item = response.json()["items"][0]
    assert item["imdb_id"] == "tt7654321"
    assert item["imdb_rating"] == 7.9
    assert item["imdb_rating_count"] == 9876



def test_online_detail_uses_full_imdb_index(monkeypatch):
    async def fake_get_json(endpoint, params=None, ttl=900, include_overview=False):
        return {
            "id": 654,
            "title": "Online title",
            "release_date": "2022-01-01",
            "external_ids": {"imdb_id": "tt7654321"},
            "genres": [],
        }

    monkeypatch.setattr(discovery.tmdb_client, "get_json", fake_get_json)
    monkeypatch.setattr(discovery, "lookup_ratings", lambda ids: {"tt7654321": (8.1, 45678)})
    with _client(monkeypatch) as client:
        response = client.get("/api/discovery/movie/654")
    assert response.status_code == 200
    body = response.json()
    assert body["imdb_id"] == "tt7654321"
    assert body["imdb_rating"] == 8.1
    assert body["imdb_rating_count"] == 45678
