"""Schema migration-chain coverage for atomic Scout import receipts."""

import sqlite3
from pathlib import Path

from scripts.migrate import execute_migration


def test_v1_database_migrates_to_v3_with_receipt_and_provenance_constraints(tmp_path):
    backend_root = Path(__file__).resolve().parents[1]
    database_path = tmp_path / "moviehub-v1.sqlite"
    initial_migration = backend_root / "migrations" / "001_moviehub_core.sql"
    latest_migration = backend_root / "migrations" / "003_movie_metadata_provenance.sql"

    with sqlite3.connect(database_path) as conn:
        conn.executescript(initial_migration.read_text(encoding="utf-8"))

    version = execute_migration(database_path, latest_migration)
    assert version == 3

    with sqlite3.connect(database_path) as conn:
        assert conn.execute(
            "SELECT MAX(version) FROM schema_migrations"
        ).fetchone()[0] == 3
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
        provenance_columns = {
            row[1] for row in conn.execute(
                "PRAGMA table_info(movie_metadata_provenance)"
            )
        }
        assert {
            "movie_id", "field_name", "source", "source_url",
            "observed_at", "value_sha256",
        }.issubset(provenance_columns)

    assert list(tmp_path.glob("moviehub-v1.sqlite.pre-migration-*.bak"))
