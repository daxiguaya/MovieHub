"""Tests for safe TMDB external-ID to IMDb title-ID mapping."""
from scripts.backfill_tmdb_imdb_ids import (
    classify_duplicates,
    valid_external_id,
)


def test_valid_external_id_requires_matching_tmdb_identity():
    assert valid_external_id({"id": 278, "imdb_id": "tt0111161"}, "278") == "tt0111161"
    assert valid_external_id({"id": 279, "imdb_id": "tt0111161"}, "278") is None


def test_valid_external_id_rejects_malformed_or_missing_ids():
    assert valid_external_id({"id": 278, "imdb_id": "not-an-imdb-id"}, "278") is None
    assert valid_external_id({"id": 278, "imdb_id": None}, "278") is None
    assert valid_external_id({"imdb_id": "tt0111161"}, "278") is None
    assert valid_external_id([], "278") is None


def test_duplicate_imdb_ids_are_rejected_for_all_candidates():
    rows = [
        {"movie_id": 1, "imdb_id": "tt0111161", "status": "candidate"},
        {"movie_id": 2, "imdb_id": "tt0111161", "status": "candidate"},
    ]
    result = classify_duplicates(rows, {})
    assert [row["status"] for row in result] == [
        "duplicate_conflict",
        "duplicate_conflict",
    ]
    assert all("imdb_id" not in row for row in result)


def test_existing_imdb_owner_conflict_is_rejected():
    rows = [
        {"movie_id": 2, "imdb_id": "tt0111161", "status": "candidate"},
    ]
    result = classify_duplicates(rows, {"tt0111161": 1})
    assert result[0]["status"] == "duplicate_conflict"
