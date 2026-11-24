"""Read-only import history aggregation tests."""

import json

from app.services.import_history import read_import_run_history, summarize_import_events


def test_history_aggregates_checkpoint_and_terminal_counters():
    events = [
        {
            "event": "run_started", "run_id": "run-a",
            "source_path": "/imports/scout.sqlite", "force_full": False,
            "source_fingerprint": "abc", "total": 5,
            "started_at": "2026-11-23T10:00:00",
        },
        {
            "event": "batch_committed", "run_id": "run-a", "batch": 1,
            "processed": 3, "total": 5, "imported": 2, "skipped": 1,
            "errors": 0, "last_douban_id": "1003",
            "committed_at": "2026-11-23T10:01:00",
        },
        {
            "event": "run_completed", "run_id": "run-a",
            "processed": 5, "total": 5, "imported": 3, "skipped": 2,
            "errors": 0, "batches": 2,
            "completed_at": "2026-11-23T10:02:00",
        },
    ]

    [summary] = summarize_import_events(events)
    assert summary["status"] == "completed"
    assert summary["source_path"] == "/imports/scout.sqlite"
    assert summary["processed"] == 5
    assert summary["imported"] == 3
    assert summary["skipped"] == 2
    assert summary["batches"] == 2
    assert summary["last_douban_id"] == "1003"
    assert summary["completed_at"] == "2026-11-23T10:02:00"


def test_history_distinguishes_failed_resumed_and_incomplete_runs():
    events = [
        {"event": "run_started", "run_id": "failed", "total": 8,
         "started_at": "2026-11-23T10:00:00"},
        {"event": "batch_committed", "run_id": "failed", "batch": 1,
         "processed": 4, "total": 8, "imported": 4, "skipped": 0,
         "errors": 0, "last_douban_id": "4"},
        {"event": "run_failed", "run_id": "failed", "committed_batches": 1,
         "failed_at": "2026-11-23T10:01:00"},
        {"event": "run_resumed", "run_id": "failed",
         "resumed_at": "2026-11-23T10:02:00"},
        {"event": "run_started", "run_id": "incomplete", "total": 2,
         "started_at": "2026-11-23T11:00:00"},
    ]

    summaries = {item["run_id"]: item for item in summarize_import_events(events)}
    assert summaries["failed"]["status"] == "running"
    assert summaries["failed"]["processed"] == 4
    assert summaries["failed"]["resume_count"] == 1
    assert summaries["incomplete"]["status"] == "incomplete"


def test_history_ignores_torn_final_line_and_can_filter_run(tmp_path):
    journal = tmp_path / "import-journal.jsonl"
    journal.write_text(
        json.dumps({
            "event": "run_started", "run_id": "one",
            "started_at": "2026-11-23T10:00:00",
        }) + "\n"
        + json.dumps({
            "event": "run_started", "run_id": "two",
            "started_at": "2026-11-23T11:00:00",
        }) + "\n"
        + '{"event":"batch_committed"',
        encoding="utf-8",
    )

    runs = read_import_run_history(journal)
    assert [item["run_id"] for item in runs] == ["two", "one"]
    [selected] = read_import_run_history(journal, run_id="one")
    assert selected["status"] == "incomplete"
    assert read_import_run_history(journal, run_id="missing") == []
