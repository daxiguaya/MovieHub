"""Tests for the combined read-only Scout import preflight."""

import hashlib
import json
import sqlite3

from scripts.audit_scout_preflight import audit_scout_preflight, main


def _make_inputs(tmp_path, duplicate=False):
    scout = tmp_path / "scout.sqlite"
    snapshot = tmp_path / "annual.json"
    detail = {
        "rating": {"count": 120},
        "summary": "Overview",
        "original_title": "Original",
        "directors": [{"name": "Director"}],
        "actors": [{"name": "Actor"}],
        "genres": ["Drama"],
        "countries": ["Japan"],
        "pic": {"large": "https://img.test/poster.jpg"},
    }
    with sqlite3.connect(scout) as db:
        db.execute(
            """CREATE TABLE item (
                douban_id TEXT, imdb_id TEXT, douban_title TEXT, year INTEGER,
                rating REAL, raw_data TEXT, type TEXT, update_time INTEGER
            )"""
        )
        db.execute(
            "INSERT INTO item VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("1234567", None, "Movie", 2020, 8.5,
             json.dumps({"detail": detail}), "movie", 1700000000),
        )
        if duplicate:
            db.execute(
                "INSERT INTO item VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                ("1234567", None, "Duplicate", 2020, 8.0, "{}", "movie", 1700000001),
            )
        db.commit()
    snapshot.write_text(
        json.dumps({
            "slug": "annual-2025-chinese-movies",
            "name": "2025 评分最高华语电影",
            "source": "douban",
            "category": "annual",
            "period": "2025",
            "snapshot_date": "2026-11-23",
            "movies": [
                {"douban_id": "1234567", "rank": 1, "title": "Movie", "type": "movie"}
            ],
        }, ensure_ascii=False),
        encoding="utf-8",
    )
    return scout, snapshot


def _hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_combined_preflight_passes_and_never_modifies_scout(tmp_path):
    scout, snapshot = _make_inputs(tmp_path)
    before = _hash(scout)

    report = audit_scout_preflight(scout, [snapshot])

    assert report["read_only"] is True
    assert report["decision"] == "ready_for_operator_review"
    assert report["strict_gate"]["passed"] is True
    assert not any(report["strict_gate"]["blocking_issues"].values())
    assert report["catalogue_audit"]["summary"]["total_records"] == 1
    assert report["chart_coverage_audit"]["summary"]["scout_type_valid_matches"] == 1
    assert _hash(scout) == before


def test_combined_preflight_blocks_duplicate_catalogue_identity(tmp_path):
    scout, snapshot = _make_inputs(tmp_path, duplicate=True)

    report = audit_scout_preflight(scout, [snapshot])

    assert report["decision"] == "blocked"
    assert report["strict_gate"]["passed"] is False
    assert report["strict_gate"]["blocking_issues"]["duplicate_douban_ids"] == 1


def test_combined_preflight_cli_returns_two_when_blocked(tmp_path, monkeypatch, capsys):
    scout, snapshot = _make_inputs(tmp_path)
    with sqlite3.connect(scout) as db:
        db.execute(
            "INSERT INTO item VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("7654321", None, "Unlisted", 2022, 7.0, "{}", "movie", 1700000002),
        )
        db.commit()
    monkeypatch.setattr(
        "sys.argv",
        ["audit_scout_preflight", "--scout-db", str(scout), "--input", str(snapshot)],
    )

    assert main() == 0
    output = capsys.readouterr()
    assert '"decision": "ready_for_operator_review"' in output.out
    assert output.err == ""

    # A chart entry absent from Scout is a blocking coverage issue.
    with sqlite3.connect(scout) as db:
        db.execute("DELETE FROM item WHERE douban_id = '1234567'")
        db.commit()
    assert main() == 2
    output = capsys.readouterr()
    assert '"decision": "blocked"' in output.out
    assert "chart_items_missing_from_scout=1" in output.err
