"""Read-only CLI for inspecting durable per-record Scout import failures."""

import argparse
import json

from app.database import SessionLocal
from app.services.import_journal import get_import_journal_path
from app.services.import_errors import read_import_errors


def main() -> int:
    parser = argparse.ArgumentParser(
        description="List durable record-level Scout import failures."
    )
    parser.add_argument("--run-id", help="Filter to one exact import run ID.")
    args = parser.parse_args()

    journal_path = get_import_journal_path(SessionLocal)
    errors = read_import_errors(journal_path, run_id=args.run_id)
    print(json.dumps({
        "read_only": True,
        "journal": str(journal_path),
        "run_id": args.run_id,
        "error_count": len(errors),
        "errors": errors,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
