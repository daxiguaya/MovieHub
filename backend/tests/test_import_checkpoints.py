"""Focused tests for safe import checkpoint restoration."""

import sqlite3

import pytest

from app.services.import_checkpoints import validate_resume_checkpoints


def _source(tmp_path):
    conn = sqlite3.connect(tmp_path / "scout.sqlite")
    conn.execute("CREATE TABLE item (douban_id TEXT, type TEXT)")
    conn.executemany(
        "INSERT INTO item VALUES (?, 'movie')",
        [("100",), ("200",), ("300",)],
    )
    return conn


def _checkpoint(batch, processed, last_id, imported, skipped, errors=0, total=3):
    return {
        "event": "batch_committed",
        "batch": batch,
        "processed": processed,
        "last_douban_id": last_id,
        "imported": imported,
        "skipped": skipped,
        "errors": errors,
        "total": total,
    }


def test_restores_a_valid_monotonic_checkpoint_history(tmp_path):
    source = _source(tmp_path)
    try:
        result = validate_resume_checkpoints(
            source,
            [
                _checkpoint(1, 2, "200", 2, 0),
                _checkpoint(2, 3, "300", 2, 1, errors=1),
            ],
            total=3,
        )
        assert result == {
            "processed": 3,
            "imported": 2,
            "skipped": 1,
            "errors": 1,
            "batch": 2,
            "last_douban_id": "300",
        }
    finally:
        source.close()


def test_rejects_discontinuous_batch_sequence(tmp_path):
    source = _source(tmp_path)
    try:
        with pytest.raises(ValueError, match="batch sequence"):
            validate_resume_checkpoints(
                source,
                [_checkpoint(2, 2, "200", 2, 0)],
                total=3,
            )
    finally:
        source.close()


def test_rejects_counters_that_do_not_sum_to_processed(tmp_path):
    source = _source(tmp_path)
    try:
        with pytest.raises(ValueError, match="do not add up"):
            validate_resume_checkpoints(
                source,
                [_checkpoint(1, 2, "200", 1, 0)],
                total=3,
            )
    finally:
        source.close()


def test_rejects_checkpoint_cursor_not_matching_source_order(tmp_path):
    source = _source(tmp_path)
    try:
        with pytest.raises(ValueError, match="cursor does not match"):
            validate_resume_checkpoints(
                source,
                [_checkpoint(1, 2, "300", 2, 0)],
                total=3,
            )
    finally:
        source.close()


def test_rejects_checkpoint_for_different_source_total(tmp_path):
    source = _source(tmp_path)
    try:
        with pytest.raises(ValueError, match="total does not match"):
            validate_resume_checkpoints(
                source,
                [_checkpoint(1, 2, "200", 2, 0, total=4)],
                total=3,
            )
    finally:
        source.close()


def test_rejects_error_count_greater_than_skipped(tmp_path):
    source = _source(tmp_path)
    try:
        with pytest.raises(ValueError, match="errors exceed skipped"):
            validate_resume_checkpoints(
                source,
                [_checkpoint(1, 2, "200", 2, 0, errors=1)],
                total=3,
            )
    finally:
        source.close()
