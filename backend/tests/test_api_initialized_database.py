"""Data API smoke tests with an explicitly initialized temporary database."""

from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker
from app.database import Movie

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
        assert readiness_response.json() == {"status": "ready", "schema_version": 1}
    finally:
        engine.dispose()
