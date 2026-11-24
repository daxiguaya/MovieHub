"""Poster completeness gates for built-in charts."""

from datetime import date

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.database import Base, Chart, ChartSnapshot, Movie
from app.schemas_chart_import import ChartSnapshotImport
from app.services.chart_import_service import ChartImportError, ChartImportService


def _payload(slug, posters):
    return {
        "slug": slug,
        "name": "Poster gate fixture",
        "source": "douban",
        "category": "annual" if slug.startswith("annual-") else "rating",
        "period": "2025" if slug.startswith("annual-") else None,
        "snapshot_date": date(2026, 11, 24),
        "movies": [
            {
                "douban_id": "987654321",
                "rank": 1,
                "title": "Poster gate fixture",
                "type": "movie",
                "posters": posters,
            }
        ],
    }


@pytest.mark.parametrize(
    "slug",
    [
        "annual-2025-chinese-movies",
        "annual-2025-international-movies",
        "annual-2025-hidden-gems",
    ],
)
def test_annual_movie_chart_schema_rejects_empty_posters(slug):
    with pytest.raises(ValidationError, match="requires at least one poster"):
        ChartSnapshotImport.model_validate(_payload(slug, []))


def test_annual_chart_schema_accepts_poster_and_nonrequired_chart_remains_optional():
    valid = ChartSnapshotImport.model_validate(
        _payload("annual-2025-chinese-movies", ["https://example.test/poster.jpg"])
    )
    assert valid.movies[0].posters

    optional = ChartSnapshotImport.model_validate(_payload("high-rated", []))
    assert optional.movies[0].posters == []


def test_import_service_rejects_raw_annual_payload_before_database_writes():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    db = Session(engine)
    try:
        raw = _payload("annual-2025-chinese-movies", [])
        raw["snapshot_date"] = "2026-11-24"

        with pytest.raises(ChartImportError, match="requires at least one poster"):
            ChartImportService().import_snapshot(db, raw)

        assert db.scalar(select(func.count()).select_from(Movie)) == 0
        assert db.scalar(select(func.count()).select_from(Chart)) == 0
        assert db.scalar(select(func.count()).select_from(ChartSnapshot)) == 0
    finally:
        db.close()
        engine.dispose()
