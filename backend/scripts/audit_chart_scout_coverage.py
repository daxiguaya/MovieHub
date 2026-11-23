"""Read-only audit of normalized chart metadata coverage in a Douban Scout DB."""

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any

from app.adapters.local_import import LocalImportAdapter
from app.services.import_service import ImportService


SOURCE_COLUMNS = """
SELECT douban_id, imdb_id, douban_title, year, rating, raw_data, type, update_time
FROM item
WHERE douban_id IN ({placeholders}) AND type IN ('movie', 'tv')
"""


def _present(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple, set, dict)):
        return bool(value)
    return True


def audit_chart_snapshots(
    snapshot_paths: list[str | Path],
    scout_db_path: str | Path,
) -> dict[str, Any]:
    """Compare chart snapshot IDs with Scout rows without writing to either DB."""
    snapshots = [
        LocalImportAdapter().load_snapshot(path)
        for path in snapshot_paths
    ]
    source_path = Path(scout_db_path).expanduser().resolve()
    if not source_path.is_file():
        raise FileNotFoundError(f"Scout database not found: {source_path}")

    ids = sorted({
        item.douban_id
        for snapshot in snapshots
        for item in snapshot.movies
    })
    if not ids:
        raise ValueError("No Douban IDs found in the supplied chart snapshots")

    uri = source_path.as_uri() + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        ImportService._validate_source(conn)
        rows: dict[str, sqlite3.Row] = {}
        # Keep each query comfortably below SQLite's host-parameter limit.
        for start in range(0, len(ids), 400):
            batch = ids[start:start + 400]
            placeholders = ",".join("?" for _ in batch)
            query = SOURCE_COLUMNS.format(placeholders=placeholders)
            for row in conn.execute(query, batch):
                rows[str(row["douban_id"])] = row

        extractor = ImportService()
        field_names = (
            "year",
            "rating",
            "rating_count",
            "original_title",
            "overview",
            "douban_url",
            "directors",
            "actors",
            "genres",
            "regions",
            "posters",
        )
        reports = []
        for snapshot in snapshots:
            matched = [
                (item, rows[item.douban_id])
                for item in snapshot.movies
                if item.douban_id in rows
            ]
            field_counts = {name: 0 for name in field_names}
            type_mismatches = []
            for item, row in matched:
                detail = extractor._extract_detail(row["raw_data"])
                values = {
                    "year": row["year"],
                    "rating": row["rating"],
                    **detail,
                }
                for name in field_names:
                    if _present(values.get(name)):
                        field_counts[name] += 1
                if row["type"] != item.type:
                    type_mismatches.append({
                        "douban_id": item.douban_id,
                        "title": item.title,
                        "chart_type": item.type,
                        "scout_type": row["type"],
                    })

            missing_ids = [
                item.douban_id
                for item in snapshot.movies
                if item.douban_id not in rows
            ]
            reports.append({
                "slug": snapshot.slug,
                "snapshot_date": snapshot.snapshot_date.isoformat(),
                "chart_type": sorted({item.type for item in snapshot.movies}),
                "chart_items": len(snapshot.movies),
                "scout_matches": len(matched),
                "scout_missing": len(missing_ids),
                "missing_douban_ids": missing_ids,
                "type_mismatch_count": len(type_mismatches),
                "type_mismatches": type_mismatches,
                "field_coverage": {
                    name: {
                        "present": count,
                        "matched_total": len(matched),
                        "percent": round(count * 100 / len(matched), 1) if matched else 0.0,
                    }
                    for name, count in field_counts.items()
                },
            })

        total_items = sum(report["chart_items"] for report in reports)
        total_matches = sum(report["scout_matches"] for report in reports)
        total_mismatches = sum(report["type_mismatch_count"] for report in reports)
        return {
            "read_only": True,
            "scout_database": str(source_path),
            "charts": reports,
            "summary": {
                "chart_count": len(reports),
                "chart_items": total_items,
                "scout_matches": total_matches,
                "scout_missing": total_items - total_matches,
                "type_mismatches": total_mismatches,
            },
            "next_step": (
                "Review coverage and type mismatches. This audit does not import "
                "data or modify Scout or MovieHub."
            ),
        }
    finally:
        conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Read-only coverage audit between normalized chart JSON snapshots "
            "and a Douban Scout SQLite database."
        )
    )
    parser.add_argument(
        "--scout-db",
        required=True,
        help="Path to a consistent read-only Scout SQLite copy",
    )
    parser.add_argument(
        "--input",
        action="append",
        required=True,
        help="Normalized chart JSON file; repeat once per chart",
    )
    args = parser.parse_args()
    try:
        result = audit_chart_snapshots(args.input, args.scout_db)
    except Exception as exc:
        print(f"Scout chart coverage audit failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
