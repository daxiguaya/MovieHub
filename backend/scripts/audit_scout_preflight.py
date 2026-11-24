"""Combined read-only Scout catalogue and chart coverage preflight."""

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from scripts.audit_chart_scout_coverage import audit_chart_snapshots
from scripts.audit_scout_import import audit_scout_database


def audit_scout_preflight(
    scout_db_path: str | Path,
    snapshot_paths: list[str | Path],
) -> dict[str, Any]:
    """Run both quality audits and return one import decision report.

    The Scout input must be a staged, immutable SQLite backup for the duration
    of this command. Each underlying audit uses a read-only SQLite connection;
    the chart audit also pins its validation and lookups to one transaction.
    """
    catalogue = audit_scout_database(scout_db_path)
    charts = audit_chart_snapshots(snapshot_paths, scout_db_path)

    catalogue_summary = catalogue["summary"]
    chart_summary = charts["summary"]
    blocking = {
        "invalid_identity_rows": catalogue_summary["invalid_identity_rows"],
        "duplicate_douban_ids": catalogue_summary["duplicate_douban_ids"],
        "chart_items_missing_from_scout": chart_summary["scout_missing"],
        "chart_items_with_ambiguous_scout_ids": chart_summary["scout_ambiguous"],
        "chart_media_type_mismatches": chart_summary["type_mismatches"],
    }
    passed = not any(blocking.values())
    return {
        "read_only": True,
        "scout_database": catalogue["scout_database"],
        "decision": "ready_for_operator_review" if passed else "blocked",
        "strict_gate": {
            "passed": passed,
            "blocking_issues": blocking,
        },
        "catalogue_audit": catalogue,
        "chart_coverage_audit": charts,
        "warnings": {
            "invalid_ratings": catalogue_summary["invalid_ratings"],
            "invalid_years": catalogue_summary["invalid_years"],
            "malformed_raw_data": catalogue_summary["malformed_raw_data"],
        },
        "limitations": [
            "This report does not import data or modify either database.",
            "Use a consistent staged SQLite backup and keep it unchanged during the audit.",
            "A passed gate means ready for operator review, not automatic authorization to import.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the combined read-only Scout catalogue and annual-chart preflight."
    )
    parser.add_argument("--scout-db", required=True, help="Path to a staged Scout SQLite backup")
    parser.add_argument(
        "--input",
        action="append",
        required=True,
        help="Normalized chart JSON snapshot; repeat once per chart",
    )
    args = parser.parse_args()
    try:
        report = audit_scout_preflight(args.scout_db, args.input)
    except Exception as exc:
        print(f"Combined Scout preflight failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if not report["strict_gate"]["passed"]:
        print(
            "Scout preflight blocked: "
            + ", ".join(
                f"{name}={count}"
                for name, count in report["strict_gate"]["blocking_issues"].items()
                if count
            ),
            file=sys.stderr,
        )
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
