"""Tests for the guarded four-chart annual import command."""
import json
from datetime import date

import pytest

import scripts.import_annual_charts as annual_import


CAPTURE_DATE = date(2026, 11, 23)


def _write_batch(directory, *, date_value="2026-11-23", filename_date=None, omit=None):
    directory.mkdir(parents=True, exist_ok=True)
    definitions = {
        "annual-2025-chinese-movies": ("movie", "Chinese movies"),
        "annual-2025-international-movies": ("movie", "International movies"),
        "annual-2025-hidden-gems": ("movie", "Hidden gems"),
        "annual-2025-chinese-tv": ("tv", "Chinese TV"),
    }
    for index, (slug, (media_type, name)) in enumerate(definitions.items(), start=1):
        if slug == omit:
            continue
        payload = {
            "slug": slug,
            "name": name,
            "source": "douban",
            "category": "annual",
            "period": "2025",
            "snapshot_date": date_value,
            "movies": [
                {
                    "douban_id": str(900000 + index),
                    "rank": 1,
                    "title": f"Fixture {name}",
                    "type": media_type,
                }
            ],
        }
        file_date = filename_date or date_value
        (directory / f"{slug}-{file_date}.json").write_text(
            json.dumps(payload, ensure_ascii=False),
            encoding="utf-8",
        )


def test_annual_batch_dry_run_validates_four_files_without_database_access(
    tmp_path, monkeypatch
):
    _write_batch(tmp_path)

    def unexpected_database_access():
        raise AssertionError("dry-run must not inspect the database")

    monkeypatch.setattr(annual_import, "database_is_ready", unexpected_database_access)

    result = annual_import.import_annual_batch(tmp_path, CAPTURE_DATE)

    assert result["valid"] is True
    assert result["applied"] is False
    assert result["chart_count"] == 4
    assert [chart["slug"] for chart in result["charts"]] == list(
        annual_import.ANNUAL_CHARTS
    )


def test_annual_batch_rejects_missing_chart_before_database_access(tmp_path, monkeypatch):
    _write_batch(tmp_path, omit="annual-2025-hidden-gems")
    monkeypatch.setattr(
        annual_import,
        "database_is_ready",
        lambda: pytest.fail("database must not be checked for invalid input"),
    )

    with pytest.raises(ValueError, match="Missing annual chart"):
        annual_import.import_annual_batch(tmp_path, CAPTURE_DATE, apply=True)


def test_annual_batch_rejects_mixed_snapshot_dates(tmp_path, monkeypatch):
    _write_batch(tmp_path, date_value="2026-11-22", filename_date="2026-11-23")
    monkeypatch.setattr(
        annual_import,
        "database_is_ready",
        lambda: pytest.fail("database must not be checked for invalid input"),
    )

    with pytest.raises(ValueError, match="snapshot_date"):
        annual_import.import_annual_batch(tmp_path, CAPTURE_DATE)


def test_annual_batch_apply_calls_single_atomic_service_entrypoint(tmp_path, monkeypatch):
    _write_batch(tmp_path)
    calls = []

    class FakeSession:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

    def capture_batch(db, snapshots):
        calls.append((db, snapshots))
        return {
            "success": True,
            "imported_count": len(snapshots),
            "snapshots": [],
        }

    monkeypatch.setattr(annual_import, "database_is_ready", lambda: True)
    monkeypatch.setattr(annual_import, "SessionLocal", FakeSession)
    monkeypatch.setattr(
        annual_import.chart_import_service,
        "import_snapshots",
        capture_batch,
    )

    result = annual_import.import_annual_batch(
        tmp_path,
        CAPTURE_DATE,
        apply=True,
    )

    assert result["applied"] is True
    assert len(calls) == 1
    assert len(calls[0][1]) == 4
    assert [item.slug for item in calls[0][1]] == list(annual_import.ANNUAL_CHARTS)


def test_annual_batch_rejects_wrong_capture_date_before_opening_database(
    tmp_path, monkeypatch
):
    _write_batch(tmp_path, date_value="2026-11-22")
    monkeypatch.setattr(
        annual_import,
        "database_is_ready",
        lambda: pytest.fail("database must not be checked for invalid input"),
    )

    with pytest.raises(ValueError, match="Missing annual chart"):
        annual_import.import_annual_batch(
            tmp_path,
            date(2026, 11, 23),
            apply=True,
        )
