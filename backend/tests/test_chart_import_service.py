"""Behavioral tests for chart snapshot import and metadata precedence."""

from datetime import date

import pytest
from sqlalchemy import create_engine, event, select, func
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.database import (
    Base, Chart, ChartSnapshot, ChartItem, Movie, MovieMetadataProvenance,
    Genre, Region, MovieGenre, MovieRegion,
)
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

@pytest.mark.parametrize(
    ("rank_values", "error_match"),
    [
        ([1, 1], "duplicate ranks"),
        ([True], "invalid rank"),
        ([1.5], "invalid rank"),
    ],
)
def test_chart_import_rejects_invalid_or_duplicate_raw_ranks_before_writes(
    rank_values,
    error_match,
):
    engine, db = _session()
    service = ChartImportService()
    try:
        raw_snapshot = {
            "slug": "raw-rank-chart",
            "name": "Raw rank chart",
            "source": "test",
            "category": "general",
            "snapshot_date": "2026-11-23",
            "movies": [
                {
                    "douban_id": str(30001 + index),
                    "rank": rank,
                    "title": f"Raw movie {index}",
                    "type": "movie",
                }
                for index, rank in enumerate(rank_values)
            ],
        }

        with pytest.raises(ChartImportError, match=error_match):
            service.import_snapshot(db, raw_snapshot)

        # Rejected payloads must not create chart, movie or snapshot rows.
        assert db.scalar(select(func.count()).select_from(Movie)) == 0
        assert db.scalar(select(func.count()).select_from(ChartSnapshot)) == 0
    finally:
        db.close()
        engine.dispose()

def test_chart_import_discards_non_finite_raw_ratings():
    engine, db = _session()
    service = ChartImportService()
    try:
        raw_snapshot = {
            "slug": "nonfinite-rating-chart",
            "name": "Non-finite rating chart",
            "source": "test",
            "category": "general",
            "snapshot_date": "2026-11-23",
            "movies": [
                {
                    "douban_id": "40001",
                    "rank": 1,
                    "title": "Rating edge case",
                    "rating": float("nan"),
                    "source_rating": float("inf"),
                }
            ],
        }

        service.import_snapshot(db, raw_snapshot)

        movie = db.scalar(select(Movie).where(Movie.douban_id == "40001"))
        chart_item = db.scalar(select(ChartItem))
        assert movie is not None
        assert movie.rating is None
        assert chart_item is not None
        assert chart_item.source_rating is None
    finally:
        db.close()
        engine.dispose()



@pytest.mark.parametrize("invalid_year", [1800, 2201, -1])
def test_chart_import_rejects_out_of_range_raw_years(invalid_year):
    engine, db = _session()
    service = ChartImportService()
    try:
        raw_snapshot = {
            "slug": "raw-year-chart",
            "name": "Raw year chart",
            "source": "test",
            "category": "general",
            "snapshot_date": "2026-11-23",
            "movies": [
                {
                    "douban_id": "50001",
                    "rank": 1,
                    "title": "Out of range year",
                    "year": invalid_year,
                    "type": "movie",
                }
            ],
        }

        service.import_snapshot(db, raw_snapshot)

        movie = db.scalar(select(Movie).where(Movie.douban_id == "50001"))
        assert movie is not None
        assert movie.year is None
    finally:
        db.close()
        engine.dispose()


def test_chart_import_preserves_existing_year_when_raw_year_is_invalid():
    engine, db = _session()
    service = ChartImportService()
    try:
        movie = Movie(
            douban_id="50002",
            title="Scout-owned title",
            year=1998,
            type="movie",
            rating_count=0,
            directors="[]",
            actors="[]",
        )
        db.add(movie)
        db.commit()

        raw_snapshot = {
            "slug": "existing-raw-year-chart",
            "name": "Existing raw year chart",
            "source": "test",
            "category": "general",
            "snapshot_date": "2026-11-23",
            "movies": [
                {
                    "douban_id": "50002",
                    "rank": 1,
                    "title": "Chart title",
                    "year": 1800,
                    "type": "movie",
                }
            ],
        }

        service.import_snapshot(db, raw_snapshot)

        stored = db.scalar(select(Movie).where(Movie.douban_id == "50002"))
        assert stored.year == 1998
        assert stored.title == "Scout-owned title"
    finally:
        db.close()
        engine.dispose()


def test_multi_chart_import_rolls_back_every_snapshot_when_one_fails():
    engine, db = _session()
    service = ChartImportService()
    try:
        existing = Movie(
            douban_id="90002",
            title="Existing movie",
            type="movie",
            rating_count=0,
            directors="[]",
            actors="[]",
        )
        db.add(existing)
        db.commit()

        first = ChartSnapshotImport(
            slug="batch-first",
            name="Batch first",
            source="test",
            category="annual",
            period="2025",
            snapshot_date=date(2026, 11, 23),
            movies=[
                ChartMovieImport(
                    douban_id="90001",
                    rank=1,
                    title="Must roll back",
                    type="movie",
                )
            ],
        )
        second = ChartSnapshotImport(
            slug="batch-second",
            name="Batch second",
            source="test",
            category="annual",
            period="2025",
            snapshot_date=date(2026, 11, 23),
            movies=[
                ChartMovieImport(
                    douban_id="90002",
                    rank=1,
                    title="Conflicting TV label",
                    type="tv",
                )
            ],
        )

        with pytest.raises(ChartImportError, match="media type mismatch"):
            service.import_snapshots(db, [first, second])

        db.expire_all()
        assert db.scalar(select(func.count()).select_from(ChartSnapshot)) == 0
        assert db.scalar(select(func.count()).select_from(ChartItem)) == 0
        assert db.scalar(select(func.count()).select_from(Chart)) == 0
        assert db.scalar(
            select(func.count()).select_from(Movie).where(
                Movie.douban_id == "90001"
            )
        ) == 0
        preserved = db.scalar(
            select(Movie).where(Movie.douban_id == "90002")
        )
        assert preserved.type == "movie"
        assert preserved.title == "Existing movie"
    finally:
        db.close()
        engine.dispose()


