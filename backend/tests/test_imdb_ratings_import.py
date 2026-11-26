"""Tests for exact-ID, streaming IMDb ratings ingestion."""
import csv
import gzip
from pathlib import Path

import pytest

from scripts.import_imdb_ratings import iter_matching_ratings


def _write_ratings(path: Path, rows: list[tuple[str, str, str]]):
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "wt", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t")
        writer.writerow(["tconst", "averageRating", "numVotes"])
        writer.writerows(rows)


def test_streams_only_exact_requested_imdb_ids(tmp_path):
    source = tmp_path / "title.ratings.tsv.gz"
    _write_ratings(source, [
        ("tt0111161", "9.3", "3000000"),
        ("tt0068646", "9.2", "2000000"),
        ("tt0000001", "5.6", "100"),
    ])
    assert list(iter_matching_ratings(source, {"tt0111161", "tt0000001"})) == [
        ("tt0111161", 9.3, 3000000),
        ("tt0000001", 5.6, 100),
    ]


def test_rejects_duplicate_matching_id(tmp_path):
    source = tmp_path / "ratings.tsv"
    _write_ratings(source, [
        ("tt0111161", "9.3", "3000000"),
        ("tt0111161", "9.2", "2999999"),
    ])
    with pytest.raises(ValueError, match="Duplicate"):
        list(iter_matching_ratings(source, {"tt0111161"}))


@pytest.mark.parametrize("rating,votes", [("10.1", "10"), ("7.0", "-1"), ("bad", "10")])
def test_rejects_invalid_matching_rating_rows(tmp_path, rating, votes):
    source = tmp_path / "ratings.tsv"
    _write_ratings(source, [("tt0111161", rating, votes)])
    with pytest.raises(ValueError):
        list(iter_matching_ratings(source, {"tt0111161"}))


def test_requires_official_dataset_columns(tmp_path):
    source = tmp_path / "ratings.tsv"
    source.write_text("id\taverageRating\\n", encoding="utf-8")
    with pytest.raises(ValueError, match="must contain"):
        list(iter_matching_ratings(source, {"tt0111161"}))

def test_apply_updates_only_imdb_fields_and_keeps_douban_data(tmp_path):
    import sqlite3
    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import Session

    from app.database import Base, Movie, MovieMetadataProvenance
    from scripts.import_imdb_ratings import import_imdb_ratings

    database_path = tmp_path / "movies.db"
    engine = create_engine(f"sqlite:///{database_path}")
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY, name TEXT NOT NULL, applied_at TEXT NOT NULL)"
        )
        connection.exec_driver_sql(
            "INSERT INTO schema_migrations VALUES (5, 'imdb_ratings', '2026-11-26')"
        )
    with Session(engine) as db:
        db.add(Movie(
            douban_id="1292052",
            imdb_id="tt0111161",
            tmdb_id="278",
            title="肖申克的救赎",
            type="movie",
            rating=9.7,
            rating_count=2500000,
        ))
        db.commit()
    engine.dispose()

    source = tmp_path / "title.ratings.tsv.gz"
    _write_ratings(source, [("tt0111161", "9.3", "3000000")])

    dry_run = import_imdb_ratings(source, database_path=database_path)
    assert dry_run["applied"] is False
    assert dry_run["matched"] == 1

    applied = import_imdb_ratings(source, database_path=database_path, apply=True)
    assert applied["applied"] is True
    assert applied["updated"] == 1
    assert Path(applied["backup"]).is_file()

    engine = create_engine(f"sqlite:///{database_path}")
    with Session(engine) as db:
        movie = db.scalar(select(Movie).where(Movie.imdb_id == "tt0111161"))
        assert movie.imdb_rating == 9.3
        assert movie.imdb_rating_count == 3000000
        assert movie.rating == 9.7
        assert movie.rating_count == 2500000
        provenance = db.scalars(select(MovieMetadataProvenance).where(
            MovieMetadataProvenance.source == "imdb"
        )).all()
        assert {item.field_name for item in provenance} == {
            "imdb_rating", "imdb_rating_count"
        }
    engine.dispose()

    check = sqlite3.connect(str(database_path))
    try:
        assert check.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    finally:
        check.close()
