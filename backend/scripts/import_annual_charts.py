"""Preflight and optionally import all four normalized 2025 annual charts.

The default mode is validation-only and never opens the MovieHub database.
Persistence requires the explicit --apply flag and is performed as one
all-or-nothing transaction by ChartImportService.import_snapshots().
"""
import argparse
import json
import sys
from datetime import date
from pathlib import Path
from typing import Any

from app.adapters.local_import import LocalImportAdapter
from app.adapters.douban_annual import ANNUAL_CHARTS
from app.database import SessionLocal, database_is_ready
from app.schemas_chart_import import ChartSnapshotImport
from app.services.chart_import_service import chart_import_service


def load_annual_batch(
    input_dir: str | Path,
    snapshot_date: date,
) -> list[ChartSnapshotImport]:
    """Load and cross-validate the complete four-file annual chart batch."""
    directory = Path(input_dir).expanduser()
    if not directory.exists() or not directory.is_dir():
        raise ValueError("Annual chart input directory does not exist")

    snapshots: list[ChartSnapshotImport] = []
    for slug, config in ANNUAL_CHARTS.items():
        path = directory / f"{slug}-{snapshot_date.isoformat()}.json"
        if not path.is_file():
            raise ValueError(f"Missing annual chart snapshot: {path.name}")

        snapshot = LocalImportAdapter().load_snapshot(path)
        if snapshot.slug != slug:
            raise ValueError(
                f"{path.name} declares slug {snapshot.slug!r}; expected {slug!r}"
            )
        if snapshot.snapshot_date != snapshot_date:
            raise ValueError(
                f"{path.name} has snapshot_date {snapshot.snapshot_date}; "
                f"expected {snapshot_date}"
            )
        if snapshot.source != "douban":
            raise ValueError(f"{path.name} must declare source='douban'")
        if snapshot.category != "annual" or snapshot.period != "2025":
            raise ValueError(
                f"{path.name} must declare category='annual' and period='2025'"
            )
        if any(movie.type != config["media_type"] for movie in snapshot.movies):
            raise ValueError(
                f"{path.name} contains an entry with the wrong media type"
            )

        ranks = [movie.rank for movie in snapshot.movies]
        if ranks != sorted(ranks):
            raise ValueError(f"{path.name} ranks must be in ascending order")

        snapshots.append(snapshot)

    if len(snapshots) != len(ANNUAL_CHARTS):
        raise ValueError("Annual batch must contain exactly four configured charts")

    return snapshots


def import_annual_batch(
    input_dir: str | Path,
    snapshot_date: date,
    *,
    apply: bool = False,
) -> dict[str, Any]:
    """Validate the batch; persist only when apply=True."""
    snapshots = load_annual_batch(input_dir, snapshot_date)
    summary = {
        "valid": True,
        "applied": False,
        "snapshot_date": snapshot_date.isoformat(),
        "chart_count": len(snapshots),
        "charts": [
            {
                "slug": snapshot.slug,
                "name": snapshot.name,
                "item_count": len(snapshot.movies),
                "first_rank": snapshot.movies[0].rank,
                "last_rank": snapshot.movies[-1].rank,
            }
            for snapshot in snapshots
        ],
    }

    if not apply:
        return summary

    if not database_is_ready():
        raise RuntimeError(
            "MovieHub database is not ready. Initialize the independent MovieHub database first."
        )

    with SessionLocal() as db:
        result = chart_import_service.import_snapshots(db, snapshots)

    summary["applied"] = True
    summary["import"] = result
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Validate the complete four-chart 2025 annual batch. "
            "Validation-only is the default; --apply is required to write."
        )
    )
    parser.add_argument("--input-dir", required=True, help="Directory containing the four JSON files")
    parser.add_argument("--date", required=True, help="Snapshot date in YYYY-MM-DD format")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Explicitly import all four snapshots in one database transaction",
    )
    args = parser.parse_args()

    try:
        snapshot_date = date.fromisoformat(args.date)
        result = import_annual_batch(
            args.input_dir,
            snapshot_date,
            apply=args.apply,
        )
    except Exception as exc:
        print(f"Annual chart import failed: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
