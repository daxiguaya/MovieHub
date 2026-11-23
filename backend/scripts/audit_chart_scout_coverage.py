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
WHERE douban_id IN ({placeholders})
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
    chart_date_pairs = [
        (snapshot.slug, snapshot.snapshot_date)
        for snapshot in snapshots
    ]
    if len(chart_date_pairs) != len(set(chart_date_pairs)):
        raise ValueError("Duplicate chart/date snapshot supplied to Scout coverage audit")

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
        rows: dict[str, list[sqlite3.Row]] = {}
        # Keep each query comfortably below SQLite's host-parameter limit.
        # Do not filter by media type here: a matching ID with an unexpected
        # Scout type must be reported as a type mismatch, not as a missing ID.
        for start in range(0, len(ids), 400):
            batch = ids[start:start + 400]
            placeholders = ",".join("?" for _ in batch)
            query = SOURCE_COLUMNS.format(placeholders=placeholders)
            for row in conn.execute(query, batch):
                rows.setdefault(str(row["douban_id"]), []).append(row)

        unique_rows = {
            douban_id: matches[0]
            for douban_id, matches in rows.items()
            if len(matches) == 1
        }
        ambiguous_ids = {
            douban_id: len(matches)
            for douban_id, matches in rows.items()
            if len(matches) > 1
        }

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
        total_field_counts = {name: 0 for name in field_names}
        for snapshot in snapshots:
            matched = [
                (item, unique_rows[item.douban_id])
                for item in snapshot.movies
                if item.douban_id in unique_rows
            ]
            chart_ambiguous = [
                item.douban_id
                for item in snapshot.movies
                if item.douban_id in ambiguous_ids
            ]
            field_counts = {name: 0 for name in field_names}
            type_mismatches = []
            type_valid_matches = 0
            for item, row in matched:
                if row["type"] != item.type:
                    type_mismatches.append({
                        "douban_id": item.douban_id,
                        "title": item.title,
                        "chart_type": item.type,
                        "scout_type": row["type"],
                    })
                    continue

                # ID equality alone is not enough: metadata from a different
                # media type must not inflate coverage for this chart.
                type_valid_matches += 1
                detail = extractor._extract_detail(row["raw_data"])
                values = {
                    "year": row["year"],
                    "rating": row["rating"],
                    **detail,
                }
                for name in field_names:
                    if _present(values.get(name)):
                        field_counts[name] += 1

            for name in field_names:
                total_field_counts[name] += field_counts[name]

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
                "scout_type_valid_matches": type_valid_matches,
                "scout_missing": len(missing_ids),
                "missing_douban_ids": missing_ids,
                "scout_ambiguous": len(chart_ambiguous),
                "ambiguous_douban_ids": chart_ambiguous,
                "type_mismatch_count": len(type_mismatches),
                "type_mismatches": type_mismatches,
                "field_coverage": {
                    name: {
                        "present": count,
                        "matched_total": type_valid_matches,
                        "percent": round(count * 100 / type_valid_matches, 1) if type_valid_matches else 0.0,
                    }
                    for name, count in field_counts.items()
                },
            })

        total_items = sum(report["chart_items"] for report in reports)
        total_matches = sum(report["scout_matches"] for report in reports)
        total_type_valid_matches = sum(report["scout_type_valid_matches"] for report in reports)
        total_mismatches = sum(report["type_mismatch_count"] for report in reports)
        total_ambiguous = sum(report["scout_ambiguous"] for report in reports)
        return {
            "read_only": True,
            "scout_database": str(source_path),
            "charts": reports,
            "summary": {
                "chart_count": len(reports),
                "chart_items": total_items,
                "scout_matches": total_matches,
                "scout_type_valid_matches": total_type_valid_matches,
                "scout_missing": sum(report["scout_missing"] for report in reports),
                "scout_ambiguous": total_ambiguous,
                "type_mismatches": total_mismatches,
                "field_coverage": {
                    name: {
                        "present": count,
                        "matched_total": total_type_valid_matches,
                        "percent": round(count * 100 / total_type_valid_matches, 1) if total_type_valid_matches else 0.0,
                    }
                    for name, count in total_field_counts.items()
                },
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
    parser.add_argument(
        "--strict",
        action="store_true",
        help=(
            "Return exit code 2 when any chart item is missing, ambiguous, "
            "or matched to a Scout row with the wrong media type"
        ),
    )
    args = parser.parse_args()
    try:
        result = audit_chart_snapshots(args.input, args.scout_db)
    except Exception as exc:
        print(f"Scout chart coverage audit failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if args.strict:
        summary = result["summary"]
        quality_issues = {
            "missing": summary["scout_missing"],
            "ambiguous": summary["scout_ambiguous"],
            "type_mismatches": summary["type_mismatches"],
        }
        if any(quality_issues.values()):
            print(
                "Strict audit failed: "
                + ", ".join(f"{name}={count}" for name, count in quality_issues.items()),
                file=sys.stderr,
            )
            return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
