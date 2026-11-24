"""Tests for the guarded four-chart annual import command."""
import json
from datetime import date

import pytest
from sqlalchemy import create_engine, event, select, func
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.database import Base, Chart, ChartSnapshot, ChartItem, Movie
import scripts.import_annual_charts as annual_import


CAPTURE_DATE = date(2026, 11, 23)


def _write_batch(directory, *, date_value="2026-11-23", filename_date=None, omit=None, wrong_name=None):
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
            "name": "Unexpected annual chart" if slug == wrong_name else annual_import.ANNUAL_CHARTS[slug]["name"],
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
                    "posters": [f"https://example.test/{900000 + index}.jpg"],
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



def test_annual_batch_rejects_wrong_chart_name_before_database_access(
    tmp_path, monkeypatch
):
    _write_batch(tmp_path, wrong_name="annual-2025-hidden-gems")
    monkeypatch.setattr(
        annual_import,
        "database_is_ready",
        lambda: pytest.fail("database must not be checked for invalid input"),
    )

    with pytest.raises(ValueError, match="declares name"):
        annual_import.import_annual_batch(tmp_path, CAPTURE_DATE, apply=True)


def test_cli_dry_run_returns_zero_and_prints_preflight_summary(
    tmp_path, monkeypatch, capsys
):
    _write_batch(tmp_path)
    monkeypatch.setattr(
        "sys.argv",
        [
            "import_annual_charts",
            "--input-dir",
            str(tmp_path),
            "--date",
            "2026-11-23",
        ],
    )
    monkeypatch.setattr(
        annual_import,
        "database_is_ready",
        lambda: pytest.fail("CLI dry-run must not inspect the database"),
    )

    assert annual_import.main() == 0
    output = json.loads(capsys.readouterr().out)
    assert output["valid"] is True
    assert output["applied"] is False
    assert output["chart_count"] == 4


def test_cli_rejects_invalid_date_without_database_access(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.setattr(
        "sys.argv",
        [
            "import_annual_charts",
            "--input-dir",
            str(tmp_path),
            "--date",
            "not-a-date",
        ],
    )
    monkeypatch.setattr(
        annual_import,
        "database_is_ready",
        lambda: pytest.fail("invalid CLI date must fail before DB access"),
    )

    assert annual_import.main() == 1
    assert "Annual chart import failed" in capsys.readouterr().err



def _isolated_database():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(connection, record):
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    return engine


def test_annual_batch_apply_integrates_with_real_service_and_isolated_database(
    tmp_path, monkeypatch
):
    _write_batch(tmp_path)
    engine = _isolated_database()
    monkeypatch.setattr(annual_import, "database_is_ready", lambda: True)
    monkeypatch.setattr(
        annual_import,
        "SessionLocal",
        lambda: Session(engine, expire_on_commit=False),
    )

    try:
        result = annual_import.import_annual_batch(
            tmp_path,
            CAPTURE_DATE,
            apply=True,
        )

        with Session(engine) as db:
            assert result["applied"] is True
            assert db.scalar(select(func.count()).select_from(Chart)) == 4
            assert db.scalar(select(func.count()).select_from(ChartSnapshot)) == 4
            assert db.scalar(select(func.count()).select_from(ChartItem)) == 4
            assert db.scalar(select(func.count()).select_from(Movie)) == 4
    finally:
        engine.dispose()


def test_annual_batch_apply_rolls_back_all_charts_on_real_service_conflict(
    tmp_path, monkeypatch
):
    _write_batch(tmp_path)
    engine = _isolated_database()
    with Session(engine) as seed_db:
        seed_db.add(
            Movie(
                douban_id="900004",
                title="Existing Scout movie",
                type="movie",
                rating_count=0,
                directors="[]",
                actors="[]",
            )
        )
        seed_db.commit()

    monkeypatch.setattr(annual_import, "database_is_ready", lambda: True)
    monkeypatch.setattr(
        annual_import,
        "SessionLocal",
        lambda: Session(engine, expire_on_commit=False),
    )

    try:
        from app.services.chart_import_service import ChartImportError

        with pytest.raises(ChartImportError, match="media type mismatch"):
            annual_import.import_annual_batch(
                tmp_path,
                CAPTURE_DATE,
                apply=True,
            )

        with Session(engine) as db:
            assert db.scalar(select(func.count()).select_from(Chart)) == 0
            assert db.scalar(select(func.count()).select_from(ChartSnapshot)) == 0
            assert db.scalar(select(func.count()).select_from(ChartItem)) == 0
            assert db.scalar(select(func.count()).select_from(Movie)) == 1
            existing = db.scalar(
                select(Movie).where(Movie.douban_id == "900004")
            )
            assert existing.type == "movie"
            assert existing.title == "Existing Scout movie"
    finally:
        engine.dispose()
