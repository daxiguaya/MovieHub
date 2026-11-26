"""Manifest-driven importer for future Douban annual chart snapshots.

The collector is deliberately separate: once Douban publishes a new annual
roundup, a reviewed source-specific adapter can emit normalized JSON files.
This command validates the complete declared batch and imports it atomically.
"""
import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path
from typing import Any

from app.adapters.local_import import LocalImportAdapter
from app.database import SessionLocal, database_is_ready
from app.schemas_chart_import import ChartSnapshotImport
from app.services.chart_import_service import chart_import_service


def load_annual_batch(
    input_dir: str | Path,
    snapshot_date: date,
    manifest_path: str | Path,
) -> list[ChartSnapshotImport]:
    """Load and cross-validate every chart declared by a year manifest."""
    directory = Path(input_dir).expanduser()
    if not directory.exists() or not directory.is_dir():
        raise ValueError("Annual chart input directory does not exist")

    manifest_file = Path(manifest_path).expanduser()
    if not manifest_file.is_file():
        raise ValueError("Annual chart manifest does not exist")
    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        raise ValueError("Annual chart manifest must be a JSON object")

    period = str(manifest.get("period", "")).strip()
    if not re.fullmatch(r"20[0-9]{2}", period):
        raise ValueError("Manifest period must be a four-digit year (2000-2099)")
    charts = manifest.get("charts")
    if not isinstance(charts, list) or not charts:
        raise ValueError("Manifest charts must be a non-empty array")

    expected: dict[str, dict[str, str]] = {}
    for item in charts:
        if not isinstance(item, dict):
            raise ValueError("Every manifest chart entry must be an object")
        slug = str(item.get("slug", "")).strip().lower()
        name = str(item.get("name", "")).strip()
        media_type = str(item.get("media_type", "")).strip()
        if not re.fullmatch(rf"annual-{period}(?:-[a-z0-9]+)*", slug):
            raise ValueError(
                f"Chart slug {slug!r} must start with annual-{period}"
            )
        if not name or len(name) > 160:
            raise ValueError(f"Chart {slug} requires a name (max 160 characters)")
        if media_type not in ("movie", "tv"):
            raise ValueError(f"Chart {slug} media_type must be 'movie' or 'tv'")
        if slug in expected:
            raise ValueError(f"Duplicate chart slug in manifest: {slug}")
        expected[slug] = {"name": name, "media_type": media_type}

    snapshots: list[ChartSnapshotImport] = []
    for slug, config in expected.items():
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
        if snapshot.name != config["name"]:
            raise ValueError(
                f"{path.name} declares name {snapshot.name!r}; expected {config['name']!r}"
            )
        if snapshot.source != "douban":
            raise ValueError(f"{path.name} must declare source='douban'")
        if snapshot.category != "annual" or snapshot.period != period:
            raise ValueError(
                f"{path.name} must declare category='annual' and period={period!r}"
            )
        if any(movie.type != config["media_type"] for movie in snapshot.movies):
            raise ValueError(
                f"{path.name} contains an entry with the wrong media type"
            )
        ranks = [movie.rank for movie in snapshot.movies]
        if not ranks or ranks != sorted(ranks):
            raise ValueError(f"{path.name} ranks must be non-empty and ascending")
        snapshots.append(snapshot)

    return snapshots


def import_annual_batch(
    input_dir: str | Path,
    snapshot_date: date,
    manifest_path: str | Path,
    *,
    apply: bool = False,
) -> dict[str, Any]:
    """Validate a declared annual batch; persist only when apply=True."""
    snapshots = load_annual_batch(input_dir, snapshot_date, manifest_path)
    summary: dict[str, Any] = {
        "valid": True,
        "applied": False,
        "period": snapshots[0].period,
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
            "Validate a manifest-declared annual chart batch. "
            "Dry-run is the default; --apply is required to write."
        )
    )
    parser.add_argument("--input-dir", required=True)
    parser.add_argument("--manifest", required=True, help="JSON manifest declaring period and charts")
    parser.add_argument("--date", required=True, help="Snapshot date in YYYY-MM-DD format")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    try:
        snapshot_date = date.fromisoformat(args.date)
        result = import_annual_batch(
            args.input_dir,
            snapshot_date,
            args.manifest,
            apply=args.apply,
        )
    except Exception as exc:
        print(f"Annual chart import failed: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
