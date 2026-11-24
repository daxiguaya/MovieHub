"""Durable per-record Scout import failure manifest tests."""

import json
import os

from app.services.import_errors import (
    append_import_errors,
    get_import_error_path,
    read_import_errors,
)


def test_error_manifest_is_durable_filtered_and_deduplicated_on_replay(tmp_path):
    journal = tmp_path / "moviehub.sqlite.import-journal.jsonl"
    errors = [
        {
            "run_id": "run-1", "batch": 2, "douban_id": "12345",
            "title": "Example Movie", "error_type": "IntegrityError",
            "error_message": "unique constraint failed",
            "occurred_at": "2026-11-23T12:00:00",
        }
    ]

    append_import_errors(journal, errors)
    # Simulate replay after the manifest append but before the journal checkpoint.
    append_import_errors(journal, errors)
    append_import_errors(journal, [{
        **errors[0], "run_id": "run-2", "douban_id": "67890"
    }])

    manifest = get_import_error_path(journal)
    assert manifest.exists()
    assert os.stat(manifest).st_mode & 0o777 == 0o600
    assert len(read_import_errors(journal)) == 2
    [one] = read_import_errors(journal, run_id="run-1")
    assert one["douban_id"] == "12345"
    assert one["batch"] == 2
    assert one["error_message"] == "unique constraint failed"


def test_error_manifest_ignores_torn_trailing_line(tmp_path):
    journal = tmp_path / "moviehub.sqlite.import-journal.jsonl"
    append_import_errors(journal, [{
        "run_id": "run-1", "batch": 1, "douban_id": "123",
        "title": "Title", "error_type": "ValueError",
        "error_message": "bad value", "occurred_at": "2026-11-23T12:00:00",
    }])
    manifest = get_import_error_path(journal)
    with manifest.open("a", encoding="utf-8") as target:
        target.write('{"event":"record_error"')

    assert len(read_import_errors(journal, run_id="run-1")) == 1
