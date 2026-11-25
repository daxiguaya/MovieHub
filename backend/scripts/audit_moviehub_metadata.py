"""Read-only metadata and provenance audit for an existing MovieHub SQLite database.

This audits the deployed MovieHub database directly. It does not require a Scout
export, call external providers, print synopsis text, or modify any database.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any


MEDIA_FIELDS = (
    "original_title",
    "year",
    "rating",
    "rating_count",
    "imdb_id",
    "tmdb_id",
    "directors",
    "actors",
    "overview",
    "douban_url",
)
PROVENANCE_FIELDS = (
    "original_title",
    "year",
    "rating",
    "rating_count",
    "directors",
    "actors",
    "overview",
)
REQUIRED_TABLES = {
    "movies",
    "movie_metadata_provenance",
    "lists",
    "chart_snapshots",
    "list_items",
    "movie_genres",
    "movie_regions",
    "movie_posters",
}


def _table_columns(connection: sqlite3.Connection, table: str) -> set[str]:
    return {
        row["name"]
        for row in connection.execute(f'PRAGMA table_info("{table}")')
    }


def _present_sql(column: str) -> str:
    if column in {"directors", "actors"}:
        return f"({column} IS NOT NULL AND trim({column}) NOT IN ('', '[]'))"
    return f"({column} IS NOT NULL AND trim(CAST({column} AS TEXT)) <> '')"


def audit_database(database_path: str | Path) -> dict[str, Any]:
    """Return aggregate coverage and source-lineage diagnostics, using SELECT only."""
    path = Path(database_path).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"MovieHub database does not exist: {path}")

    connection = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=5)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA query_only = ON")
        tables = {
            row["name"]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        missing = sorted(REQUIRED_TABLES - tables)
        if missing:
            raise ValueError(
                "Not a complete MovieHub database; missing tables: "
                + ", ".join(missing)
            )

        movie_columns = _table_columns(connection, "movies")
        required_movie_columns = {"id", "douban_id", "imdb_id", "tmdb_id", "title"}
        absent_columns = sorted(required_movie_columns - movie_columns)
        if absent_columns:
            raise ValueError(
                "MovieHub movies table is missing columns: "
                + ", ".join(absent_columns)
            )

        total = connection.execute("SELECT COUNT(*) FROM movies").fetchone()[0]
        identity = {}
        for field in ("douban_id", "tmdb_id", "imdb_id"):
            present = connection.execute(
                f"SELECT COUNT(*) FROM movies WHERE {_present_sql(field)}"
            ).fetchone()[0]
            identity[field] = {
                "present": present,
                "missing": total - present,
                "percentage": round(present * 100 / total, 1) if total else 0.0,
            }

        coverage = {}
        for field in MEDIA_FIELDS:
            if field not in movie_columns:
                continue
            present = connection.execute(
                f"SELECT COUNT(*) FROM movies WHERE {_present_sql(field)}"
            ).fetchone()[0]
            coverage[field] = {
                "present": present,
                "missing": total - present,
                "percentage": round(present * 100 / total, 1) if total else 0.0,
            }

        association_counts = {}
        for key, table in (
            ("genres", "movie_genres"),
            ("regions", "movie_regions"),
            ("posters", "movie_posters"),
        ):
            present = connection.execute(
                f"SELECT COUNT(DISTINCT movie_id) FROM {table}"
            ).fetchone()[0]
            association_counts[key] = {
                "movies_with_data": present,
                "missing": total - present,
                "percentage": round(present * 100 / total, 1) if total else 0.0,
            }

        provenance_columns = _table_columns(
            connection, "movie_metadata_provenance"
        )
        needed_provenance = {
            "movie_id", "field_name", "source", "source_url", "observed_at"
        }
        if not needed_provenance.issubset(provenance_columns):
            raise ValueError("MovieHub provenance table has an unexpected schema")

        provenance_by_field = [
            dict(row)
            for row in connection.execute(
                """
                SELECT field_name, source,
                       COUNT(*) AS observations,
                       COUNT(DISTINCT movie_id) AS movies
                FROM movie_metadata_provenance
                GROUP BY field_name, source
                ORDER BY field_name, source
                """
            )
        ]
        provenance_summary = {
            field: {
                "movies_with_observation": connection.execute(
                    """
                    SELECT COUNT(DISTINCT movie_id)
                    FROM movie_metadata_provenance
                    WHERE field_name = ?
                    """,
                    (field,),
                ).fetchone()[0],
            }
            for field in PROVENANCE_FIELDS
        }

        charts = [
            dict(row)
            for row in connection.execute(
                """
                SELECT l.slug, l.name, l.source,
                       COUNT(DISTINCT cs.id) AS snapshot_count,
                       COALESCE((
                           SELECT SUM(cs2.item_count)
                           FROM chart_snapshots AS cs2
                           WHERE cs2.list_id = l.list_id
                       ), 0) AS declared_items,
                       COUNT(DISTINCT li.movie_id) AS distinct_movies
                FROM lists AS l
                LEFT JOIN chart_snapshots AS cs ON cs.list_id = l.list_id
                LEFT JOIN list_items AS li ON li.snapshot_id = cs.id
                GROUP BY l.list_id, l.slug, l.name, l.source
                ORDER BY l.slug
                """
            )
        ]

        chart_sources = [
            dict(row)
            for row in connection.execute(
                """
                SELECT source, COUNT(*) AS chart_count
                FROM lists
                GROUP BY source
                ORDER BY source
                """
            )
        ]

        migration_version = None
        if "schema_migrations" in tables:
            migration_version = connection.execute(
                "SELECT MAX(version) FROM schema_migrations"
            ).fetchone()[0]

        overview_present = coverage.get("overview", {}).get("present", 0)
        overview_provenance = provenance_summary.get(
            "overview", {"movies_with_observation": 0}
        )["movies_with_observation"]

        return {
            "report_version": 1,
            "read_only": True,
            "database": str(path),
            "schema_version": migration_version,
            "movie_count": total,
            "identity_coverage": identity,
            "metadata_coverage": coverage,
            "association_coverage": association_counts,
            "provenance": {
                "observation_count": connection.execute(
                    "SELECT COUNT(*) FROM movie_metadata_provenance"
                ).fetchone()[0],
                "by_field_and_source": provenance_by_field,
                "movies_with_observation_by_field": provenance_summary,
                "interpretation": (
                    "Provenance records are created when chart import first fills "
                    "an empty field. They are not a complete history of every "
                    "source that ever contributed to an already-populated field."
                ),
            },
            "charts": charts,
            "chart_sources": chart_sources,
            "diagnostics": {
                "overview_populated_without_provenance": max(
                    0, overview_present - overview_provenance
                ),
                "overview_provenance_without_current_value": max(
                    0, overview_provenance - overview_present
                ),
                "note": (
                    "These are aggregate differences, not proof of a data-loss "
                    "event; provenance is first-fill-only."
                ),
            },
            "safety": [
                "Opened SQLite in read-only mode and enabled query_only.",
                "No Scout database or external API is required.",
                "Synopsis text, API tokens, and poster URLs are not included.",
            ],
        }
    finally:
        connection.close()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Read-only audit of an existing MovieHub production SQLite database."
    )
    parser.add_argument(
        "--db",
        required=True,
        help="Path to MovieHub db/movies.db (not a Scout database)",
    )
    args = parser.parse_args()
    try:
        report = audit_database(args.db)
    except Exception as exc:
        print(f"MovieHub metadata audit failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
