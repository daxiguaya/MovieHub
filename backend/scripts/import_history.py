"""Read-only CLI for inspecting durable Scout import run history."""

import argparse
import json

from app.database import SessionLocal
from app.services.import_journal import get_import_journal_path
from app.services.import_history import read_import_run_history


def main() -> int:
    parser = argparse.ArgumentParser(
        description="List or inspect Scout import runs from the append-only journal."
    )
    parser.add_argument(
        "--run-id",
        help="Show one run by its exact run ID instead of listing all runs.",
    )
    args = parser.parse_args()

    journal_path = get_import_journal_path(SessionLocal)
    runs = read_import_run_history(journal_path, run_id=args.run_id)
    if args.run_id and not runs:
        print(json.dumps({"error": "run_not_found", "run_id": args.run_id}))
        return 2

    print(json.dumps({
        "journal": str(journal_path),
        "run_count": len(runs),
        "runs": runs,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
