"""Schema-v2 migration coverage for atomic Scout import receipts."""

import sqlite3

from scripts.migrate import execute_migration


def test_v1_database_migrates_to_v2_with_receipt_constraints(tmp_path):
    backend_root = __import__("pathlib").Path(__file__).resolve().parents[1]
    database_path = tmp_path / "moviehub-v1.sqlite"
    initial_migration = backend_root / "migrations" / "001_moviehub_core.sql"
    receipt_migration = backend_root / "migrations" / "002_durable_import_batch_receipts.sql"

    with sqlite3.connect(database_path) as conn:
        conn.executescript(initial_migration.read_text(encoding="utf-8"))

    version = execute_migration(database_path, receipt_migration)
    assert version == 2

    with sqlite3.connect(database_path) as conn:
        assert conn.execute(
            "SELECT MAX(version) FROM schema_migrations"
        ).fetchone()[0] == 2
        columns = {
            row[1] for row in conn.execute(
                "PRAGMA table_info(import_batch_receipts)"
            )
        }
        assert {
            "run_id",
            "batch_number",
            "source_fingerprint",
            "processed",
            "total",
            "imported",
            "skipped",
            "errors",
            "last_douban_id",
            "error_records",
            "committed_at",
        }.issubset(columns)
        unique_indexes = conn.execute(
            "PRAGMA index_list(import_batch_receipts)"
        ).fetchall()
        assert any(row[2] for row in unique_indexes)

    assert list(tmp_path.glob("moviehub-v1.sqlite.pre-migration-*.bak"))
