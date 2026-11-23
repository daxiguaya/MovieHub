"""Validate and import a normalized local chart snapshot into MovieHub."""

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from app.adapters.local_import import CinephileImportAdapter, LocalImportAdapter
from app.database import SessionLocal, database_is_ready
from app.services.chart_import_service import chart_import_service


def import_snapshot(
    source_path: str | Path,
    adapter_name: str = "local",
    dry_run: bool = False,
) -> dict[str, Any]:
    """Load, validate and optionally persist one normalized chart snapshot."""
    adapters = {
        "local": LocalImportAdapter,
        "cinephile": CinephileImportAdapter,
    }
    try:
        adapter_type = adapters[adapter_name]
    except KeyError as exc:
        raise ValueError(f"Unsupported adapter: {adapter_name}") from exc

    snapshot = adapter_type().load_snapshot(source_path)
    if dry_run:
        return {
            "valid": True,
            "slug": snapshot.slug,
            "snapshot_date": snapshot.snapshot_date.isoformat(),
            "item_count": len(snapshot.movies),
            "source": snapshot.source,
        }

    if not database_is_ready():
        raise RuntimeError(
            "MovieHub database is not ready. Initialize the independent MovieHub database first."
        )

    with SessionLocal() as db:
        return chart_import_service.import_snapshot(db, snapshot)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Import a normalized MovieHub chart snapshot JSON file."
    )
    parser.add_argument("--input", required=True, help="Path to the JSON snapshot file")
    parser.add_argument(
        "--adapter",
        choices=("local", "cinephile"),
        default="local",
        help="Input adapter; Cinephile mode accepts an already normalized local export",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate the file without writing to the MovieHub database",
    )
    args = parser.parse_args()

    try:
        result = import_snapshot(
            source_path=args.input,
            adapter_name=args.adapter,
            dry_run=args.dry_run,
        )
    except Exception as exc:
        print(f"Chart import failed: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
