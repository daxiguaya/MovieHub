"""Read-only CLI for preview-to-import reconciliation."""

import argparse
import json

from app.database import SessionLocal
from app.services.import_journal import get_import_journal_path
from app.services.import_reconciliation import (
    ReconciliationError,
    load_preview_report,
    reconcile_preview_with_run,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compare a saved Scout preview with a completed import run."
    )
    parser.add_argument("--preview", required=True, help="Saved preview JSON report")
    parser.add_argument("--run-id", required=True, help="Exact import run ID")
    args = parser.parse_args()
    try:
        preview = load_preview_report(args.preview)
        result = reconcile_preview_with_run(
            preview,
            get_import_journal_path(SessionLocal),
            args.run_id,
        )
    except ReconciliationError as exc:
        print(json.dumps({"reconciled": False, "status": "invalid_input", "error": str(exc)}, ensure_ascii=False, indent=2))
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["reconciled"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
