"""Tests for the one-command read-only Scout import readiness package."""

import hashlib
import json
import sqlite3

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.database import Base, Movie
import app.services.import_service as import_service_module
import scripts.prepare_scout_import as preparation


def _inputs(tmp_path, duplicate=False):
    scout = tmp_path / "scout.sqlite"
    chart = tmp_path / "annual.json"
    with sqlite3.connect(scout) as db:
        db.execute(
            """CREATE TABLE item (
                douban_id TEXT, imdb_id TEXT, douban_title TEXT, year INTEGER,
                rating REAL, raw_data TEXT, type TEXT, update_time INTEGER
            )"""
        )
        db.execute(
            "INSERT INTO item VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("1234567", None, "Movie", 2020, 8.5, "{}", "movie", 1700000000),
        )
        if duplicate:
            db.execute(
                "INSERT INTO item VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                ("1234567", None, "Duplicate", 2021, 8.0, "{}", "movie", 1700000001),
            )
        db.commit()
    chart.write_text(json.dumps({
        "slug": "annual-2025-chinese-movies",
        "name": "2025 Chinese movies",
        "source": "douban",
        "category": "annual",
        "period": "2025",
        "snapshot_date": "2026-11-23",
        "movies": [{"douban_id": "1234567", "rank": 1, "title": "Movie", "type": "movie"}],
    }), encoding="utf-8")
    return scout, chart


def test_prepare_runs_preflight_then_preview_and_never_imports(tmp_path, monkeypatch):
    scout, chart = _inputs(tmp_path)
    target = tmp_path / "target.sqlite"
    engine = create_engine(f"sqlite:///{target.as_posix()}")
    Base.metadata.create_all(engine)
    TargetSession = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    monkeypatch.setattr(preparation, "database_is_ready", lambda: True)
    monkeypatch.setattr(import_service_module, "SessionLocal", TargetSession)
    before = hashlib.sha256(scout.read_bytes()).hexdigest()

    report = preparation.prepare_scout_import(scout, [chart])

    assert report["decision"] == "ready_for_operator_review"
    assert report["preflight"]["strict_gate"]["passed"] is True
    assert report["preview"]["summary"]["new_records"] == 1
    assert report["preview"]["source_fingerprint"]
    assert report["operator_action_required"] is True
    with TargetSession() as db:
        assert db.scalar(select(Movie.id)) is None
    assert hashlib.sha256(scout.read_bytes()).hexdigest() == before
    engine.dispose()


def test_prepare_blocks_before_target_preview_when_preflight_fails(tmp_path, monkeypatch):
    scout, chart = _inputs(tmp_path, duplicate=True)
    monkeypatch.setattr(
        preparation,
        "database_is_ready",
        lambda: (_ for _ in ()).throw(AssertionError("target preview must not run")),
    )

    report = preparation.prepare_scout_import(scout, [chart])

    assert report["decision"] == "blocked"
    assert report["preview"] is None
    assert report["preflight"]["strict_gate"]["passed"] is False


def test_readiness_report_is_written_atomically_with_private_permissions(tmp_path):
    output = tmp_path / "reports" / "ready.json"
    report = {"read_only": True, "decision": "ready_for_operator_review"}
    result = preparation.write_report(output, report)

    assert result == output
    assert json.loads(output.read_text(encoding="utf-8")) == report
    assert output.stat().st_mode & 0o777 == 0o600
    assert not output.with_name(output.name + ".tmp").exists()



def test_report_output_cannot_overwrite_scout_database_or_chart_snapshot(tmp_path):
    scout, chart = _inputs(tmp_path)
    for protected_input in (scout, chart):
        try:
            preparation.validate_report_output_path(
                protected_input,
                scout,
                [chart],
            )
        except ValueError as exc:
            assert "different from the Scout database" in str(exc)
        else:
            raise AssertionError("protected input path was accepted")


def test_report_output_rejects_symlink_destination_and_temporary_file(tmp_path):
    scout, chart = _inputs(tmp_path)
    destination = tmp_path / "report.json"
    destination.symlink_to(scout)
    try:
        preparation.validate_report_output_path(destination, scout, [chart])
    except ValueError as exc:
        assert "symbolic link" in str(exc)
    else:
        raise AssertionError("symlink destination was accepted")

    destination.unlink()
    temporary = destination.with_name(destination.name + ".tmp")
    temporary.symlink_to(scout)
    try:
        preparation.validate_report_output_path(destination, scout, [chart])
    except ValueError as exc:
        assert "temporary path" in str(exc)
    else:
        raise AssertionError("symlink temporary path was accepted")


def test_report_writer_refuses_preexisting_temporary_file(tmp_path):
    output = tmp_path / "ready.json"
    temporary = output.with_name(output.name + ".tmp")
    temporary.write_text("keep me", encoding="utf-8")

    try:
        preparation.write_report(output, {"read_only": True})
    except FileExistsError:
        pass
    else:
        raise AssertionError("pre-existing temporary file was overwritten")

    assert temporary.read_text(encoding="utf-8") == "keep me"
    assert not output.exists()
