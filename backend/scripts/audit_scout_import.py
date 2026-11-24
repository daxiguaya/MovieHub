"""Read-only whole-catalogue quality audit for a Douban Scout SQLite DB."""

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any

from app.services.import_service import ImportService


FIELD_NAMES = (
    "year", "rating", "rating_count", "original_title", "overview",
    "douban_url", "directors", "actors", "genres", "regions", "posters",
)


def _present(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple, set, dict)):
        return bool(value)
    return True


def audit_scout_database(scout_db_path: str | Path) -> dict[str, Any]:
    """Inspect every movie/TV row in one read-only SQLite snapshot."""
    path = Path(scout_db_path).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"Scout database not found: {path}")

    conn = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=30)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("BEGIN")
        ImportService._validate_source(conn)
        type_counts = {
            row["type"]: row["count"]
            for row in conn.execute(
                "SELECT type, COUNT(*) AS count FROM item "
                "WHERE type IN ('movie', 'tv') GROUP BY type"
            )
        }
        total = sum(type_counts.values())
        if total == 0:
            raise ValueError("Scout database contains no movie or TV records")

        identity = conn.execute(
            """
            SELECT
                SUM(CASE WHEN douban_id IS NULL
                              OR trim(CAST(douban_id AS TEXT)) = ''
                              OR trim(CAST(douban_id AS TEXT)) GLOB '*[^0-9]*'
                              OR douban_title IS NULL
                              OR trim(douban_title) = ''
                         THEN 1 ELSE 0 END) AS invalid_rows
            FROM item WHERE type IN ('movie', 'tv')
            """
        ).fetchone()
        duplicate = conn.execute(
            """
            SELECT COUNT(*) AS duplicate_ids, COALESCE(SUM(row_count), 0) AS duplicate_rows
            FROM (
                SELECT douban_id, COUNT(*) AS row_count
                FROM item
                WHERE type IN ('movie', 'tv') AND douban_id IS NOT NULL
                GROUP BY douban_id HAVING COUNT(*) > 1
            )
            """
        ).fetchone()

        field_counts = {name: 0 for name in FIELD_NAMES}
        invalid_ratings = 0
        invalid_years = 0
        malformed_raw_data = 0
        extractor = ImportService()
        cursor = conn.execute(
            "SELECT year, rating, raw_data FROM item "
            "WHERE type IN ('movie', 'tv') ORDER BY douban_id"
        )
        for row in cursor:
            year = extractor._safe_int(row["year"])
            if year is not None and not 1870 <= year <= 2200:
                invalid_years += 1
            if row["year"] is not None and (
                year is None or not 1870 <= year <= 2200
            ):
                invalid_years += 0 if year is not None else 1

            rating = extractor._safe_rating(row["rating"])
            if row["rating"] is not None and rating is None:
                invalid_ratings += 1

            raw = row["raw_data"]
            if raw:
                try:
                    parsed = json.loads(raw)
                    if not isinstance(parsed, dict):
                        malformed_raw_data += 1
                except (TypeError, json.JSONDecodeError):
                    malformed_raw_data += 1
            detail = extractor._extract_detail(raw)
            values = {
                "year": year if year is not None and 1870 <= year <= 2200 else None,
                "rating": rating,
                **detail,
            }
            for name in FIELD_NAMES:
                if _present(values.get(name)):
                    field_counts[name] += 1

        return {
            "read_only": True,
            "scout_database": str(path),
            "snapshot_consistent": True,
            "summary": {
                "total_records": total,
                "media_type_counts": {
                    "movie": type_counts.get("movie", 0),
                    "tv": type_counts.get("tv", 0),
                },
                "invalid_identity_rows": identity["invalid_rows"] or 0,
                "duplicate_douban_ids": duplicate["duplicate_ids"],
                "rows_in_duplicate_groups": duplicate["duplicate_rows"],
                "invalid_ratings": invalid_ratings,
                "invalid_years": invalid_years,
                "malformed_raw_data": malformed_raw_data,
                "field_coverage": {
                    name: {
                        "present": count,
                        "total": total,
                        "percent": round(count * 100 / total, 1),
                    }
                    for name, count in field_counts.items()
                },
            },
            "strict_gate": {
                "passed": not (identity["invalid_rows"] or duplicate["duplicate_ids"]),
                "blocking_issues": {
                    "invalid_identity_rows": identity["invalid_rows"] or 0,
                    "duplicate_douban_ids": duplicate["duplicate_ids"],
                },
                "note": "Numeric and raw_data anomalies are reported as warnings; identity defects block import.",
            },
        }
    finally:
        conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Read-only whole-catalogue quality audit for a Scout SQLite database."
    )
    parser.add_argument("--scout-db", required=True, help="Path to a consistent Scout SQLite copy")
    parser.add_argument("--strict", action="store_true", help="Exit 2 if invalid identities or duplicate Douban IDs exist")
    args = parser.parse_args()
    try:
        report = audit_scout_database(args.scout_db)
    except Exception as exc:
        print(f"Scout import audit failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if args.strict and not report["strict_gate"]["passed"]:
        print("Strict Scout import audit failed: identity defects or duplicate IDs found.", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