def test_multi_chart_import_rejects_duplicate_chart_date_pairs():
    engine, db = _session()
    service = ChartImportService()
    try:
        one = _snapshot(
            date(2026, 11, 23),
            [ChartMovieImport(douban_id="91001", rank=1, title="One")],
        )
        two = _snapshot(
            date(2026, 11, 23),
            [ChartMovieImport(douban_id="91002", rank=1, title="Two")],
        )
        with pytest.raises(ChartImportError, match="duplicate chart/date"):
            service.import_snapshots(db, [one, two])
        assert db.scalar(select(func.count()).select_from(Chart)) == 0
    finally:
        db.close()
        engine.dispose()


def test_new_movie_metadata_associations_receive_generated_movie_id():
    engine, db = _session()
    service = ChartImportService()
    try:
        snapshot = _snapshot(
            date(2026, 11, 24),
            [
                ChartMovieImport(
                    douban_id="120001",
                    rank=1,
                    title="New movie with metadata",
                    genres=["Drama", "Thriller"],
                    regions=["China"],
                )
            ],
        )
        service.import_snapshot(db, snapshot)

        movie = db.scalar(select(Movie).where(Movie.douban_id == "120001"))
        assert movie is not None and movie.id is not None
        genre_names = set(db.scalars(
            select(Genre.name)
            .join(MovieGenre, MovieGenre.genre_id == Genre.id)
            .where(MovieGenre.movie_id == movie.id)
        ).all())
        region_names = set(db.scalars(
            select(Region.name)
            .join(MovieRegion, MovieRegion.region_id == Region.id)
            .where(MovieRegion.movie_id == movie.id)
        ).all())
        assert genre_names == {"Drama", "Thriller"}
        assert region_names == {"China"}
    finally:
        db.close()
        engine.dispose()


def test_chart_import_records_field_level_source_provenance_idempotently():
    engine, db = _session()
    service = ChartImportService()
    try:
        snapshot = _snapshot(
            date(2026, 11, 24),
            [
                ChartMovieImport(
                    douban_id="120101",
                    rank=1,
                    title="Provenance fixture",
                    original_title="Source title",
                    year=2020,
                    rating=8.2,
                    rating_count=12345,
                    directors=["Director A"],
                    actors=["Actor A"],
                    overview="Source synopsis",
                    douban_url="https://movie.douban.com/subject/120101/",
                )
            ],
        )
        service.import_snapshot(db, snapshot)
        db.commit()

        movie = db.scalar(
            select(Movie).where(Movie.douban_id == "120101")
        )
        records = db.scalars(
            select(MovieMetadataProvenance).where(
                MovieMetadataProvenance.movie_id == movie.id
            )
        ).all()
        by_field = {record.field_name: record for record in records}

        assert set(by_field) == {
            "original_title", "year", "rating", "rating_count",
            "directors", "actors", "overview",
        }
        assert all(record.source == "test" for record in records)
        assert all(
            record.source_url == "https://movie.douban.com/subject/120101/"
            for record in records
        )
        assert all(record.observed_at is not None for record in records)
        assert all(len(record.value_sha256) == 64 for record in records)

        db.commit()
        service.import_snapshot(db, snapshot)
        db.commit()
        assert db.scalar(
            select(func.count()).select_from(MovieMetadataProvenance)
        ) == 7
    finally:
        db.close()
        engine.dispose()



def test_chart_import_validates_imdb_ids_and_ignores_invalid_raw_values():
    engine, db = _session()
    service = ChartImportService()
    try:
        with pytest.raises(ValueError, match="canonical IMDb title ID"):
            ChartMovieImport(
                douban_id="130001",
                rank=1,
                title="Invalid IMDb identity",
                imdb_id="tt12x4567",
            )

        raw_snapshot = {
            "slug": "raw-invalid-imdb-chart",
            "name": "Raw invalid IMDb chart",
            "source": "test",
            "category": "general",
            "snapshot_date": "2026-11-26",
            "movies": [
                {
                    "douban_id": "130002",
                    "rank": 1,
                    "title": "Raw mapping with invalid IMDb ID",
                    "type": "movie",
                    "imdb_id": "tt12x4567",
                }
            ],
        }
        service.import_snapshot(db, raw_snapshot)
        movie = db.scalar(select(Movie).where(Movie.douban_id == "130002"))
        assert movie is not None
        assert movie.imdb_id is None
    finally:
        db.close()
        engine.dispose()
