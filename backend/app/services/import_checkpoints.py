"""Validation of durable batch checkpoints before a resumed import."""

import sqlite3
from typing import Any


def validate_resume_checkpoints(
    source_conn: sqlite3.Connection,
    checkpoints: list[dict[str, Any]],
    total: int,
) -> dict[str, Any]:
    """Validate journal counters and prove the final cursor matches source order."""
    previous = {"batch": 0, "processed": 0, "imported": 0, "skipped": 0, "errors": 0}
    previous_id: str | None = None

    for index, event in enumerate(checkpoints, start=1):
        if event.get("event") != "batch_committed":
            raise ValueError(f"Invalid checkpoint event at position {index}")

        values: dict[str, int] = {}
        for key in ("batch", "processed", "total", "imported", "skipped", "errors"):
            value = event.get(key)
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise ValueError(f"Import checkpoint has invalid {key} at position {index}")
            values[key] = value

        if values["batch"] != index:
            raise ValueError("Import checkpoint batch sequence is discontinuous")
        if values["total"] != total:
            raise ValueError("Import checkpoint total does not match the source snapshot")
        if not previous["processed"] < values["processed"] <= total:
            raise ValueError("Import checkpoint processed count is not strictly increasing")
        if values["processed"] != values["imported"] + values["skipped"]:
            raise ValueError("Import checkpoint counters do not add up to processed")
        if values["errors"] > values["skipped"]:
            raise ValueError("Import checkpoint errors exceed skipped records")
        if values["imported"] < previous["imported"] or values["skipped"] < previous["skipped"]:
            raise ValueError("Import checkpoint counters moved backwards")
        if values["errors"] < previous["errors"]:
            raise ValueError("Import checkpoint error count moved backwards")

        last_id = event.get("last_douban_id")
        if not isinstance(last_id, str) or not last_id:
            raise ValueError(f"Import checkpoint has invalid last_douban_id at position {index}")
        if previous_id is not None and last_id <= previous_id:
            raise ValueError("Import checkpoint source cursor is not strictly increasing")

        previous = values
        previous_id = last_id

    if not checkpoints:
        return {
            "processed": 0,
            "imported": 0,
            "skipped": 0,
            "errors": 0,
            "batch": 0,
            "last_douban_id": None,
        }

    # Validate the actual resume cursor once, after checking all journal
    # counters. Repeated OFFSET scans for every batch would become quadratic
    # for large catalogues.
    source_row = source_conn.execute(
        """
        SELECT douban_id
        FROM item
        WHERE type IN ('movie', 'tv')
        ORDER BY douban_id
        LIMIT 1 OFFSET ?
        """,
        (previous["processed"] - 1,),
    ).fetchone()
    if source_row is None or str(source_row[0]) != previous_id:
        raise ValueError("Import checkpoint cursor does not match the source snapshot")

    return {
        "processed": previous["processed"],
        "imported": previous["imported"],
        "skipped": previous["skipped"],
        "errors": previous["errors"],
        "batch": previous["batch"],
        "last_douban_id": previous_id,
    }
