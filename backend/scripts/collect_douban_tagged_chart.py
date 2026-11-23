"""One-shot collector for Douban popular and high-rated movie lists."""

import argparse
import json
import sys
from datetime import date
from pathlib import Path

from app.adapters.douban_tagged_chart import (
    CHARTS,
    MAX_ITEMS,
    DoubanTaggedChartCollector,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Collect a bounded Douban tagged movie list from its public web endpoint. "
            "Checks robots.txt, waits at least two seconds between pages, "
            "and stops on access/rate-limit errors."
        )
    )
    parser.add_argument(
        "--chart",
        required=True,
        choices=sorted(CHARTS),
        help="Chart to collect: popular or high-rated",
    )
    parser.add_argument(
        "--date",
        required=True,
        help="Snapshot date in YYYY-MM-DD format",
    )
    parser.add_argument(
        "--output",
        required=True,
        help="Output path for the normalized JSON snapshot",
    )
    parser.add_argument(
        "--max-items",
        type=int,
        default=MAX_ITEMS,
        help=f"Maximum number of movies to request (1-500; default {MAX_ITEMS})",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Allow replacing an existing output file",
    )
    args = parser.parse_args()

    try:
        snapshot_date = date.fromisoformat(args.date)
        output = Path(args.output).expanduser()
        if output.exists() and not args.overwrite:
            raise FileExistsError(
                f"{output} already exists; pass --overwrite to replace it"
            )

        snapshot = DoubanTaggedChartCollector(
            max_items=args.max_items
        ).collect(args.chart, snapshot_date)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(
                snapshot.model_dump(mode="json"),
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
    except Exception as exc:
        print(f"Douban chart collection failed: {exc}", file=sys.stderr)
        return 1

    print(
        json.dumps(
            {
                "success": True,
                "slug": snapshot.slug,
                "snapshot_date": snapshot.snapshot_date.isoformat(),
                "count": len(snapshot.movies),
                "output": str(output),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
