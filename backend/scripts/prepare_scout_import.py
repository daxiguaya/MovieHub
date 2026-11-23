"""One-command, read-only Scout import readiness package."""

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from app.database import database_is_ready
from app.services.import_service import ImportService
from scripts.audit_scout_preflight import audit_scout_preflight


def prepare_scout_import(
    scout_db_path: str | Path,
    snapshot_paths: list[str | Path],
    force_full: bool = False,
) -> dict[str, Any]:
    """Run catalogue/chart gates first, then target-aware preview if safe."""
    preflight = audit_scout_preflight(scout_db_path, snapshot_paths)
    report: dict[str, Any] = {
        "report_version": 1,
        "generated_at": datetime.now().isoformat(),
        "read_only": True,
        "decision": "blocked",
        "scout_database": preflight["scout_database"],
        "force_full": force_full,
        "preflight": preflight,
        "preview": None,
        "limitations": [
            "This command never imports records or modifies either database.",
            "The staged Scout database and chart snapshots must remain unchanged throughout preparation.",
            "A ready report requires a separate operator decision before starting an import.",
        ],
    }
    if not preflight["strict_gate"]["passed"]:
        report["blockers"] = preflight["strict_gate"]["blocking_issues"]
        return report
    if not database_is_ready():
        raise RuntimeError(
            "MovieHub target database is not initialized; readiness package cannot include a target-aware preview"
        )

    preview = ImportService().preview_import(scout_db_path, force_full=force_full)
    if preview["source_database"] != preflight["scout_database"]:
        raise RuntimeError("Preflight and preview resolved different Scout source paths")
    report["preview"] = preview
    report["decision"] = (
        "ready_for_operator_review"
        if preview["summary"]["would_write"] > 0
        else "no_changes"
    )
    report["operator_action_required"] = preview["summary"]["would_write"] > 0
    return report


def write_report(path: str | Path, report: dict[str, Any]) -> Path:
    """Atomically persist a private JSON report (owner read/write only)."""
    output_path = Path(path).expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_name(output_path.name + ".tmp")
    descriptor = os.open(temporary, os.O_CREAT | os.O_TRUNC | os.O_WRONLY, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(report, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, output_path)
        os.chmod(output_path, 0o600)
    except Exception:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
        raise
    return output_path


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build a read-only Scout catalogue/chart audit plus target-aware import preview."
    )
    parser.add_argument("--scout-db", required=True, help="Staged Scout SQLite database")
    parser.add_argument("--input", action="append", required=True, help="Normalized chart snapshot JSON; repeat per chart")
    parser.add_argument("--output", required=True, help="Output JSON report path (mode 0600)")
    parser.add_argument("--force-full", action="store_true", help="Preview a forced full reprocessing run")
    args = parser.parse_args()
    try:
        report = prepare_scout_import(args.scout_db, args.input, force_full=args.force_full)
        output_path = write_report(args.output, report)
    except Exception as exc:
        print(f"Scout import readiness preparation failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps({
        "report": str(output_path),
        "decision": report["decision"],
        "source_database": report["scout_database"],
    }, ensure_ascii=False))
    return 0 if report["decision"] in {"ready_for_operator_review", "no_changes"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
