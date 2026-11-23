
"""Local JSON snapshot adapters."""

import json
from pathlib import Path

from pydantic import ValidationError

from app.adapters.base import AdapterError, ChartSourceAdapter
from app.schemas_chart_import import ChartSnapshotImport


class LocalImportAdapter(ChartSourceAdapter):
    source_name = "local"
    MAX_FILE_SIZE = 50 * 1024 * 1024

    def load_snapshot(
        self,
        source_path: str | Path,
    ) -> ChartSnapshotImport:
        path = Path(source_path).expanduser()

        if not path.exists() or not path.is_file():
            raise AdapterError("Snapshot file does not exist")

        try:
            size = path.stat().st_size
        except OSError as exc:
            raise AdapterError("Unable to inspect snapshot file") from exc

        if size <= 0:
            raise AdapterError("Snapshot file is empty")

        if size > self.MAX_FILE_SIZE:
            raise AdapterError("Snapshot file exceeds the 50 MB limit")

        try:
            with path.open("r", encoding="utf-8-sig") as file:
                payload = json.load(file)
        except UnicodeDecodeError as exc:
            raise AdapterError("Snapshot file must use UTF-8 encoding") from exc
        except json.JSONDecodeError as exc:
            raise AdapterError(
                f"Invalid JSON at line {exc.lineno}, column {exc.colno}"
            ) from exc
        except OSError as exc:
            raise AdapterError("Unable to read snapshot file") from exc

        try:
            snapshot = ChartSnapshotImport.model_validate(payload)
        except ValidationError as exc:
            raise AdapterError(
                "Snapshot data does not match the MovieHub import schema"
            ) from exc

        return snapshot.model_copy(
            update={"source": self.source_name}
        )


class CinephileImportAdapter(LocalImportAdapter):
    """Import an authorized local Cinephile data export.

    This adapter does not scrape Cinephile or download its data.
    The input must be a local JSON snapshot already converted to the
    MovieHub ChartSnapshotImport format.
    """

    source_name = "cinephile"

