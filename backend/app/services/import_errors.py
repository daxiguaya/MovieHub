"""Durable, privacy-conscious per-record Scout import failure reports."""

from pathlib import Path
from typing import Any

from app.services.import_journal import append_import_event, read_import_events


def get_import_error_path(journal_path: str | Path) -> Path:
    """Return the failure manifest path beside the import journal."""
    path = Path(journal_path)
    suffix = ".import-journal.jsonl"
    if path.name.endswith(suffix):
        return path.with_name(path.name[:-len(suffix)] + ".import-errors.jsonl")
    return path.with_name(path.name + ".errors.jsonl")


def append_import_errors(
    journal_path: str | Path,
    errors: list[dict[str, Any]],
) -> None:
    """Append durable record-level failures without copying raw Scout payloads."""
    manifest = get_import_error_path(journal_path)
    for error in errors:
        append_import_event(manifest, {"event": "record_error", **error})


def read_import_errors(
    journal_path: str | Path,
    run_id: str | None = None,
) -> list[dict[str, Any]]:
    """Read and de-duplicate failures, including safe replay after checkpoint gaps."""
    events = read_import_events(get_import_error_path(journal_path))
    unique: dict[tuple[str, int, str, str, str], dict[str, Any]] = {}
    for event in events:
        if event.get("event") != "record_error":
            continue
        event_run_id = event.get("run_id")
        if not isinstance(event_run_id, str) or not event_run_id:
            continue
        if run_id is not None and event_run_id != run_id:
            continue
        try:
            batch = int(event.get("batch", 0))
        except (TypeError, ValueError):
            batch = 0
        key = (
            event_run_id,
            batch,
            str(event.get("douban_id", "")),
            str(event.get("error_type", "")),
            str(event.get("error_message", "")),
        )
        unique.setdefault(key, event)
    return sorted(
        unique.values(),
        key=lambda item: (
            str(item.get("occurred_at", "")),
            int(item.get("batch", 0) or 0),
            str(item.get("douban_id", "")),
        ),
    )
