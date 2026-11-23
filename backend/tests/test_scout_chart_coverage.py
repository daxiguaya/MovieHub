"""Tests for read-only Scout metadata coverage audit."""

import hashlib
import json
import sqlite3

from scripts.audit_chart_scout_coverage import audit_chart_snapshots


def _create_scout(path):
    detail = {
        "rating": {"count": 2345},
        "original_title": "Original title",
        "summary": "Scout summary",
        "url": "https://movie.douban.com/subject/1234567/",
        "directors": [{"name": "Director"}],
        "actors": [{"name": "Actor"}],
        "genres": ["剧情", "悬疑"],
        "countries": ["中国大陆"],
        "pic": {"large": "https://img.example/poster.jpg"},
    }
    with sqlite3.connect(path) as db:
        db.execute(
            """
            CREATE TABLE item (
                douban_id TEXT, imdb_id TEXT, douban_title TEXT, year INTEGER,
                rating REAL, raw_data TEXT, type TEXT, update_time INTEGER
            )
            """
        )
        db.execute(
            "INSERT INTO item VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "1234567", "tt1234567", "Scout movie", 2020, 8.6,
                json.dumps({"detail": detail}, ensure_ascii=False),
                "movie", 1790000000,
            ),
        )
        db.commit()


def _sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def test_audit_reports_match_missing_and_field_coverage_without_writes(tmp_path):
    scout = tmp_path / "scout.sqlite"
    snapshot = tmp_path / "annual.json"
    _create_scout(scout)
    snapshot.write_text(
        json.dumps(
            {
                "slug": "annual-2025-chinese-movies",
                "name": "2025 评分最高华语电影",
                "source": "douban",
                "category": "annual",
                "period": "2025",
                "snapshot_date": "2026-11-23",
                "movies": [
                    {
                        "douban_id": "1234567",
                        "rank": 1,
                        "title": "Movie",
                        "type": "movie",
                    },
                    {
                        "douban_id": "7654321",
                        "rank": 2,
                        "title": "Missing",
                        "type": "movie",
                    },
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    before = _sha256(scout)

    report = audit_chart_snapshots([snapshot], scout)

    assert report["read_only"] is True
    summary = report["summary"]
    assert {
        key: summary[key]
        for key in (
            "chart_count",
            "chart_items",
            "scout_matches",
            "scout_type_valid_matches",
            "scout_missing",
            "scout_ambiguous",
            "type_mismatches",
        )
    } == {
        "chart_count": 1,
        "chart_items": 2,
        "scout_matches": 1,
        "scout_type_valid_matches": 1,
        "scout_missing": 1,
        "scout_ambiguous": 0,
        "type_mismatches": 0,
    }
    assert summary["field_coverage"]["year"] == {
        "present": 1,
        "matched_total": 1,
        "percent": 100.0,
    }
    chart = report["charts"][0]
    assert chart["missing_douban_ids"] == ["7654321"]
    assert chart["field_coverage"]["year"]["present"] == 1
    assert chart["field_coverage"]["rating_count"]["present"] == 1
    assert chart["field_coverage"]["directors"]["present"] == 1
    assert chart["field_coverage"]["posters"]["present"] == 1
    assert _sha256(scout) == before


def test_audit_reports_media_type_mismatch(tmp_path):
    scout = tmp_path / "scout.sqlite"
    snapshot = tmp_path / "annual-tv.json"
    _create_scout(scout)
    snapshot.write_text(
        json.dumps(
            {
                "slug": "annual-2025-chinese-tv",
                "name": "2025 评分最高华语剧集",
                "source": "douban",
                "category": "annual",
                "period": "2025",
                "snapshot_date": "2026-11-23",
                "movies": [
                    {
                        "douban_id": "1234567",
                        "rank": 1,
                        "title": "TV",
                        "type": "tv",
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    report = audit_chart_snapshots([snapshot], scout)
    assert report["summary"]["type_mismatches"] == 1
    chart = report["charts"][0]
    assert chart["type_mismatches"][0]["scout_type"] == "movie"
    assert chart["scout_matches"] == 1
    assert chart["scout_type_valid_matches"] == 0
    assert chart["field_coverage"]["year"]["matched_total"] == 0
    assert chart["field_coverage"]["year"]["present"] == 0



def test_audit_flags_unexpected_scout_media_type_instead_of_missing(tmp_path):
    scout = tmp_path / "scout.sqlite"
    snapshot = tmp_path / "annual-book-mismatch.json"
    _create_scout(scout)
    with sqlite3.connect(scout) as db:
        db.execute(
            "UPDATE item SET type = 'book' WHERE douban_id = '1234567'"
        )
        db.commit()
    snapshot.write_text(
        json.dumps(
            {
                "slug": "annual-2025-chinese-movies",
                "name": "2025 评分最高华语电影",
                "source": "douban",
                "category": "annual",
                "period": "2025",
                "snapshot_date": "2026-11-23",
                "movies": [
                    {
                        "douban_id": "1234567",
                        "rank": 1,
                        "title": "Movie",
                        "type": "movie",
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    report = audit_chart_snapshots([snapshot], scout)
    chart = report["charts"][0]
    assert chart["scout_matches"] == 1
    assert chart["scout_missing"] == 0
    assert chart["type_mismatch_count"] == 1
    assert chart["type_mismatches"][0]["scout_type"] == "book"
    assert chart["scout_type_valid_matches"] == 0
    assert chart["field_coverage"]["year"]["matched_total"] == 0
    assert chart["field_coverage"]["year"]["present"] == 0


def test_audit_reports_duplicate_scout_ids_as_ambiguous(tmp_path):
    scout = tmp_path / "scout.sqlite"
    snapshot = tmp_path / "annual-ambiguous.json"
    _create_scout(scout)
    with sqlite3.connect(scout) as db:
        db.execute(
            "INSERT INTO item VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "1234567", "tt7654321", "Duplicate row", 2021, 7.5,
                json.dumps({"detail": {"summary": "Second row"}}),
                "movie", 1790000001,
            ),
        )
        db.commit()
    snapshot.write_text(
        json.dumps(
            {
                "slug": "annual-2025-chinese-movies",
                "name": "2025 评分最高华语电影",
                "source": "douban",
                "category": "annual",
                "period": "2025",
                "snapshot_date": "2026-11-23",
                "movies": [
                    {
                        "douban_id": "1234567",
                        "rank": 1,
                        "title": "Movie",
                        "type": "movie",
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    report = audit_chart_snapshots([snapshot], scout)
    chart = report["charts"][0]
    assert chart["scout_matches"] == 0
    assert chart["scout_missing"] == 0
    assert chart["scout_ambiguous"] == 1
    assert chart["ambiguous_douban_ids"] == ["1234567"]
    assert report["summary"]["scout_ambiguous"] == 1



def test_audit_rejects_duplicate_chart_date_inputs_before_opening_scout(tmp_path):
    snapshot = tmp_path / "annual.json"
    snapshot.write_text(
        json.dumps(
            {
                "slug": "annual-2025-chinese-movies",
                "name": "2025 评分最高华语电影",
                "source": "douban",
                "category": "annual",
                "period": "2025",
                "snapshot_date": "2026-11-23",
                "movies": [
                    {
                        "douban_id": "1234567",
                        "rank": 1,
                        "title": "Movie",
                        "type": "movie",
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    import pytest

    with pytest.raises(ValueError, match="Duplicate chart/date"):
        audit_chart_snapshots([snapshot, snapshot], tmp_path / "missing-scout.sqlite")



def test_audit_aggregates_field_coverage_across_distinct_charts(tmp_path):
    scout = tmp_path / "scout.sqlite"
    _create_scout(scout)
    snapshots = []
    for slug, name in (
        ("annual-2025-chinese-movies", "2025 评分最高华语电影"),
        ("annual-2025-international-movies", "2025 评分最高外语电影"),
    ):
        path = tmp_path / f"{slug}.json"
        path.write_text(
            json.dumps(
                {
                    "slug": slug,
                    "name": name,
                    "source": "douban",
                    "category": "annual",
                    "period": "2025",
                    "snapshot_date": "2026-11-23",
                    "movies": [
                        {
                            "douban_id": "1234567",
                            "rank": 1,
                            "title": "Shared chart entry",
                            "type": "movie",
                        }
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        snapshots.append(path)

    report = audit_chart_snapshots(snapshots, scout)

    assert report["summary"]["chart_count"] == 2
    assert report["summary"]["chart_items"] == 2
    assert report["summary"]["scout_type_valid_matches"] == 2
    assert report["summary"]["field_coverage"]["year"] == {
        "present": 2,
        "matched_total": 2,
        "percent": 100.0,
    }
