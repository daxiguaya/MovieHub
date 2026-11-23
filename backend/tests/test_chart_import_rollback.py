"""Failure-path tests for transactional chart snapshot imports."""

from datetime import datetime

import pytest
from sqlalchemy import create_engine, event, select, func
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.database import Base, Chart, ChartItem, ChartSnapshot, Movie
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


def test_failed_reimport_rolls_back_chart_movie_and_snapshot_changes():
    engine, db = _session()
    service = ChartImportService()
    try:
        chart = Chart(
            slug="rollback-chart",
            name="Original chart name",
            source="test",
            category="general",
            enabled=True,
            display_order=7,
            created_at=datetime(2026, 1, 1),
            updated_at=datetime(2026, 1, 1),
        )
        movie = Movie(
            douban_id="10001",
            title="Original movie",
            type="movie",
            rating_count=0,
            directors="[]",
            actors="[]",
        )
        db.add_all([chart, movie])
        db.flush()

        snapshot = ChartSnapshot(
            list_id=chart.list_id,
            snapshot_date="2026-11-23",
            imported_at=datetime(2026, 11, 23),
            item_count=1,
        )
        db.add(snapshot)
        db.flush()
        db.add(
            ChartItem(
                snapshot_id=snapshot.id,
                movie_id=movie.id,
                rank=1,
                source_rating=8.5,
            )
        )
        db.commit()

        invalid_payload = {
            "slug": "rollback-chart",
            "name": "Changed name must roll back",
            "source": "changed-source",
            "category": "changed-category",
            "snapshot_date": "2026-11-23",
            "movies": [
                {
                    "douban_id": "10002",
                    "title": "New movie A",
                    "rank": 1,
                },
                {
                    "douban_id": "10003",
                    "title": "New movie B",
                    "rank": 1,
                },
            ],
        }

        with pytest.raises(ChartImportError):
            service.import_snapshot(db, invalid_payload)

        db.expire_all()
        current_chart = db.scalar(
            select(Chart).where(Chart.slug == "rollback-chart")
        )
        assert current_chart.name == "Original chart name"
        assert current_chart.source == "test"
        assert current_chart.category == "general"
        assert current_chart.display_order == 7

        snapshots = db.scalars(
            select(ChartSnapshot).where(
                ChartSnapshot.list_id == current_chart.list_id
            )
        ).all()
        assert len(snapshots) == 1
        assert snapshots[0].snapshot_date == "2026-11-23"
        assert snapshots[0].item_count == 1

        existing_item = db.scalar(
            select(ChartItem).where(
                ChartItem.snapshot_id == snapshots[0].id
            )
        )
        assert existing_item.rank == 1
        assert existing_item.movie.douban_id == "10001"
        assert db.scalar(
            select(func.count()).select_from(Movie)
        ) == 1
    finally:
        db.close()
        engine.dispose()
