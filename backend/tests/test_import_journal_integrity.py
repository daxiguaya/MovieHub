"""Integrity checks for the durable import journal reader."""

import json

import pytest

from app.services.import_journal import read_import_events


def test_reader_ignores_only_a_torn_final_line(tmp_path):
    path = tmp_path / "import.jsonl"
    first = {"event": "run_started", "run_id": "run-1"}
    path.write_bytes(
        (json.dumps(first) + "\n").encode("utf-8")
        + b'{"event":"batch_committed","run_id":'
    )

    assert read_import_events(path) == [first]


def test_reader_rejects_corruption_before_the_final_line(tmp_path):
    path = tmp_path / "import.jsonl"
    path.write_text(
        '{"event":"run_started","run_id":"run-1"}\n'
        '{"event":broken}\n'
        '{"event":"batch_committed"}\n',
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="line 2"):
        read_import_events(path)


def test_reader_rejects_malformed_final_line_with_newline(tmp_path):
    path = tmp_path / "import.jsonl"
    path.write_text(
        '{"event":"run_started","run_id":"run-1"}\n'
        '{"event":broken}\n',
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="line 2"):
        read_import_events(path)


def test_reader_rejects_non_object_journal_events(tmp_path):
    path = tmp_path / "import.jsonl"
    path.write_text('[]\n', encoding="utf-8")

    with pytest.raises(ValueError, match="line 1"):
        read_import_events(path)


def test_append_repairs_a_torn_final_line_before_writing_next_event(tmp_path):
    from app.services.import_journal import append_import_event

    path = tmp_path / "import.jsonl"
    first = {"event": "run_started", "run_id": "run-1"}
    recovered = {"event": "run_resumed", "run_id": "run-1"}
    path.write_bytes(
        (json.dumps(first) + "\n").encode("utf-8")
        + b'{"event":"batch_committed","run_id":'
    )

    append_import_event(path, recovered)

    assert read_import_events(path) == [first, recovered]
    assert path.stat().st_mode & 0o777 == 0o600
