import json
import sqlite3

import pytest

from scripts.import_verified_tmdb_identities import apply_report


def make_db(path):
    with sqlite3.connect(path) as conn:
        conn.executescript(
            """
            CREATE TABLE movies (
                id INTEGER PRIMARY KEY, douban_id TEXT, tmdb_id TEXT UNIQUE,
                title TEXT NOT NULL, year INTEGER, type TEXT NOT NULL
            );
            CREATE TABLE movie_metadata_provenance (
                id INTEGER PRIMARY KEY, movie_id INTEGER NOT NULL,
                field_name TEXT NOT NULL, source TEXT NOT NULL,
                source_url TEXT NOT NULL DEFAULT '', observed_at TEXT NOT NULL,
                value_sha256 TEXT NOT NULL,
                UNIQUE(movie_id, field_name, source, source_url, value_sha256),
                FOREIGN KEY(movie_id) REFERENCES movies(id)
            );
            INSERT INTO movies VALUES
                (1, 'db-1', NULL, '肖申克的救赎', 1994, 'movie'),
                (2, 'db-2', NULL, '未知电影', 2020, 'movie'),
                (3, 'db-3', '999', '已有映射', 2021, 'movie');
            """
        )


def make_report(path):
    report = {
        "report_version": 1,
        "read_only": True,
        "results": [
            {
                "movie_id": 1, "douban_id": "db-1", "title": "肖申克的救赎",
                "year": 1994, "media_type": "movie", "status": "verified_candidate",
                "verified_candidates": [{"tmdb_id": 278}],
                "review_candidates": [], "errors": [],
            },
            {
                "movie_id": 2, "douban_id": "db-2", "title": "未知电影",
                "year": 2020, "media_type": "movie", "status": "needs_review",
                "verified_candidates": [], "review_candidates": [{"tmdb_id": 123}],
                "errors": [],
            },
            {
                "movie_id": 3, "douban_id": "db-3", "title": "已有映射",
                "year": 2021, "media_type": "movie", "status": "no_match",
                "verified_candidates": [], "review_candidates": [], "errors": [],
            },
        ],
    }
    path.write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")


def test_default_is_read_only_dry_run(tmp_path):
    db = tmp_path / "movies.db"
    report = tmp_path / "audit.json"
    make_db(db)
    make_report(report)
    before = db.read_bytes()

    result = apply_report(db, report)

    assert result["mode"] == "dry_run"
    assert result["verified_candidates_in_report"] == 1
    assert result["would_update"] == 1
    assert result["database_written"] is False
    assert result["backup"] is None
    assert db.read_bytes() == before


def test_apply_updates_only_verified_identity_and_records_provenance(tmp_path):
    db = tmp_path / "movies.db"
    report = tmp_path / "audit.json"
    make_db(db)
    make_report(report)

    result = apply_report(db, report, apply=True)

    assert result["updated"] == 1
    assert result["database_written"] is True
    assert result["backup"]
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT tmdb_id FROM movies WHERE id=1").fetchone()[0] == "278"
        assert conn.execute("SELECT tmdb_id FROM movies WHERE id=2").fetchone()[0] is None
        assert conn.execute("SELECT tmdb_id FROM movies WHERE id=3").fetchone()[0] == "999"
        provenance = conn.execute(
            "SELECT field_name, source, source_url FROM movie_metadata_provenance"
        ).fetchone()
        assert provenance == (
            "tmdb_id", "tmdb", "https://api.themoviedb.org/3/movie/278"
        )


def test_reapplying_same_report_is_idempotent(tmp_path):
    db = tmp_path / "movies.db"
    report = tmp_path / "audit.json"
    make_db(db)
    make_report(report)
    apply_report(db, report, apply=True)

    result = apply_report(db, report, apply=True)

    assert result["would_update"] == 0
    assert result["already_applied"] == 1
    assert result["database_written"] is False


def test_stale_report_or_tmdb_identity_conflict_fails_closed(tmp_path):
    db = tmp_path / "movies.db"
    report = tmp_path / "audit.json"
    make_db(db)
    make_report(report)
    with sqlite3.connect(db) as conn:
        conn.execute("UPDATE movies SET title='Changed title' WHERE id=1")
    before = db.read_bytes()

    with pytest.raises(ValueError, match="stale"):
        apply_report(db, report, apply=True)

    assert db.read_bytes() == before


def test_duplicate_tmdb_id_in_verified_candidates_is_rejected(tmp_path):
    db = tmp_path / "movies.db"
    report = tmp_path / "audit.json"
    make_db(db)
    make_report(report)
    payload = json.loads(report.read_text(encoding="utf-8"))
    payload["results"][1].update({
        "status": "verified_candidate",
        "verified_candidates": [{"tmdb_id": 278}],
        "review_candidates": [],
    })
    report.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(ValueError, match="Duplicate TMDB ID"):
        apply_report(db, report)
