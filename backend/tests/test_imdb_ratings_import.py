"""Tests for exact-ID, streaming IMDb ratings ingestion."""
import csv
import gzip
from pathlib import Path

import pytest

from scripts.import_imdb_ratings import iter_matching_ratings


def _write_ratings(path: Path, rows: list[tuple[str, str, str]]):
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "wt", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, delimiter="\\t")
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
    source.write_text("id\\taverageRating\\n", encoding="utf-8")
    with pytest.raises(ValueError, match="must contain"):
        list(iter_matching_ratings(source, {"tt0111161"}))
