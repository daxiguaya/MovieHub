"""Rank comparison tests for dated chart snapshots."""

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.database as database
import app.main as main_module
from app.database import Chart, ChartItem, ChartSnapshot, Movie
from app.services.chart_service import chart_service


def _seed_chart_comparison(TargetSession):
    with TargetSession() as db:
        chart = Chart(
            slug="compare-fixture",
            name="Compare Fixture",
            source="test",
            category="classic",
            enabled=True,
            display_order=1,
        )
        movies = [
            Movie(douban_id="1001", title="A Movie", type="movie"),
            Movie(douban_id="1002", title="B Movie", type="movie"),
            Movie(douban_id="1003", title="C Movie", type="movie"),
            Movie(douban_id="1004", title="D Movie", type="movie"),
        ]
        db.add(chart)
        db.add_all(movies)
        db.flush()

        before = ChartSnapshot(
            list_id=chart.list_id,
            snapshot_date="2026-11-22",
            item_count=3,
        )
        after = ChartSnapshot(
            list_id=chart.list_id,
            snapshot_date="2026-11-23",
            item_count=3,
        )
        db.add_all([before, after])
        db.flush()

        db.add_all([
            ChartItem(snapshot_id=before.id, movie_id=movies[0].id, rank=1),
            ChartItem(snapshot_id=before.id, movie_id=movies[1].id, rank=2),
            ChartItem(snapshot_id=before.id, movie_id=movies[2].id, rank=3),
            ChartItem(snapshot_id=after.id, movie_id=movies[1].id, rank=1),
            ChartItem(snapshot_id=after.id, movie_id=movies[0].id, rank=2),
            ChartItem(snapshot_id=after.id, movie_id=movies[3].id, rank=3),
        ])
        db.commit()


def test_chart_comparison_reports_rises_drops_new_and_removed(tmp_path):
    db_path = tmp_path / "chart-compare.sqlite"
    engine = create_engine(
        f"sqlite:///{db_path.as_posix()}",
        connect_args={"check_same_thread": False},
    )
    database.Base.metadata.create_all(engine)
    TargetSession = sessionmaker(bind=engine, expire_on_commit=False)
    _seed_chart_comparison(TargetSession)

    try:
        with TargetSession() as db:
            result = chart_service.compare_snapshots(
                db,
                "compare-fixture",
                "2026-11-22",
                "2026-11-23",
            )

        by_title = {item.title: item for item in result.items}
        assert result.total_before == 3
        assert result.total_after == 3
        assert by_title["A Movie"].status == "moved"
        assert by_title["A Movie"].rank_change == -1
        assert by_title["B Movie"].status == "moved"
        assert by_title["B Movie"].rank_change == 1
        assert by_title["C Movie"].status == "removed"
        assert by_title["C Movie"].before_rank == 3
        assert by_title["C Movie"].after_rank is None
        assert by_title["D Movie"].status == "new"
        assert by_title["D Movie"].before_rank is None
        assert by_title["D Movie"].after_rank == 3
    finally:
        engine.dispose()


def test_chart_comparison_endpoint_validates_dates_and_returns_changes(
    tmp_path,
    monkeypatch,
):
    db_path = tmp_path / "chart-compare-api.sqlite"
    engine = create_engine(
        f"sqlite:///{db_path.as_posix()}",
        connect_args={"check_same_thread": False},
    )
    database.Base.metadata.create_all(engine)
    TargetSession = sessionmaker(bind=engine, expire_on_commit=False)
    _seed_chart_comparison(TargetSession)
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
            response = client.get(
                "/api/charts/compare-fixture/compare",
                params={
                    "from_date": "2026-11-22",
                    "to_date": "2026-11-23",
                },
            )
            same_date = client.get(
                "/api/charts/compare-fixture/compare",
                params={
                    "from_date": "2026-11-23",
                    "to_date": "2026-11-23",
                },
            )
            missing_date = client.get(
                "/api/charts/compare-fixture/compare",
                params={
                    "from_date": "2026-11-21",
                    "to_date": "2026-11-23",
                },
            )

        assert response.status_code == 200
        assert response.json()["items"][0]["after_rank"] == 1
        assert same_date.status_code == 400
        assert missing_date.status_code == 404
    finally:
        engine.dispose()
