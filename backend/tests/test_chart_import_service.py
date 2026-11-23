"""Behavioral tests for chart snapshot import and metadata precedence."""

from datetime import date

import pytest
from sqlalchemy import create_engine, event, select, func
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.database import Base, ChartSnapshot, ChartItem, Movie
from app.schemas_chart_import import ChartMovieImport, ChartSnapshotImport
from app.services.chart_import_service import ChartImportError, ChartImportService


def _session():
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


def _snapshot(day, movies):
    return ChartSnapshotImport(
        slug="test-chart",
        name="Test chart",
        source="test",
        category="general",
        snapshot_date=day,
        movies=movies,
    )


def test_chart_import_replaces_only_the_requested_date_and_preserves_scout_data():
    engine, db = _session()
    service = ChartImportService()
    try:
        scout_movie = Movie(
            douban_id="10001",
            title="Scout title",
            year=2010,
            rating=9.1,
            rating_count=1000,
            type="movie",
            directors="[]",
            actors="[]",
        )
        db.add(scout_movie)
        db.commit()

        first = _snapshot(
            date(2026, 11, 23),
            [
                ChartMovieImport(
                    douban_id="10001",
                    rank=1,
                    title="Chart title must not replace Scout",
                    year=2001,
                    rating=6.2,
                    directors=["Director A"],
                    actors=["Actor A"],
                    genres=["Drama"],
                ),
                ChartMovieImport(
                    douban_id="10002",
                    rank=2,
                    title="New chart movie",
                    rating=7.8,
                ),
            ],
        )
        service.import_snapshot(db, first)

        movie = db.scalar(
            select(Movie).where(Movie.douban_id == "10001")
        )
        assert movie.title == "Scout title"
        assert movie.year == 2010
        assert movie.rating == 9.1
        assert movie.directors == '["Director A"]'
        assert movie.actors == '["Actor A"]'

        original_snapshot = db.scalar(
            select(ChartSnapshot).where(
                ChartSnapshot.snapshot_date == "2026-11-23"
            )
        )
        assert original_snapshot.item_count == 2
        original_snapshot_id = original_snapshot.id

        # End the read transaction before invoking the importer again;
        # the importer intentionally owns a fresh transaction per call.
        db.commit()

        # Re-importing the same date replaces its complete contents.
        replacement = _snapshot(
            date(2026, 11, 23),
            [
                ChartMovieImport(
                    douban_id="10003",
                    rank=1,
                    title="Replacement movie",
                )
            ],
        )
        service.import_snapshot(db, replacement)

        snapshots = db.scalars(select(ChartSnapshot)).all()
        assert len(snapshots) == 1
        assert snapshots[0].snapshot_date == "2026-11-23"
        assert snapshots[0].item_count == 1
        # SQLite may reuse an INTEGER PRIMARY KEY after its previous row is deleted.
        assert db.scalar(
            select(func.count()).select_from(ChartItem)
        ) == 1
        current_movie = db.scalar(
            select(Movie).join(ChartItem, ChartItem.movie_id == Movie.id)
        )
        assert current_movie.douban_id == '10003'

        # A different date creates a second history record.
        db.commit()
        next_day = _snapshot(
            date(2026, 11, 24),
            [
                ChartMovieImport(
                    douban_id="10004",
                    rank=1,
                    title="Next day movie",
                )
            ],
        )
        service.import_snapshot(db, next_day)
        assert db.scalar(
            select(func.count()).select_from(ChartSnapshot)
        ) == 2
    finally:
        db.close()
        engine.dispose()



def test_chart_import_rejects_existing_movie_media_type_conflict_atomically():
    engine, db = _session()
    service = ChartImportService()
    try:
        existing = Movie(
            douban_id="20001",
            title="Existing Scout movie",
            type="movie",
            rating_count=0,
            directors="[]",
            actors="[]",
        )
        db.add(existing)
        db.commit()

        initial = _snapshot(
            date(2026, 11, 23),
            [
                ChartMovieImport(
                    douban_id="20001",
                    rank=1,
                    title="Existing Scout movie",
                    type="movie",
                )
            ],
        )
        service.import_snapshot(db, initial)
        db.commit()

        conflicting = _snapshot(
            date(2026, 11, 23),
            [
                ChartMovieImport(
                    douban_id="20001",
                    rank=1,
                    title="Same ID incorrectly labeled as TV",
                    type="tv",
                )
            ],
        )

        with pytest.raises(ChartImportError, match="media type mismatch"):
            service.import_snapshot(db, conflicting)

        db.commit()
        stored_movie = db.scalar(
            select(Movie).where(Movie.douban_id == "20001")
        )
        assert stored_movie.type == "movie"

        snapshots = db.scalars(select(ChartSnapshot)).all()
        assert len(snapshots) == 1
        assert snapshots[0].snapshot_date == "2026-11-23"
        assert snapshots[0].item_count == 1
        chart_item = db.scalar(select(ChartItem))
        assert chart_item is not None
        assert chart_item.movie_id == stored_movie.id
    finally:
        db.close()
        engine.dispose()
