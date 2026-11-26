"""Private read-only lookup for the complete official IMDb ratings snapshot."""
from __future__ import annotations
import logging
import os
import re
import sqlite3
from pathlib import Path
from app.database import get_db_path

LOG = logging.getLogger("moviehub.imdb_index")
IMDB_ID_PATTERN = re.compile(r"tt[0-9]{7,12}")

def get_index_path() -> Path:
    configured = os.environ.get("IMDB_RATINGS_INDEX_PATH")
    return Path(configured).expanduser().resolve() if configured else Path(get_db_path()).with_name("imdb-ratings.sqlite3")

def lookup_ratings(imdb_ids: list[str] | set[str]) -> dict[str, tuple[float, int]]:
    wanted = sorted({value for value in imdb_ids if isinstance(value, str) and IMDB_ID_PATTERN.fullmatch(value)})
    path = get_index_path()
    if not wanted or not path.is_file():
        return {}
    result: dict[str, tuple[float, int]] = {}
    try:
        connection = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=2)
        try:
            connection.execute("PRAGMA query_only=ON")
            for offset in range(0, len(wanted), 500):
                batch = wanted[offset:offset + 500]
                placeholders = ",".join("?" for _ in batch)
                rows = connection.execute(
                    f"SELECT imdb_id, rating, vote_count FROM ratings WHERE imdb_id IN ({placeholders})",
                    batch,
                ).fetchall()
                result.update({row[0]: (float(row[1]), int(row[2])) for row in rows})
        finally:
            connection.close()
    except (sqlite3.Error, OSError) as exc:
        LOG.warning("IMDb rating index lookup unavailable: %s", type(exc).__name__)
    return result
