"""Tests for the complete, separately stored IMDb rating index."""
import csv
import sqlite3
from pathlib import Path

import pytest

from scripts.import_imdb_rating_index import import_imdb_rating_index


def _write_tsv(path: Path, rows):
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t")
        writer.writerow(["tconst", "averageRating", "numVotes"])
        writer.writerows(rows)


def test_full_index_dry_run_then_atomic_apply(tmp_path):
    source = tmp_path / "title.ratings.tsv"
    target = tmp_path / "imdb-ratings.sqlite3"
    _write_tsv(source, [
        ("tt0111161", "9.3", "3000000"),
        ("tt0068646", "9.2", "2000000"),
        ("tt1234567", "8.4", "12345"),
    ])
    preview = import_imdb_rating_index(source, database_path=target, min_rows=3)
    assert preview["valid"] is True
    assert preview["indexed_titles"] == 3
    assert target.exists() is False

    applied = import_imdb_rating_index(source, database_path=target, apply=True, min_rows=3)
    assert applied["applied"] is True
    connection = sqlite3.connect(target)
    try:
        assert connection.execute("SELECT rating, vote_count FROM ratings WHERE imdb_id='tt1234567'").fetchone() == (8.4, 12345)
        assert connection.execute("SELECT COUNT(*) FROM ratings").fetchone()[0] == 3
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    finally:
        connection.close()


def test_full_index_rejects_duplicate_ids_and_low_row_count(tmp_path):
    source = tmp_path / "ratings.tsv"
    _write_tsv(source, [("tt0111161", "9.3", "10"), ("tt0111161", "9.2", "9")])
    with pytest.raises(ValueError, match="Duplicate"):
        import_imdb_rating_index(source, database_path=tmp_path / "index.db", min_rows=1)
    _write_tsv(source, [("tt0111161", "9.3", "10")])
    with pytest.raises(ValueError, match="below minimum"):
        import_imdb_rating_index(source, database_path=tmp_path / "index.db", min_rows=2)


@pytest.mark.parametrize("rating,votes", [("10.1", "1"), ("8.0", "-1"), ("bad", "1")])
def test_full_index_rejects_invalid_rating_rows(tmp_path, rating, votes):
    source = tmp_path / "ratings.tsv"
    _write_tsv(source, [("tt0111161", rating, votes)])
    with pytest.raises(ValueError):
        import_imdb_rating_index(source, database_path=tmp_path / "index.db", min_rows=1)
