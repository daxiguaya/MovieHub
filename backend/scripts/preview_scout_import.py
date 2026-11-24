"""Read-only preview of the changes a Scout import would make."""

import argparse
import json
import os
import sys
from pathlib import Path

from app.database import database_is_ready
from app.services.import_service import ImportService


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Classify new, updated and unchanged Scout records without writing."
    )
    parser.add_argument("--scout-db", required=True, help="Path to a staged Scout SQLite database")
    parser.add_argument("--force-full", action="store_true", help="Preview forced full reprocessing")
    parser.add_argument("--output", help="Persist the preview JSON report to this path (mode 0600)")
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

    rendered = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        output_path = Path(args.output).expanduser().resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = output_path.with_name(output_path.name + ".tmp")
        descriptor = os.open(temporary, os.O_CREAT | os.O_TRUNC | os.O_WRONLY, 0o600)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as target:
                target.write(rendered)
                target.flush()
                os.fsync(target.fileno())
            os.replace(temporary, output_path)
            os.chmod(output_path, 0o600)
        except Exception:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass
            raise
        print(json.dumps({"saved": str(output_path), "source_fingerprint": report["source_fingerprint"]}, ensure_ascii=False))
    else:
        print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
