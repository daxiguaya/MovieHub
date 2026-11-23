"""Tests for the normalized local chart import command."""

import json

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

import scripts.import_chart as import_chart
import app.services.chart_import_service as chart_import_service_module
from app.database import Base, Chart, ChartSnapshot, Movie


def _write_snapshot(path):
    path.write_text(
        json.dumps(
            {
                "slug": "cli-chart",
                "name": "CLI Chart",
                "source": "ignored-input-source",
                "category": "test",
                "snapshot_date": "2026-11-23",
                "movies": [
                    {
                        "douban_id": "123456",
                        "rank": 1,
                        "title": "CLI Fixture Movie",
                        "rating": 8.1,
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def test_chart_import_cli_dry_run_validates_without_database_access(tmp_path, monkeypatch):
    source = tmp_path / "chart.json"
    _write_snapshot(source)

    def unexpected_database_check():
        raise AssertionError("dry-run must not inspect or write the database")

    monkeypatch.setattr(import_chart, "database_is_ready", unexpected_database_check)

    result = import_chart.import_snapshot(source, dry_run=True)

    assert result == {
        "valid": True,
        "slug": "cli-chart",
        "snapshot_date": "2026-11-23",
        "item_count": 1,
        "source": "local",
    }


def test_chart_import_cli_writes_only_to_moviehub_session(tmp_path, monkeypatch):
    source = tmp_path / "chart.json"
    _write_snapshot(source)

    engine = create_engine(f"sqlite:///{(tmp_path / 'moviehub.db').as_posix()}")
    Base.metadata.create_all(engine)
    TargetSession = sessionmaker(
        bind=engine,
        autoflush=False,
        expire_on_commit=False,
    )
    monkeypatch.setattr(import_chart, "database_is_ready", lambda: True)
    monkeypatch.setattr(import_chart, "SessionLocal", TargetSession)
    monkeypatch.setattr(
        chart_import_service_module.cache_manager,
        "clear",
        lambda: None,
    )

    try:
        result = import_chart.import_snapshot(source)

        assert result["success"] is True
        assert result["slug"] == "cli-chart"
        assert result["imported_count"] == 1

        with TargetSession() as db:
            chart = db.scalar(select(Chart).where(Chart.slug == "cli-chart"))
            snapshot = db.scalar(select(ChartSnapshot))
            movie = db.scalar(select(Movie).where(Movie.douban_id == "123456"))
            assert chart.source == "local"
            assert snapshot.item_count == 1
            assert movie.title == "CLI Fixture Movie"
    finally:
        engine.dispose()
