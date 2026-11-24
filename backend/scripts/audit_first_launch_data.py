"""Audit first-launch chart snapshots for dataset size and metadata coverage."""

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from app.adapters.local_import import LocalImportAdapter

REQUIRED_CHARTS = {"top250", "popular", "high-rated"}
COVERAGE_FIELDS = (
    "year",
    "rating",
    "rating_count",
    "original_title",
    "directors",
    "actors",
    "genres",
    "regions",
    "posters",
    "overview",
)


def summarize_snapshots(snapshots) -> dict[str, Any]:
    """Return a deterministic quality report without writing to any database."""
    chart_reports = []
    id_occurrences: Counter[str] = Counter()
    field_counts = Counter()
    total_items = 0
    errors: list[str] = []

    for snapshot in sorted(snapshots, key=lambda item: item.slug):
        items = snapshot.movies
        ranks = [item.rank for item in items]
        if ranks != sorted(ranks):
            errors.append(f"{snapshot.slug}: ranks are not sorted")
        if len(ranks) != len(set(ranks)):
            errors.append(f"{snapshot.slug}: duplicate ranks")
        for item in items:
            id_occurrences[item.douban_id] += 1
            for field in COVERAGE_FIELDS:
                value = getattr(item, field)
                present = bool(value) if isinstance(value, (list, str)) else value is not None
                if present:
                    field_counts[field] += 1
        total_items += len(items)
        chart_reports.append({
            "slug": snapshot.slug,
            "name": snapshot.name,
            "snapshot_date": snapshot.snapshot_date.isoformat(),
            "item_count": len(items),
            "first_rank": min(ranks) if ranks else None,
            "last_rank": max(ranks) if ranks else None,
        })

    slugs = {item["slug"] for item in chart_reports}
    missing_charts = sorted(REQUIRED_CHARTS - slugs)
    if missing_charts:
        errors.append("missing required first-launch charts: " + ", ".join(missing_charts))

    unique_movies = len(id_occurrences)
    duplicate_occurrences = sum(count - 1 for count in id_occurrences.values() if count > 1)
    coverage = {
        field: {
            "present": field_counts[field],
            "total": total_items,
            "percentage": round(field_counts[field] * 100 / total_items, 1) if total_items else 0.0,
        }
        for field in COVERAGE_FIELDS
    }
    return {
        "valid": not errors,
        "chart_count": len(chart_reports),
        "chart_item_count": total_items,
        "unique_movie_count": unique_movies,
        "cross_chart_duplicate_occurrences": duplicate_occurrences,
        "charts": chart_reports,
        "metadata_coverage": coverage,
        "errors": errors,
        "notes": [
            "Coverage measures source-provided fields; missing values are not inferred or fabricated.",
            "Cross-chart duplicates are expected and should resolve to one MovieHub movie per Douban ID.",
        ],
    }


def load_snapshots(input_dir: str | Path, snapshot_date: str):
    directory = Path(input_dir).expanduser()
    if not directory.is_dir():
        raise ValueError("Snapshot input directory does not exist")
    snapshots = []
    for path in sorted(directory.glob("*.json")):
        snapshot = LocalImportAdapter().load_snapshot(path)
        if snapshot.snapshot_date.isoformat() != snapshot_date:
            continue
        snapshots.append(snapshot)
    if not snapshots:
        raise ValueError(f"No normalized snapshots found for {snapshot_date}")
    return snapshots


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Audit first-launch chart size, overlap and metadata coverage."
    )
    parser.add_argument("--input-dir", required=True)
    parser.add_argument("--date", required=True, help="Snapshot date in YYYY-MM-DD format")
    args = parser.parse_args()
    try:
        report = summarize_snapshots(load_snapshots(args.input_dir, args.date))
    except Exception as exc:
        print(f"First-launch data audit failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
