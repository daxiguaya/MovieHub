"""Protected favorites API integration tests using a temporary MovieHub database."""

from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

import app.database as database
import app.main as main_module
from app.config import settings
from scripts.init_db import initialize


def test_favorites_use_internal_movie_ids_and_are_idempotent(tmp_path, monkeypatch):
    db_path = tmp_path / "moviehub-data" / "movies.db"
    backend_dir = Path(__file__).resolve().parents[1]
    initialize(db_path, backend_dir / "migrations" / "001_moviehub_core.sql")

    engine = database.create_engine(
        f"sqlite:///{db_path.as_posix()}",
        connect_args={"check_same_thread": False},
    )
    TargetSession = sessionmaker(
        bind=engine,
        autoflush=False,
        expire_on_commit=False,
    )
    monkeypatch.setattr(database, "get_db_path", lambda: str(db_path))
    monkeypatch.setattr(database, "SessionLocal", TargetSession)
    monkeypatch.setattr(main_module, "get_db_path", lambda: str(db_path))
    monkeypatch.setattr(settings, "api_key", "favorites-test-key")
    monkeypatch.setattr(
        main_module.poster_cache_service,
        "clear_expired_cache",
        lambda: None,
    )

    with TargetSession() as db:
        movie = database.Movie(
            douban_id="987654",
            title="Favorites Fixture",
            year=2024,
            rating=8.2,
            rating_count=1200,
            type="movie",
            directors="[]",
            actors="[]",
        )
        db.add(movie)
        db.commit()
        internal_movie_id = movie.id

    headers = {"X-API-Key": "favorites-test-key"}
    try:
        with TestClient(main_module.app) as client:
            assert client.get("/api/favorites").status_code == 401
            assert client.put(
                f"/api/favorites/{internal_movie_id}",
                json={"note": "rewatch"},
            ).status_code == 401

            first = client.put(
                f"/api/favorites/{internal_movie_id}",
                headers=headers,
                json={"note": "rewatch"},
            )
            second = client.put(
                f"/api/favorites/{internal_movie_id}",
                headers=headers,
                json={"note": "rewatch later"},
            )
            listing = client.get("/api/favorites", headers=headers)
            wrong_identifier = client.put(
                "/api/favorites/987654",
                headers=headers,
                json={"note": ""},
            )

            removed = client.delete(
                f"/api/favorites/{internal_movie_id}",
                headers=headers,
            )
            empty_listing = client.get("/api/favorites", headers=headers)
            missing_remove = client.delete(
                f"/api/favorites/{internal_movie_id}",
                headers=headers,
            )

        assert first.status_code == 200
        assert first.json()["movie"]["id"] == internal_movie_id
        assert first.json()["movie"]["douban_id"] == "987654"
        assert first.json()["note"] == "rewatch"

        assert second.status_code == 200
        assert second.json()["note"] == "rewatch later"
        assert listing.status_code == 200
        assert len(listing.json()) == 1
        assert listing.json()[0]["movie"]["id"] == internal_movie_id
        assert listing.json()[0]["note"] == "rewatch later"

        # A provider ID is not accepted as a favorite key.
        assert wrong_identifier.status_code == 404

        assert removed.status_code == 204
        assert empty_listing.status_code == 200
        assert empty_listing.json() == []
        assert missing_remove.status_code == 404

        with TargetSession() as db:
            assert db.scalars(select(database.Favorite)).all() == []
    finally:
        engine.dispose()
