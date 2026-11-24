"""Regression tests for chart snapshot queries and cursor pagination."""

from datetime import datetime

import pytest
import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.database import Base, Chart, ChartItem, ChartSnapshot, Movie
from app.services.chart_service import ChartCursorError, ChartService


def _database():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(connection, record):
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    return engine, Session(engine, expire_on_commit=False)


def _seed_chart(db: Session) -> None:
    chart = Chart(
        slug="test-chart",
        name="Test chart",
        source="test",
        category="general",
        enabled=True,
        display_order=1,
        created_at=datetime(2026, 1, 1),
        updated_at=datetime(2026, 1, 1),
    )
    db.add(chart)
    db.flush()

    for day, first_id in (("2026-11-22", 1), ("2026-11-23", 4)):
        snapshot = ChartSnapshot(
            list_id=chart.list_id,
            snapshot_date=day,
            imported_at=datetime.fromisoformat(day),
            item_count=3,
        )
        db.add(snapshot)
        db.flush()

        for offset in range(3):
            movie_id = first_id + offset
            movie = Movie(
                id=movie_id,
                douban_id=str(10000 + movie_id),
                title=f"Movie {movie_id}",
                type="movie",
                rating_count=0,
                directors="[]",
                actors="[]",
            )
            db.add(movie)
            db.flush()
            db.add(
                ChartItem(
                    snapshot_id=snapshot.id,
                    movie_id=movie.id,
                    rank=offset + 1,
                    source_rating=8.0 + offset / 10,
                )
            )

    db.commit()


def test_default_query_uses_latest_snapshot_and_paginates_by_rank():
    engine, db = _database()
    service = ChartService()
    try:
        _seed_chart(db)

        first_page = service.get_chart_movies(
            db, "test-chart", limit=2
        )
        assert first_page is not None
        assert first_page.total == 3
        assert [item.title for item in first_page.items] == [
            "Movie 4", "Movie 5"
        ]
        assert [item.rank for item in first_page.items] == [1, 2]
        assert first_page.items[0].snapshot_date == "2026-11-23"
        assert first_page.next_cursor == service._encode_cursor(2)

        second_page = service.get_chart_movies(
            db,
            "test-chart",
            cursor=first_page.next_cursor,
            limit=2,
        )
        assert second_page is not None
        assert [item.title for item in second_page.items] == ["Movie 6"]
        assert [item.rank for item in second_page.items] == [3]
        assert second_page.next_cursor is None
    finally:
        db.close()
        engine.dispose()


def test_explicit_snapshot_date_returns_historical_snapshot():
    engine, db = _database()
    service = ChartService()
    try:
        _seed_chart(db)

        result = service.get_chart_movies(
            db, "test-chart", snapshot_date="2026-11-22"
        )

        assert result is not None
        assert result.total == 3
        assert [item.title for item in result.items] == [
            "Movie 1", "Movie 2", "Movie 3"
        ]
        assert {item.snapshot_date for item in result.items} == {
            "2026-11-22"
        }
    finally:
        db.close()
        engine.dispose()


def test_invalid_cursor_is_rejected_and_missing_snapshot_is_empty():
    engine, db = _database()
    service = ChartService()
    try:
        _seed_chart(db)

        with pytest.raises(ChartCursorError, match="Invalid chart pagination cursor"):
            service.get_chart_movies(
                db, "test-chart", cursor="not-a-valid-cursor", limit=1
            )
        missing_snapshot = service.get_chart_movies(
            db, "test-chart", snapshot_date="2020-01-01"
        )
        assert missing_snapshot is not None
        assert missing_snapshot.items == []
        assert missing_snapshot.total == 0
        assert missing_snapshot.next_cursor is None
    finally:
        db.close()
        engine.dispose()


def test_disabled_or_unknown_chart_is_not_returned():
    engine, db = _database()
    service = ChartService()
    try:
        _seed_chart(db)
        chart = db.query(Chart).filter_by(slug="test-chart").one()
        chart.enabled = False
        db.commit()

        assert service.get_chart(db, "test-chart") is None
        assert service.get_chart_movies(db, "test-chart") is None
        assert service.get_chart(db, "unknown-chart") is None
    finally:
        db.close()
        engine.dispose()
