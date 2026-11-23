"""Collect all four official Douban 2025 annual chart snapshots to local JSON."""
import argparse
import json
import os
import shutil
import sys
import tempfile
from datetime import date
from pathlib import Path

from app.adapters.douban_annual import (
    ANNUAL_CHARTS,
    DoubanAnnualChartCollector,
)



def write_snapshots(
    snapshots,
    output_dir: str | Path,
    capture_date: date,
    overwrite: bool = False,
) -> list[dict[str, object]]:
    """Stage all annual JSON files before publishing any of them.

    If publication fails partway through, restore pre-existing files and
    remove newly published files so callers never mistake a partial set for
    a complete annual collection.
    """
    output_dir = Path(output_dir).expanduser()
    output_dir.mkdir(parents=True, exist_ok=True)
    targets = {
        slug: output_dir / f"{slug}-{capture_date.isoformat()}.json"
        for slug in ANNUAL_CHARTS
    }
    existing = {slug: path for slug, path in targets.items() if path.exists()}
    if existing and not overwrite:
        raise FileExistsError(
            "Output file(s) already exist; pass --overwrite to replace: "
            + ", ".join(str(path) for path in existing.values())
        )

    results: list[dict[str, object]] = []
    published: list[str] = []
    with tempfile.TemporaryDirectory(prefix=".moviehub-annual-", dir=output_dir) as temp:
        staging = Path(temp) / "staged"
        backups = Path(temp) / "backups"
        staging.mkdir()
        backups.mkdir()

        # Serialize and write every output before touching published files.
        for slug, snapshot in snapshots.items():
            staged_path = staging / targets[slug].name
            staged_path.write_text(
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
                "output": str(targets[slug]),
            })

        for slug, target in targets.items():
            if slug in existing:
                shutil.copy2(target, backups / target.name)

        try:
            for slug, target in targets.items():
                os.replace(staging / target.name, target)
                published.append(slug)
        except Exception:
            for slug in reversed(published):
                target = targets[slug]
                if slug in existing:
                    os.replace(backups / target.name, target)
                else:
                    target.unlink(missing_ok=True)
            raise

    return results


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
        snapshots = DoubanAnnualChartCollector().collect(capture_date)
        results = write_snapshots(
            snapshots,
            output_dir,
            capture_date,
            overwrite=args.overwrite,
        )
    except Exception as exc:
        print(f"Douban annual collection failed: {exc}", file=sys.stderr)
        return 1

    print(json.dumps({"success": True, "charts": results}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
