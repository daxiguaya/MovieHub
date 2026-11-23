"""Read-only preview of the changes a Scout import would make."""

import argparse
import json
import sys

from app.database import database_is_ready
from app.services.import_service import ImportService


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Classify new, updated and unchanged Scout records without writing."
    )
    parser.add_argument("--scout-db", required=True, help="Path to a staged Scout SQLite database")
    parser.add_argument("--force-full", action="store_true", help="Preview forced full reprocessing")
    args = parser.parse_args()

    if not database_is_ready():
        print(
            "MovieHub database is not ready. Initialize the independent MovieHub database first.",
            file=sys.stderr,
        )
        return 1

    try:
        report = ImportService().preview_import(args.scout_db, force_full=args.force_full)
    except Exception as exc:
        print(f"Scout import preview failed: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
