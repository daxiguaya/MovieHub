"""Durable append-only journal for committed Scout import batches."""

import fcntl
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
        os.O_CREAT | os.O_APPEND | os.O_RDWR,
        0o600,
    )
    try:
        # Serialize independent writers and repair only an unterminated tail
        # left by a killed writer before appending the next complete event.
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        end = os.lseek(descriptor, 0, os.SEEK_END)
        if end:
            os.lseek(descriptor, end - 1, os.SEEK_SET)
            if os.read(descriptor, 1) not in (b"\n", b"\r"):
                cursor = end
                truncate_at = 0
                while cursor > 0:
                    start = max(0, cursor - 4096)
                    os.lseek(descriptor, start, os.SEEK_SET)
                    chunk = os.read(descriptor, cursor - start)
                    boundary = max(chunk.rfind(b"\n"), chunk.rfind(b"\r"))
                    if boundary >= 0:
                        truncate_at = start + boundary + 1
                        break
                    cursor = start
                # Preserve a complete JSON object that merely lacks its
                # trailing newline; discard only a malformed partial record.
                tail_size = end - truncate_at
                os.lseek(descriptor, truncate_at, os.SEEK_SET)
                tail = os.read(descriptor, tail_size)
                try:
                    tail_event = json.loads(tail.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    tail_event = None
                if isinstance(tail_event, dict):
                    os.write(descriptor, b"\n")
                else:
                    os.ftruncate(descriptor, truncate_at)

        # One append write plus fsync makes each event durable and prevents
        # interleaving. A torn trailing event is discarded before the next write.
        written = os.write(descriptor, payload)
        if written != len(payload):
            raise OSError("Incomplete import journal write")
        os.fsync(descriptor)
    finally:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        finally:
            os.close(descriptor)


def read_import_events(path: str | Path) -> list[dict[str, Any]]:
    """Read complete events; tolerate only an unterminated, torn final line."""
    journal_path = Path(path)
    if not journal_path.exists():
        return []

    raw = journal_path.read_bytes()
    if not raw:
        return []

    lines = raw.splitlines(keepends=True)
    events: list[dict[str, Any]] = []
    for index, raw_line in enumerate(lines):
        is_final = index == len(lines) - 1
        is_terminated = raw_line.endswith((b"\n", b"\r"))
        try:
            line = raw_line.decode("utf-8")
            value = json.loads(line)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            if is_final and not is_terminated:
                # os.write can be interrupted by process termination. Only an
                # incomplete trailing record is recoverable; earlier damage
                # must never be silently discarded because it may hide a
                # committed-batch checkpoint and corrupt resume accounting.
                break
            raise ValueError(
                f"Corrupt import journal at line {index + 1}"
            ) from exc

        if not isinstance(value, dict):
            raise ValueError(
                f"Invalid import journal event at line {index + 1}: expected an object"
            )
        events.append(value)

    return events
