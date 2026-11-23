"""Reconcile a saved read-only preview with a completed import journal."""

import json
from pathlib import Path
from typing import Any

from app.services.import_errors import read_import_errors
from app.services.import_history import read_import_run_history


class ReconciliationError(ValueError):
    """The preview/run pair cannot be safely reconciled."""


def _validate_preview(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or value.get("report_version") != 1:
        raise ReconciliationError("Unsupported or invalid preview report version")
    if value.get("read_only") is not True:
        raise ReconciliationError("Preview report is not marked read-only")
    if not isinstance(value.get("source_database"), str) or not value["source_database"]:
        raise ReconciliationError("Preview report is missing source_database")
    fingerprint = value.get("source_fingerprint")
    if not isinstance(fingerprint, str) or len(fingerprint) != 64:
        raise ReconciliationError("Preview report has an invalid source fingerprint")
    if not isinstance(value.get("force_full"), bool):
        raise ReconciliationError("Preview report is missing force_full mode")
    summary = value.get("summary")
    required = ("source_records", "new_records", "update_candidates", "unchanged_skips", "would_write")
    if not isinstance(summary, dict):
        raise ReconciliationError("Preview report is missing summary")
    for key in required:
        number = summary.get(key)
        if not isinstance(number, int) or isinstance(number, bool) or number < 0:
            raise ReconciliationError(f"Preview report has invalid summary.{key}")
    if summary["new_records"] + summary["update_candidates"] != summary["would_write"]:
        raise ReconciliationError("Preview report counters are internally inconsistent")
    if summary["would_write"] + summary["unchanged_skips"] != summary["source_records"]:
        raise ReconciliationError("Preview report totals are internally inconsistent")
    return value


def load_preview_report(path: str | Path) -> dict[str, Any]:
    try:
        value = json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ReconciliationError(f"Cannot read preview report: {exc}") from exc
    return _validate_preview(value)


def reconcile_preview_with_run(
    preview: dict[str, Any],
    journal_path: str | Path,
    run_id: str,
) -> dict[str, Any]:
    """Compare preview accounting with durable run counters; never opens SQLite."""
    preview = _validate_preview(preview)
    if not isinstance(run_id, str) or not run_id or len(run_id) > 64:
        raise ReconciliationError("A valid run_id is required")
    runs = read_import_run_history(journal_path, run_id=run_id)
    if not runs:
        raise ReconciliationError(f"Import run not found: {run_id}")
    run = runs[0]
    blockers = []
    if run["status"] != "completed":
        blockers.append(f"Import run is not completed (status={run['status']})")
    if run.get("source_path") != preview["source_database"]:
        blockers.append("Source path differs from the saved preview")
    if run.get("force_full") is not preview["force_full"]:
        blockers.append("Import mode differs from the saved preview")
    if run.get("source_fingerprint") != preview["source_fingerprint"]:
        blockers.append("Source fingerprint differs from the saved preview")
    if blockers:
        return {
            "reconciled": False,
            "status": "blocked",
            "run_id": run_id,
            "blockers": blockers,
            "preview": preview["summary"],
            "actual": {key: run.get(key) for key in ("total", "processed", "imported", "skipped", "errors")},
        }

    errors = read_import_errors(journal_path, run_id=run_id)
    error_count = len(errors)
    summary = preview["summary"]
    expected_imported = summary["new_records"] + summary["update_candidates"]
    actual_imported = int(run.get("imported") or 0)
    actual_skipped = int(run.get("skipped") or 0)
    actual_errors = int(run.get("errors") or 0)
    checks = {
        "source_records": {"expected": summary["source_records"], "actual": int(run.get("total") or 0)},
        "processed": {"expected": summary["source_records"], "actual": int(run.get("processed") or 0)},
        "imported_plus_errors": {"expected": expected_imported, "actual": actual_imported + actual_errors},
        "unchanged_skips": {"expected": summary["unchanged_skips"], "actual": actual_skipped - actual_errors},
        "error_manifest": {"expected": actual_errors, "actual": error_count},
    }
    mismatches = [
        {"counter": name, **values}
        for name, values in checks.items()
        if values["expected"] != values["actual"]
    ]
    matched = not mismatches
    return {
        "reconciled": matched,
        "status": ("matched_with_errors" if actual_errors else "matched") if matched else "mismatch",
        "run_id": run_id,
        "source_fingerprint": preview["source_fingerprint"],
        "preview": {
            "new_records": summary["new_records"],
            "update_candidates": summary["update_candidates"],
            "expected_imported": expected_imported,
            "unchanged_skips": summary["unchanged_skips"],
            "would_write": summary["would_write"],
        },
        "actual": {
            "imported": actual_imported,
            "skipped": actual_skipped,
            "errors": actual_errors,
            "error_manifest_records": error_count,
            "processed": int(run.get("processed") or 0),
            "total": int(run.get("total") or 0),
        },
        "checks": checks,
        "mismatches": mismatches,
        "record_errors": errors,
        "note": "A match validates accounting and source identity, not metadata correctness or target stability between preview and import.",
    }
