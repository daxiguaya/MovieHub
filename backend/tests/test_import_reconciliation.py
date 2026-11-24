"""Tests for preview-to-import reconciliation."""

import json

import pytest

from app.services.import_journal import append_import_event
from app.services.import_reconciliation import (
    ReconciliationError,
    load_preview_report,
    reconcile_preview_with_run,
)


def _preview():
    return {
        "report_version": 1,
        "read_only": True,
        "source_database": "/staged/scout.sqlite",
        "source_fingerprint": "a" * 64,
        "force_full": False,
        "summary": {
            "source_records": 5,
            "new_records": 2,
            "update_candidates": 1,
            "unchanged_skips": 2,
            "would_write": 3,
        },
    }


def _journal(path, **overrides):
    append_import_event(path, {
        "event": "run_started", "run_id": "run-1",
        "source_path": "/staged/scout.sqlite", "force_full": False,
        "source_fingerprint": "a" * 64, "total": 5,
        "started_at": "2026-11-23T10:00:00",
    })
    completed = {
        "event": "run_completed", "run_id": "run-1",
        "processed": 5, "total": 5, "imported": 2, "skipped": 3,
        "errors": 1, "batches": 1, "completed_at": "2026-11-23T10:02:00",
    }
    completed.update(overrides)
    append_import_event(path, completed)
    error_path = path.with_name(path.name.replace(".import-journal.jsonl", ".import-errors.jsonl"))
    append_import_event(error_path, {
        "event": "record_error", "run_id": "run-1", "batch": 1,
        "douban_id": "1005", "title": "Bad record",
        "error_type": "IntegrityError", "error_message": "constraint",
        "occurred_at": "2026-11-23T10:01:00",
    })


def test_reconciliation_accounts_for_record_errors_and_matches_counts(tmp_path):
    journal = tmp_path / "movies.db.import-journal.jsonl"
    _journal(journal)
    result = reconcile_preview_with_run(_preview(), journal, "run-1")
    assert result["reconciled"] is True
    assert result["status"] == "matched_with_errors"
    assert result["checks"]["imported_plus_errors"] == {"expected": 3, "actual": 3}
    assert result["checks"]["unchanged_skips"] == {"expected": 2, "actual": 2}
    assert len(result["record_errors"]) == 1


def test_reconciliation_blocks_source_fingerprint_mismatch(tmp_path):
    journal = tmp_path / "movies.db.import-journal.jsonl"
    _journal(journal)
    preview = _preview()
    preview["source_fingerprint"] = "b" * 64
    result = reconcile_preview_with_run(preview, journal, "run-1")
    assert result["status"] == "blocked"
    assert any("fingerprint" in item for item in result["blockers"])


def test_reconciliation_blocks_incomplete_run(tmp_path):
    journal = tmp_path / "movies.db.import-journal.jsonl"
    append_import_event(journal, {
        "event": "run_started", "run_id": "run-1",
        "source_path": "/staged/scout.sqlite", "force_full": False,
        "source_fingerprint": "a" * 64, "total": 5,
    })
    result = reconcile_preview_with_run(_preview(), journal, "run-1")
    assert result["status"] == "blocked"
    assert "incomplete" in result["blockers"][0]


def test_reconciliation_detects_counter_drift(tmp_path):
    journal = tmp_path / "movies.db.import-journal.jsonl"
    _journal(journal, imported=1, skipped=4)
    result = reconcile_preview_with_run(_preview(), journal, "run-1")
    assert result["reconciled"] is False
    assert {item["counter"] for item in result["mismatches"]} >= {"imported_plus_errors"}


def test_preview_report_rejects_corrupt_or_inconsistent_payload(tmp_path):
    report = _preview()
    report["summary"]["would_write"] = 99
    path = tmp_path / "preview.json"
    path.write_text(json.dumps(report), encoding="utf-8")
    with pytest.raises(ReconciliationError, match="inconsistent"):
        load_preview_report(path)
