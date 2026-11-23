"""Read-only reporting helpers for the durable Scout import journal."""

from pathlib import Path
from typing import Any

from app.services.import_journal import read_import_events


def summarize_import_events(
    events: list[dict[str, Any]],
    run_id: str | None = None,
) -> list[dict[str, Any]]:
    """Build cumulative run summaries without opening either SQLite database."""
    runs: dict[str, dict[str, Any]] = {}

    for event in events:
        current_id = event.get("run_id")
        if not isinstance(current_id, str) or not current_id:
            continue
        if run_id is not None and current_id != run_id:
            continue

        kind = event.get("event")
        summary = runs.get(current_id)
        if kind == "run_started":
            if summary is None:
                summary = {
                    "run_id": current_id,
                    "status": "interrupted",
                    "source_path": event.get("source_path"),
                    "force_full": event.get("force_full"),
                    "source_fingerprint": event.get("source_fingerprint"),
                    "total": event.get("total", 0),
                    "processed": 0,
                    "imported": 0,
                    "skipped": 0,
                    "errors": 0,
                    "batches": 0,
                    "started_at": event.get("started_at"),
                    "completed_at": None,
                    "last_event_at": event.get("started_at"),
                    "last_douban_id": None,
                    "resume_count": 0,
                }
                runs[current_id] = summary
            continue

        if summary is None:
            # Ignore orphaned events instead of presenting an incomplete run
            # as authoritative; a valid run always begins with run_started.
            continue

        timestamp = (
            event.get("committed_at")
            or event.get("resumed_at")
            or event.get("completed_at")
            or event.get("failed_at")
        )
        if timestamp:
            summary["last_event_at"] = timestamp

        if kind == "batch_committed":
            summary.update({
                "status": "running",
                "processed": event.get("processed", summary["processed"]),
                "total": event.get("total", summary["total"]),
                "imported": event.get("imported", summary["imported"]),
                "skipped": event.get("skipped", summary["skipped"]),
                "errors": event.get("errors", summary["errors"]),
                "batches": event.get("batch", summary["batches"]),
                "last_douban_id": event.get("last_douban_id"),
            })
        elif kind == "run_resumed":
            summary["status"] = "running"
            summary["resume_count"] += 1
        elif kind == "run_completed":
            summary.update({
                "status": "completed",
                "processed": event.get("processed", summary["processed"]),
                "total": event.get("total", summary["total"]),
                "imported": event.get("imported", summary["imported"]),
                "skipped": event.get("skipped", summary["skipped"]),
                "errors": event.get("errors", summary["errors"]),
                "batches": event.get("batches", summary["batches"]),
                "completed_at": event.get("completed_at"),
            })
        elif kind == "run_failed":
            summary["status"] = "failed"
            summary["failed_at"] = event.get("failed_at")
            summary["failed_after_batches"] = event.get(
                "committed_batches", summary["batches"]
            )

    return sorted(
        runs.values(),
        key=lambda item: item.get("started_at") or "",
        reverse=True,
    )


def read_import_run_history(
    journal_path: str | Path,
    run_id: str | None = None,
) -> list[dict[str, Any]]:
    """Read and summarize the journal; never accesses MovieHub or Scout DBs."""
    return summarize_import_events(read_import_events(journal_path), run_id=run_id)
