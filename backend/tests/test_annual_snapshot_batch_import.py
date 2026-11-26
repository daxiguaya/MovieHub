"""Tests for the manifest-driven future annual chart importer."""
import json
from datetime import date

import pytest
from sqlalchemy import create_engine, event, select, func
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.database import Base, Chart, ChartSnapshot, ChartItem, Movie
import scripts.import_annual_snapshot_batch as annual_import


CAPTURE_DATE = date(2026, 11, 26)


def _write_batch(directory, *, period="2026", omit=None, wrong_period=None):
    directory.mkdir(parents=True, exist_ok=True)
    definitions = [
        ("annual-2026-chinese-movies", "2026 评分最高华语电影", "movie"),
        ("annual-2026-international-movies", "2026 评分最高外语电影", "movie"),
        ("annual-2026-chinese-tv", "2026 评分最高华语剧集", "tv"),
    ]
    manifest = {"period": period, "charts": []}
    for index, (slug, name, media_type) in enumerate(definitions, start=1):
        manifest["charts"].append({
            "slug": slug,
            "name": name,
            "media_type": media_type,
        })
        if slug == omit:
            continue
        payload = {
            "slug": slug,
            "name": name,
            "source": "douban",
            "category": "annual",
            "period": wrong_period or period,
            "snapshot_date": CAPTURE_DATE.isoformat(),
            "movies": [{
                "douban_id": str(910000 + index),
                "rank": 1,
                "source_rating": 8.1,
                "rating": 8.1,
                "title": f"Fixture {index}",
                "type": media_type,
            }],
        }
        (directory / f"{slug}-{CAPTURE_DATE.isoformat()}.json").write_text(
            json.dumps(payload, ensure_ascii=False), encoding="utf-8"
        )
    manifest_path = directory / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    return manifest_path


def test_dry_run_validates_future_year_batch_without_database_access(tmp_path, monkeypatch):
    manifest = _write_batch(tmp_path)
    monkeypatch.setattr(
        annual_import, "database_is_ready",
        lambda: pytest.fail("dry-run must not inspect the database"),
    )
    result = annual_import.import_annual_batch(tmp_path, CAPTURE_DATE, manifest)
    assert result["valid"] is True
    assert result["applied"] is False
    assert result["period"] == "2026"
    assert result["chart_count"] == 3


def test_rejects_missing_chart_before_database_access(tmp_path, monkeypatch):
    manifest = _write_batch(tmp_path, omit="annual-2026-chinese-tv")
    monkeypatch.setattr(
        annual_import, "database_is_ready",
        lambda: pytest.fail("invalid input must fail before database access"),
    )
    with pytest.raises(ValueError, match="Missing annual chart"):
        annual_import.import_annual_batch(tmp_path, CAPTURE_DATE, manifest, apply=True)


def test_rejects_period_mismatch(tmp_path, monkeypatch):
    manifest = _write_batch(tmp_path, wrong_period="2025")
    monkeypatch.setattr(
        annual_import, "database_is_ready",
        lambda: pytest.fail("invalid input must fail before database access"),
    )
    with pytest.raises(ValueError, match="period"):
        annual_import.import_annual_batch(tmp_path, CAPTURE_DATE, manifest)


def test_rejects_slug_that_could_overwrite_another_year(tmp_path):
    manifest = _write_batch(tmp_path)
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    payload["charts"][0]["slug"] = "annual-2025-chinese-movies"
    manifest.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="must start with annual-2026"):
        annual_import.load_annual_batch(tmp_path, CAPTURE_DATE, manifest)


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


def test_apply_imports_batch_atomically_and_keeps_prior_year_snapshots(tmp_path, monkeypatch):
    manifest = _write_batch(tmp_path)
    engine = _isolated_database()
    with Session(engine) as db:
        old_chart = Chart(
            slug="annual-2025-chinese-movies",
            name="2025 评分最高华语电影",
            source="douban",
            category="annual",
            period="2025",
            enabled=True,
            display_order=40,
        )
        db.add(old_chart)
        db.flush()
        old_movie = Movie(
            douban_id="900001", title="2025 preserved", type="movie",
            directors="[]", actors="[]",
        )
        db.add(old_movie)
        db.flush()
        old_snapshot = ChartSnapshot(
            list_id=old_chart.list_id, snapshot_date="2026-01-15", item_count=1,
        )
        db.add(old_snapshot)
        db.flush()
        db.add(ChartItem(snapshot_id=old_snapshot.id, movie_id=old_movie.id, rank=1))
        db.commit()

    monkeypatch.setattr(annual_import, "database_is_ready", lambda: True)
    monkeypatch.setattr(
        annual_import, "SessionLocal",
        lambda: Session(engine, expire_on_commit=False),
    )
    try:
        result = annual_import.import_annual_batch(
            tmp_path, CAPTURE_DATE, manifest, apply=True
        )
        with Session(engine) as db:
            assert result["applied"] is True
            assert db.scalar(select(func.count()).select_from(Chart)) == 4
            assert db.scalar(select(func.count()).select_from(ChartSnapshot)) == 4
            assert db.scalar(select(func.count()).select_from(ChartItem)) == 4
            preserved = db.scalar(select(ChartSnapshot).where(
                ChartSnapshot.snapshot_date == "2026-01-15"
            ))
            assert preserved is not None
            preserved_movie = db.scalar(select(Movie).where(Movie.douban_id == "900001"))
            assert preserved_movie.title == "2025 preserved"
    finally:
        engine.dispose()
