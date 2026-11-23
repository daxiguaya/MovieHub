"""Recovery helpers for transactionally committed Scout import receipts."""

import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import ImportBatchReceipt
from app.services.import_journal import append_import_event, read_import_events
from app.services.import_errors import append_import_errors
from app.services.import_checkpoints import validate_resume_checkpoints


def receipt_event(receipt: ImportBatchReceipt) -> dict[str, Any]:
    return {
        "event": "batch_committed",
        "run_id": receipt.run_id,
        "batch": receipt.batch_number,
        "processed": receipt.processed,
        "total": receipt.total,
        "last_douban_id": receipt.last_douban_id,
        "imported": receipt.imported,
        "skipped": receipt.skipped,
        "errors": receipt.errors,
        "committed_at": receipt.committed_at,
    }


def restore_from_batch_receipts(
    db: Session,
    source_conn: Any,
    journal_path: str,
    run_id: str,
    source_fingerprint: str,
    total: int,
) -> dict[str, Any]:
    """Treat target-DB receipts as authoritative and repair a lagging JSONL journal."""
    receipts = db.scalars(
        select(ImportBatchReceipt)
        .where(ImportBatchReceipt.run_id == run_id)
        .order_by(ImportBatchReceipt.batch_number)
    ).all()

    receipt_events = []
    for receipt in receipts:
        if receipt.source_fingerprint != source_fingerprint:
            raise ValueError("Import batch receipt source fingerprint does not match")
        receipt_events.append(receipt_event(receipt))

    restored = validate_resume_checkpoints(source_conn, receipt_events, total)
    journal_events = [
        event for event in read_import_events(journal_path)
        if event.get("run_id") == run_id
    ]
    journal_checkpoints = [
        event for event in journal_events
        if event.get("event") == "batch_committed"
    ]
    if len(journal_checkpoints) > len(receipt_events):
        raise ValueError("Import journal contains checkpoints without database receipts")

    compare_fields = (
        "batch", "processed", "total", "last_douban_id",
        "imported", "skipped", "errors",
    )
    for index, journal_event in enumerate(journal_checkpoints):
        receipt_event_value = receipt_events[index]
        if any(journal_event.get(key) != receipt_event_value.get(key) for key in compare_fields):
            raise ValueError("Import journal checkpoint conflicts with its database receipt")

    # Recover error details and checkpoints committed to SQLite before a crash
    # interrupted their corresponding append-only JSONL writes.
    for receipt, event in zip(receipts, receipt_events):
        try:
            error_records = json.loads(receipt.error_records)
        except (TypeError, json.JSONDecodeError) as exc:
            raise ValueError(
                f"Invalid error manifest payload in batch receipt {receipt.batch_number}"
            ) from exc
        if not isinstance(error_records, list) or any(not isinstance(item, dict) for item in error_records):
            raise ValueError(
                f"Invalid error manifest payload in batch receipt {receipt.batch_number}"
            )
        if error_records:
            append_import_errors(journal_path, error_records)

    for event in receipt_events[len(journal_checkpoints):]:
        append_import_event(journal_path, event)

    return restored
