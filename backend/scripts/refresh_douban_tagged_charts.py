"""Collect and atomically refresh both Douban tagged movie charts.

This is an explicit, one-shot operation. It obeys robots.txt, does not retry
403/429 responses, and writes neither chart unless both collections succeed.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from typing import Iterable

from app.adapters.douban_tagged_chart import (
    CHARTS,
    MAX_ITEMS,
    DoubanTaggedChartCollector,
)
from app.database import SessionLocal
from app.services.chart_import_service import chart_import_service
from scripts.db_backup import create_backup

DEFAULT_CHARTS = ("popular", "high-rated")


def collect_snapshots(
    snapshot_date: date,
    max_items: int = MAX_ITEMS,
    chart_keys: Iterable[str] = DEFAULT_CHARTS,
) -> list:
    """Collect every requested chart before any database write is attempted."""
    collector = DoubanTaggedChartCollector(max_items=max_items)
    snapshots = []
    for chart_key in chart_keys:
        if chart_key not in CHARTS:
            raise ValueError(f"Unsupported Douban chart: {chart_key}")
        snapshots.append(collector.collect(chart_key, snapshot_date))
    if not snapshots:
        raise ValueError("No Douban charts were selected")
    return snapshots


def refresh_charts(snapshot_date: date, max_items: int = MAX_ITEMS) -> dict:
    """Back up once, then import both snapshots in one all-or-nothing transaction."""
    snapshots = collect_snapshots(snapshot_date, max_items=max_items)

    # The backup is intentionally created only after both remote collections
    # have completed successfully. A blocked/failed collection leaves the DB
    # and its backups untouched.
    backup_path = create_backup()
    with SessionLocal() as db:
        imported = chart_import_service.import_snapshots(db, snapshots)

    return {
        "success": True,
        "snapshot_date": snapshot_date.isoformat(),
        "backup": str(backup_path),
        "charts": [
            {"slug": snapshot.slug, "count": len(snapshot.movies)}
            for snapshot in snapshots
        ],
        "import": imported,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Refresh Douban popular and high-rated movie charts together. "
            "Checks robots.txt and stops on access/rate-limit errors."
        )
    )
    parser.add_argument(
        "--date",
        default=date.today().isoformat(),
        help="Snapshot date in YYYY-MM-DD format (default: today)",
    )
    parser.add_argument(
        "--max-items",
        type=int,
        default=MAX_ITEMS,
        help=f"Maximum movies per chart (1-500; default {MAX_ITEMS})",
    )
    args = parser.parse_args()

    try:
        snapshot_date = date.fromisoformat(args.date)
        if not 1 <= args.max_items <= 500:
            raise ValueError("--max-items must be between 1 and 500")
        result = refresh_charts(snapshot_date, args.max_items)
    except Exception as exc:
        print(
            json.dumps(
                {
                    "success": False,
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                    "database_written": False,
                },
                ensure_ascii=False,
                indent=2,
            ),
            file=sys.stderr,
        )
        return 1

    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
