-- MovieHub migration 002: durable Scout import batch receipts.
-- Each receipt is committed in the same transaction as its imported movie rows.

BEGIN IMMEDIATE;

CREATE TABLE import_batch_receipts (
    id INTEGER PRIMARY KEY,
    run_id VARCHAR(64) NOT NULL,
    batch_number INTEGER NOT NULL,
    source_fingerprint VARCHAR(64) NOT NULL,
    processed INTEGER NOT NULL,
    total INTEGER NOT NULL,
    imported INTEGER NOT NULL,
    skipped INTEGER NOT NULL,
    errors INTEGER NOT NULL,
    last_douban_id VARCHAR(32) NOT NULL,
    error_records TEXT NOT NULL DEFAULT '[]',
    committed_at VARCHAR(32) NOT NULL,
    CONSTRAINT uq_import_batch_receipts_run_batch UNIQUE (run_id, batch_number),
    CONSTRAINT ck_import_batch_receipts_batch CHECK (batch_number >= 1),
    CONSTRAINT ck_import_batch_receipts_processed CHECK (processed >= 1 AND processed <= total),
    CONSTRAINT ck_import_batch_receipts_total CHECK (total >= 1),
    CONSTRAINT ck_import_batch_receipts_counters CHECK (imported >= 0 AND skipped >= 0 AND errors >= 0),
    CONSTRAINT ck_import_batch_receipts_accounting CHECK (processed = imported + skipped),
    CONSTRAINT ck_import_batch_receipts_errors CHECK (errors <= skipped)
);
CREATE INDEX ix_import_batch_receipts_run_id
    ON import_batch_receipts(run_id, batch_number);

INSERT INTO schema_migrations(version, name, applied_at)
VALUES (2, 'durable_import_batch_receipts', strftime('%Y-%m-%dT%H:%M:%fZ', 'now'));

COMMIT;
