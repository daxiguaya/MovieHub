"""Collect all four official Douban 2025 annual chart snapshots to local JSON."""
import argparse
import json
import sys
from datetime import date
from pathlib import Path

from app.adapters.douban_annual import (
    ANNUAL_CHARTS,
    DoubanAnnualChartCollector,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Fetch Douban's official 2025 annual roundup once and write four "
            "separate normalized JSON snapshots. No database is opened."
        )
    )
    parser.add_argument("--date", required=True, help="Capture date in YYYY-MM-DD format")
    parser.add_argument(
        "--output-dir",
        required=True,
        help="Directory for the four normalized JSON files",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Allow replacing existing output files",
    )
    args = parser.parse_args()

    try:
        capture_date = date.fromisoformat(args.date)
        output_dir = Path(args.output_dir).expanduser()
        targets = {
            slug: output_dir / f"{slug}-{capture_date.isoformat()}.json"
            for slug in ANNUAL_CHARTS
        }
        existing = [str(path) for path in targets.values() if path.exists()]
        if existing and not args.overwrite:
            raise FileExistsError(
                "Output file(s) already exist; pass --overwrite to replace: "
                + ", ".join(existing)
            )

        snapshots = DoubanAnnualChartCollector().collect(capture_date)
        output_dir.mkdir(parents=True, exist_ok=True)
        results = []
        for slug, snapshot in snapshots.items():
            path = targets[slug]
            path.write_text(
                json.dumps(
                    snapshot.model_dump(mode="json"),
                    ensure_ascii=False,
                    indent=2,
                ) + "\n",
                encoding="utf-8",
            )
            results.append({
                "slug": slug,
                "name": snapshot.name,
                "snapshot_date": snapshot.snapshot_date.isoformat(),
                "item_count": len(snapshot.movies),
                "ranks": [item.rank for item in snapshot.movies],
                "output": str(path),
            })
    except Exception as exc:
        print(f"Douban annual collection failed: {exc}", file=sys.stderr)
        return 1

    print(json.dumps({"success": True, "charts": results}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
