
"""Common contracts for MovieHub data source adapters."""

from abc import ABC, abstractmethod
from pathlib import Path

from app.schemas_chart_import import ChartSnapshotImport


class AdapterError(Exception):
    """Raised when a data source cannot produce a valid chart snapshot."""


class ChartSourceAdapter(ABC):
    """Base class for adapters that normalize chart snapshots."""

    source_name: str

    @abstractmethod
    def load_snapshot(self, source_path: str | Path) -> ChartSnapshotImport:
        """Load and normalize one chart snapshot."""
        raise NotImplementedError

