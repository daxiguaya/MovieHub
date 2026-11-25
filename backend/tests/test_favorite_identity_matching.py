"""Strict cross-provider favorite identity tests."""

from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

import app.database as database
import app.main as main_module
from app.config import settings
from app.routers import favorites as favorites_router
from scripts.init_db import initialize


def test_online_favorite_uses_exact_title_year_and_director_to_link_chart_movie(
    tmp_path,
    monkeypatch,
):
    db_path = tmp_path / "moviehub-data" / "movies.db"
    backend_dir = Path(__file__).resolve().parents[1]
    initialize(db_path, backend_dir / "migrations" / "001_moviehub_core.sql")
    engine = database.create_engine(
        f"sqlite:///{db_path.as_posix()}",
        connect_args={"check_same_thread": False},
    )
    TargetSession = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    with TargetSession() as db:
        movie = database.Movie(
            douban_id="1292052",
            title="肖申克的救赎",
            original_title="The Shawshank Redemption",
            year=1994,
            rating=9.7,
            rating_count=2500000,
            type="movie",
            directors='["弗兰克·德拉邦特"]',
            actors="[]",
        )
        db.add(movie)
        db.commit()
        movie_id = movie.id

    monkeypatch.setattr(database, "get_db_path", lambda: str(db_path))
    monkeypatch.setattr(database, "SessionLocal", TargetSession)
    monkeypatch.setattr(main_module, "get_db_path", lambda: str(db_path))
    monkeypatch.setattr(settings, "api_key", "favorites-test-key")
    monkeypatch.setattr(main_module.poster_cache_service, "clear_expired_cache", lambda: None)
    monkeypatch.setattr(main_module.provider_response_cache, "clear_expired", lambda: 0)
    monkeypatch.setattr(main_module.provider_response_cache, "backup_daily", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        favorites_router.provider_response_cache,
        "delete_favorite",
        lambda media_type, provider_id: False,
    )
    monkeypatch.setattr(
        favorites_router.provider_response_cache,
        "save_favorite",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("linked chart movies must not create duplicate external favorites")),
    )

    headers = {"X-API-Key": "favorites-test-key"}
    params = {
        "title": "肖申克的救赎",
        "original_title": "The Shawshank Redemption",
        "year": 1994,
        "directors": ["弗兰克·德拉邦特"],
    }
    try:
        with TestClient(main_module.app) as client:
            saved = client.put(
                "/api/favorites/external/movie/278",
                headers=headers,
                json={"snapshot": {
                    **params,
                    "rating": 9.3,
                    "rating_count": 2500000,
                    "directors": ["弗兰克·德拉邦特"],
                }},
            )
            status_response = client.get(
                "/api/favorites/external/status/movie/278",
                headers=headers,
                params=params,
            )
            listing = client.get("/api/favorites", headers=headers)
            removed = client.delete(
                "/api/favorites/external/movie/278",
                headers=headers,
                params=params,
            )
            empty_listing = client.get("/api/favorites", headers=headers)

        assert saved.status_code == 200
        assert saved.json()["linked_movie_id"] == movie_id
        assert status_response.status_code == 200
        assert status_response.json()["is_favorite"] is True
        assert len(listing.json()) == 1
        assert listing.json()[0]["movie"]["id"] == movie_id
        assert removed.status_code == 204
        assert empty_listing.json() == []
    finally:
        engine.dispose()
