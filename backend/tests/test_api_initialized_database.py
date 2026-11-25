"""Data API smoke tests with an explicitly initialized temporary database."""

from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker
from app.database import Movie
from app.routers import movies as movies_router

import app.database as database
import app.main as main_module
from scripts.init_db import initialize


def test_data_apis_work_with_explicitly_initialized_database(
    tmp_path,
    monkeypatch,
):
    db_path = tmp_path / "moviehub-data" / "movies.db"
    backend_dir = Path(__file__).resolve().parents[1]
    migration_path = backend_dir / "migrations" / "001_moviehub_core.sql"

    initialize(db_path, migration_path)

    engine = database.create_engine(
        f"sqlite:///{db_path.as_posix()}",
        connect_args={"check_same_thread": False},
    )
    TargetSession = sessionmaker(
        bind=engine,
        autoflush=False,
        expire_on_commit=False,
    )

    with TargetSession() as db:
        movie = Movie(
            douban_id="654321",
            title="Internal ID Detail Fixture",
            year=2023,
            rating=8.0,
            rating_count=100,
            type="movie",
            directors="[]",
            actors="[]",
        )
        db.add(movie)
        db.commit()
        movie_id = movie.id

    monkeypatch.setattr(database, "get_db_path", lambda: str(db_path))
    monkeypatch.setattr(database, "SessionLocal", TargetSession)
    monkeypatch.setattr(main_module, "get_db_path", lambda: str(db_path))
    monkeypatch.setattr(
        main_module.poster_cache_service,
        "clear_expired_cache",
        lambda: None,
    )

    try:
        with TestClient(main_module.app) as client:
            charts_response = client.get("/api/charts")
            movies_response = client.get("/api/movies")
            movie_detail_response = client.get(f"/api/movies/id/{movie_id}")
            health_response = client.get("/api/health")
            readiness_response = client.get("/api/ready")

        assert charts_response.status_code == 200
        assert isinstance(charts_response.json(), list)
        assert movies_response.status_code == 200
        assert movie_detail_response.status_code == 200
        assert movie_detail_response.json()["id"] == movie_id
        assert movie_detail_response.json()["title"] == "Internal ID Detail Fixture"
        assert health_response.status_code == 200
        assert health_response.json() == {"status": "healthy"}
        assert readiness_response.status_code == 200
        assert readiness_response.json() == {
            "status": "ready",
            "schema_version": database.CURRENT_SCHEMA_VERSION,
        }
    finally:
        engine.dispose()



def test_local_chart_detail_uses_transient_tmdb_metadata_without_overwriting_douban(
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
        movie = Movie(
            douban_id="654322",
            tmdb_id="42",
            title="Annual Fixture",
            year=None,
            rating=8.4,
            rating_count=0,
            type="movie",
            directors='["Director from Douban"]',
            actors="[]",
        )
        db.add(movie)
        db.commit()
        movie_id = movie.id

    monkeypatch.setattr(database, "get_db_path", lambda: str(db_path))
    monkeypatch.setattr(database, "SessionLocal", TargetSession)
    monkeypatch.setattr(main_module, "get_db_path", lambda: str(db_path))
    monkeypatch.setattr(main_module.poster_cache_service, "clear_expired_cache", lambda: None)
    monkeypatch.setattr(main_module.provider_response_cache, "clear_expired", lambda: 0)
    monkeypatch.setattr(main_module.provider_response_cache, "backup_daily", lambda *args, **kwargs: None)

    calls = []
    async def fake_get_json(endpoint, params=None, ttl=900, include_overview=False):
        calls.append((endpoint, include_overview))
        if endpoint == "/search/movie":
            return {"results": [{"id": 42, "title": "Annual Fixture", "release_date": "2025-01-29"}]}
        return {
            "id": 42,
            "title": "Annual Fixture",
            "release_date": "2025-01-29",
            "vote_average": 7.9,
            "vote_count": 2500,
            "overview": "Transient TMDB synopsis",
            "genres": [{"id": 16, "name": "动画"}],
            "production_countries": [{"iso_3166_1": "CN", "name": "中国大陆"}],
            "credits": {
                "crew": [
                    {"job": "Director", "name": "TMDB Director"},
                    {"job": "Director", "name": "Director from Douban"},
                ],
                "cast": [{"name": "TMDB Actor"}],
            },
            "runtime": 110,
            "poster_path": "/annual.jpg",
        }

    monkeypatch.setattr(movies_router.tmdb_client, "get_json", fake_get_json)
    try:
        with TestClient(main_module.app) as client:
            response = client.get(f"/api/movies/id/{movie_id}")
        assert response.status_code == 200
        body = response.json()
        assert body["year"] is None
        assert body["rating"] == 8.4
        assert body["tmdb_metadata"]["year"] == 2025
        assert body["tmdb_metadata"]["rating"] == 7.9
        assert body["tmdb_metadata"]["overview"] == "Transient TMDB synopsis"
        assert body["tmdb_metadata"]["genres"] == ["动画"]
        assert body["tmdb_metadata"]["regions"] == ["中国大陆"]
        assert body["directors"] == ["Director from Douban"]
        assert body["tmdb_metadata"]["directors"] == ["TMDB Director", "Director from Douban"]
        assert calls == [("/search/movie", False), ("/movie/42", True)]
        with TargetSession() as db:
            stored = db.get(Movie, movie_id)
            assert stored.overview is None
            assert stored.rating == 8.4
    finally:
        engine.dispose()
