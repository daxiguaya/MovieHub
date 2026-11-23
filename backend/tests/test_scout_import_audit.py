"""Regression tests for the read-only whole-catalogue Scout audit."""

import hashlib
import json
import sqlite3

import pytest

from scripts.audit_scout_import import audit_scout_database, main


def _source(path):
    with sqlite3.connect(path) as db:
        db.execute(
            """CREATE TABLE item (
                douban_id TEXT, imdb_id TEXT, douban_title TEXT, year INTEGER,
                rating REAL, raw_data TEXT, type TEXT, update_time INTEGER
            )"""
        )
        db.executemany(
            "INSERT INTO item VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [
                ("10001", None, "Movie A", 2020, 8.5,
                 json.dumps({"detail": {
                     "rating": {"count": 123}, "summary": "Overview",
                     "original_title": "Original", "directors": [{"name": "Director"}],
                     "actors": [{"name": "Actor"}], "genres": ["Drama"],
                     "countries": ["Japan"], "pic": {"large": "https://img.test/a.jpg"}
                 }}), "movie", 1700000000),
                ("10002", None, "TV B", 2021, 7.0, "not-json", "tv", 1700000001),
            ],
        )
        db.commit()


def _hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_audit_reports_catalogue_coverage_and_anomalies_without_writes(tmp_path):
    source = tmp_path / "scout.sqlite"
    _source(source)
    with sqlite3.connect(source) as db:
        db.execute(
            "INSERT INTO item VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("bad-id", None, "Bad identity", 1800, 11.5, "[]", "movie", 1),
        )
        db.execute(
            "INSERT INTO item VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("10001", None, "Duplicate", 2020, 8.0, "{}", "movie", 2),
        )
        db.commit()
    before = _hash(source)

    report = audit_scout_database(source)
    summary = report["summary"]

    assert report["read_only"] is True
    assert report["snapshot_consistent"] is True
    assert summary["total_records"] == 4
    assert summary["media_type_counts"] == {"movie": 3, "tv": 1}
    assert summary["invalid_identity_rows"] == 1
    assert summary["duplicate_douban_ids"] == 1
    assert summary["rows_in_duplicate_groups"] == 2
    assert summary["invalid_ratings"] == 1
    assert summary["invalid_years"] == 1
    assert summary["malformed_raw_data"] == 2
    assert summary["field_coverage"]["overview"]["present"] == 1
    assert summary["field_coverage"]["posters"]["present"] == 1
    assert report["strict_gate"]["passed"] is False
    assert _hash(source) == before


def test_audit_cli_strict_mode_returns_nonzero_for_identity_defects(tmp_path, monkeypatch, capsys):
    source = tmp_path / "scout.sqlite"
    _source(source)
    with sqlite3.connect(source) as db:
        db.execute("UPDATE item SET douban_id = NULL WHERE douban_id = '10001'")
        db.commit()

    monkeypatch.setattr("sys.argv", ["audit_scout_import", "--scout-db", str(source), "--strict"])
    assert main() == 2
    output = capsys.readouterr()
    assert '"read_only": true' in output.out
    assert "Strict Scout import audit failed" in output.err


def test_import_preflight_can_reject_identity_and_duplicate_ids(tmp_path):
    from app.services.import_service import ImportService

    source = tmp_path / "scout.sqlite"
    _source(source)
    with sqlite3.connect(source) as db:
        db.execute("UPDATE item SET douban_id = 'bad-id' WHERE douban_id = '10001'")
        db.commit()

    conn = sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        with pytest.raises(ValueError, match="invalid Douban ID or empty title"):
            ImportService._validate_source(conn, reject_invalid_identity=True)
    finally:
        conn.close()
