"""Chart import and history APIs against a temporary MovieHub database."""

from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

import app.database as database
import app.main as main_module
from app.config import settings
from scripts.init_db import initialize


def _snapshot(day, movie_ids):
    return {
        "slug": "api-fixture-chart",
        "name": "API Fixture Chart",
        "source": "fixture",
        "category": "test",
        "snapshot_date": day,
        "movies": [
            {
                "douban_id": movie_id,
                "rank": index,
                "title": f"Fixture Movie {movie_id}",
                "rating": 8.0,
                "source_rating": 7.5,
            }
            for index, movie_id in enumerate(movie_ids, start=1)
        ],
    }


def test_chart_import_and_history_apis_preserve_date_scoped_snapshots(
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

    monkeypatch.setattr(database, "get_db_path", lambda: str(db_path))
    monkeypatch.setattr(database, "SessionLocal", TargetSession)
    monkeypatch.setattr(main_module, "get_db_path", lambda: str(db_path))
    monkeypatch.setattr(settings, "api_key", "chart-test-key")
    monkeypatch.setattr(
        main_module.poster_cache_service,
        "clear_expired_cache",
        lambda: None,
    )

    headers = {"X-API-Key": "chart-test-key"}

    try:
        with TestClient(main_module.app) as client:
            first = client.post(
                "/api/charts/import",
                headers=headers,
                json=_snapshot("2026-11-23", ["10001", "10002"]),
            )
            replacement = client.post(
                "/api/charts/import",
                headers=headers,
                json=_snapshot("2026-11-23", ["10003"]),
            )
            next_day = client.post(
                "/api/charts/import",
                headers=headers,
                json=_snapshot("2026-11-24", ["10004", "10005", "10006"]),
            )

            history = client.get("/api/charts/api-fixture-chart/snapshots")
            historical = client.get(
                "/api/charts/api-fixture-chart",
                params={"snapshot_date": "2026-11-23"},
            )
            latest = client.get(
                "/api/charts/api-fixture-chart",
                params={"limit": 2},
            )
            latest_second_page = client.get(
                "/api/charts/api-fixture-chart",
                params={
                    "limit": 2,
                    "cursor": latest.json()["next_cursor"],
                },
            )
            historical_page = client.get(
                "/api/charts/api-fixture-chart",
                params={"snapshot_date": "2026-11-23", "limit": 1},
            )
            invalid_cursor = client.get(
                "/api/charts/api-fixture-chart",
                params={"cursor": "not-a-valid-cursor"},
            )

        assert first.status_code == 200
        assert first.json()["imported_count"] == 2
        assert replacement.status_code == 200
        assert replacement.json()["imported_count"] == 1
        assert next_day.status_code == 200
        assert next_day.json()["imported_count"] == 3

        assert history.status_code == 200
        assert [item["snapshot_date"] for item in history.json()] == [
            "2026-11-24",
            "2026-11-23",
        ]

        assert historical.status_code == 200
        assert historical.json()["total"] == 1
        assert historical.json()["items"][0]["douban_id"] == "10003"

        assert latest.status_code == 200
        assert latest.json()["total"] == 3
        assert [item["douban_id"] for item in latest.json()["items"]] == ["10004", "10005"]
        assert latest.json()["next_cursor"]
        assert latest_second_page.status_code == 200
        assert [item["douban_id"] for item in latest_second_page.json()["items"]] == ["10006"]
        assert latest_second_page.json()["next_cursor"] is None
        assert historical_page.status_code == 200
        assert historical_page.json()["total"] == 1
        assert historical_page.json()["items"][0]["douban_id"] == "10003"
        assert invalid_cursor.status_code == 400
        assert invalid_cursor.json()["detail"] == "Invalid chart pagination cursor"
    finally:
        engine.dispose()
