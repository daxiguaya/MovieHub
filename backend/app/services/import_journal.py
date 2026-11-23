"""Durable append-only journal for committed Scout import batches."""

import json
import os
from pathlib import Path
from typing import Any


def get_import_journal_path(session_factory: Any) -> Path:
    """Place the journal beside the configured MovieHub database."""
    bind = session_factory.kw.get("bind")
    if bind is None or not getattr(bind, "url", None) or not bind.url.database:
        raise RuntimeError("Cannot resolve MovieHub database path for import journal")
    database_path = Path(bind.url.database).expanduser().resolve()
    return database_path.with_name(database_path.name + ".import-journal.jsonl")


def append_import_event(path: str | Path, event: dict[str, Any]) -> None:
    """Append one complete event and fsync it before returning."""
    journal_path = Path(path)
    journal_path.parent.mkdir(parents=True, exist_ok=True)
    payload = (
        json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n"
    ).encode("utf-8")
    descriptor = os.open(
        journal_path,
        os.O_CREAT | os.O_APPEND | os.O_WRONLY,
        0o600,
    )
    try:
        # One append write per JSONL event prevents interleaving between
        # independent writers; fsync makes each committed-batch marker durable.
        written = os.write(descriptor, payload)
        if written != len(payload):
            raise OSError("Incomplete import journal write")
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def read_import_events(path: str | Path) -> list[dict[str, Any]]:
    """Read complete journal lines, ignoring a torn final line after a crash."""
    journal_path = Path(path)
    if not journal_path.exists():
        return []
    events: list[dict[str, Any]] = []
    with journal_path.open("r", encoding="utf-8") as source:
        for line in source:
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                events.append(value)
    return events
