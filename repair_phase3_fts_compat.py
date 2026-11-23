#!/usr/bin/env python3
# MovieHub Phase3: remove the unused FTS5 hard dependency.
# Source-only repair. Does NOT migrate the production database.

import ast
import re
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path("/volume1/mysysdir/MovieHub")
BACKEND = ROOT / "backend"

FILES = [
    BACKEND / "app/database.py",
    BACKEND / "app/services/movie_service.py",
    BACKEND / "app/services/import_service.py",
    BACKEND / "app/services/chart_import_service.py",
    BACKEND / "scripts/migrate.py",
    BACKEND / "migrations/001_moviehub_core.sql",
]

def replace_once(content, old, new, filename):
    count = content.count(old)
    if count != 1:
        raise RuntimeError(
            f"{filename}: expected one occurrence, found {count}"
        )
    return content.replace(old, new, 1)

def main():
    if not ROOT.is_dir():
        raise RuntimeError(f"Project directory missing: {ROOT}")

    original = {}
    for path in FILES:
        if not path.is_file():
            raise FileNotFoundError(path)
        original[path] = path.read_text(encoding="utf-8")

    updated = dict(original)

    # ---------------------------------------------------------
    # 1. database.py: remove unused FTS5 SQL constants.
    # ---------------------------------------------------------
    path = FILES[0]
    content = updated[path]

    pattern = re.compile(
        r"FTS_TABLE_NAME = \"movie_search\"\s+"
        r"FTS_CREATE_TABLE_SQL = \(.*?\n"
        r"FTS_INSERT_ALL_SQL = \(.*?\n\s*\)\s*\n",
        re.S,
    )
    content, count = pattern.subn("", content, count=1)

    if count != 1:
        raise RuntimeError("database.py: FTS constants block not found")

    updated[path] = content

    # ---------------------------------------------------------
    # 2. movie_service.py: search directly in movies.
    # ---------------------------------------------------------
    path = FILES[1]
    content = updated[path]

    content = replace_once(
        content,
        "    FTS_TABLE_NAME,\n",
        "",
        str(path),
    )

    pattern = re.compile(
        r"    @staticmethod\n"
        r"    def _apply_search\(.*?\n"
        r"    @staticmethod\n"
        r"    def _apply_rating_range\(",
        re.S,
    )

    replacement = '''    @staticmethod
    def _apply_search(
        db: Session,
        query: Query,
        search: str,
    ) -> Query:
        """Search movie titles directly without requiring FTS5."""
        terms = [
            term.strip()
            for term in search.split()
            if term.strip()
        ]

        if not terms:
            return query

        # Every term must match either the Chinese/display title or
        # the original title. SQLAlchemy escapes LIKE wildcards.
        conditions = []

        for term in terms:
            conditions.append(
                or_(
                    Movie.title.contains(term, autoescape=True),
                    Movie.original_title.contains(
                        term,
                        autoescape=True,
                    ),
                )
            )

        return query.filter(and_(*conditions))

    @staticmethod
    def _apply_rating_range('''

    content, count = pattern.subn(replacement, content, count=1)

    if count != 1:
        raise RuntimeError("movie_service.py: search method not found")

    updated[path] = content

    # ---------------------------------------------------------
    # 3. import_service.py: FTS is not part of import transaction.
    # ---------------------------------------------------------
    path = FILES[2]
    content = updated[path]

    content = replace_once(
        content,
        "    FTS_REBUILD_SQL,\n",
        "",
        str(path),
    )

    content, count = re.subn(
        r"(?m)^[ \t]*# FTS is rebuilt in the same transaction as the metadata\n"
        r"[ \t]*# changes\. If rebuilding fails, the whole import rolls back\.\n"
        r"[ \t]*db\.execute\(text\(FTS_REBUILD_SQL\)\)\n",
        "",
        content,
        count=1,
    )
    if count != 1:
        raise RuntimeError("import_service.py: FTS block not found")

    updated[path] = content

    # ---------------------------------------------------------
    # 4. chart_import_service.py: remove FTS transaction dependency.
    # ---------------------------------------------------------
    path = FILES[3]
    content = updated[path]

    content = replace_once(
        content,
        "    FTS_REBUILD_SQL,\n",
        "",
        str(path),
    )

    content, count = re.subn(
        r"(?m)^[ \t]*# Keep FTS in sync with the movie records in this transaction\.\n"
        r"[ \t]*db\.execute\(text\(FTS_REBUILD_SQL\)\)\n",
        "",
        content,
        count=1,
    )
    if count != 1:
        raise RuntimeError("chart_import_service.py: FTS block not found")

    updated[path] = content

    # ---------------------------------------------------------
    # 5. migrate.py: movie_search is optional/non-required.
    # ---------------------------------------------------------
    path = FILES[4]
    content = updated[path]

    content = replace_once(
        content,
        '    "schema_migrations",\n    "movie_search",\n',
        '    "schema_migrations",\n',
        str(path),
    )

    pattern = re.compile(
        r"\ndef validate_fts\(conn: sqlite3\.Connection\) -> None:.*?"
        r"\n(?=def validate_migration\()",
        re.S,
    )

    content, count = pattern.subn("\n", content, count=1)

    if count != 1:
        raise RuntimeError("migrate.py: validate_fts function not found")

    content = replace_once(
        content,
        "        validate_fts(conn)\n",
        "",
        str(path),
    )

    updated[path] = content

    # ---------------------------------------------------------
    # 6. Migration SQL: remove mandatory FTS5 creation.
    # Do not DROP any pre-existing movie_search table.
    # ---------------------------------------------------------
    path = FILES[5]
    content = updated[path]

    pattern = re.compile(
        r"-- -------------------------------------------------------------------------\n"
        r"-- 6\. Rebuild FTS5 index.*?"
        r"(?=-- -------------------------------------------------------------------------\n"
        r"-- 7\. Record migration)",
        re.S,
    )

    content, count = pattern.subn("", content, count=1)

    if count != 1:
        raise RuntimeError("Migration SQL: FTS5 section not found")

    updated[path] = content

    # ---------------------------------------------------------
    # Validate all edits before touching original files.
    # ---------------------------------------------------------
    for path, content in updated.items():
        if path.suffix == ".py":
            ast.parse(content, filename=str(path))

    # Check that no active FTS hard dependency remains.
    for path, content in updated.items():
        if path.suffix == ".py":
            if "FTS_REBUILD_SQL" in content:
                raise RuntimeError(
                    f"Unresolved FTS rebuild reference: {path}"
                )
            if "FTS_TABLE_NAME" in content:
                raise RuntimeError(
                    f"Unresolved FTS table reference: {path}"
                )

    # ---------------------------------------------------------
    # Backup all six files before writing any changes.
    # ---------------------------------------------------------
    backup_dir = ROOT / (
        "MovieHub-repair-backup-phase3-"
        + datetime.now().strftime("%Y%m%d-%H%M%S")
    )

    backup_dir.mkdir(parents=True, exist_ok=False)

    try:
        for path in FILES:
            relative = path.relative_to(ROOT)
            destination = backup_dir / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, destination)

        # Verify backup copies.
        for path in FILES:
            relative = path.relative_to(ROOT)
            backup_file = backup_dir / relative
            if backup_file.read_bytes() != path.read_bytes():
                raise RuntimeError(f"Backup verification failed: {path}")

        print("Backup:", backup_dir)

        # Write each file through a temporary file.
        for path in FILES:
            temporary = path.with_name(path.name + ".phase3.tmp")
            temporary.write_text(updated[path], encoding="utf-8")
            temporary.replace(path)

        # -----------------------------------------------------
        # Syntax check after writing.
        # -----------------------------------------------------
        for path in BACKEND.rglob("*.py"):
            if "__pycache__" in path.parts:
                continue
            ast.parse(
                path.read_text(encoding="utf-8"),
                filename=str(path),
            )

        print("[PASS] Python AST validation")

        # -----------------------------------------------------
        # In-memory migration test. No production DB touched.
        # -----------------------------------------------------
        sql = (
            BACKEND / "migrations/001_moviehub_core.sql"
        ).read_text(encoding="utf-8")

        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row

        try:
            conn.execute("PRAGMA foreign_keys=ON")

            conn.executescript("""
                CREATE TABLE movies (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    year INTEGER,
                    rating REAL,
                    rating_count INTEGER NOT NULL DEFAULT 0,
                    type TEXT NOT NULL DEFAULT 'movie',
                    updated_at INTEGER
                );

                INSERT INTO movies(id, title, type)
                VALUES
                    (123, 'MovieHub migration test', 'movie'),
                    (124, '测试电影', 'movie');
            """)

            conn.executescript(sql)

            required = {
                "movies", "genres", "movie_genres",
                "regions", "movie_regions", "movie_posters",
                "lists", "list_items", "favorites",
                "schema_migrations",
            }

            tables = {
                row["name"]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }

            missing = required - tables
            assert not missing, sorted(missing)

            print("[PASS] All required tables created")

            movie = conn.execute(
                "SELECT douban_id, original_title "
                "FROM movies WHERE id=123"
            ).fetchone()

            assert movie["douban_id"] == "123"
            print("[PASS] Existing movie ID preserved")

            conn.execute("""
                INSERT INTO lists(slug, name, source, category)
                VALUES ('test', 'Test chart', 'test', 'general')
            """)

            conn.execute("""
                INSERT INTO list_items(
                    list_id, snapshot_date, douban_id, rank
                )
                VALUES (1, '2026-11-23', '123', 1)
            """)

            print("[PASS] Chart snapshot foreign key")

            matches = conn.execute(
                "SELECT id FROM movies WHERE title LIKE ?",
                ("%测试%",),
            ).fetchall()

            assert len(matches) == 1 and matches[0]["id"] == 124
            print("[PASS] Chinese title LIKE search")

            try:
                conn.execute("DELETE FROM movies WHERE id=123")
                raise AssertionError(
                    "Referenced movie deletion unexpectedly succeeded"
                )
            except sqlite3.IntegrityError:
                print("[PASS] ON DELETE RESTRICT")

            assert not conn.execute(
                "PRAGMA foreign_key_check"
            ).fetchall()

            print("[PASS] Foreign key integrity")

            version = conn.execute(
                "SELECT MAX(version) FROM schema_migrations"
            ).fetchone()[0]

            assert version == 1
            print("[PASS] Migration version:", version)

            assert not conn.execute(
                "SELECT 1 FROM sqlite_master "
                "WHERE name='movie_search'"
            ).fetchone()

            print("[PASS] Migration does not require FTS5")

        finally:
            conn.close()

        print()
        print("[SUCCESS] Phase3 source repair completed")
        print("Backup retained:", backup_dir)
        print("Production database was NOT modified.")

    except Exception:
        print("[ERROR] Phase3 validation failed; restoring source files.")

        for path in FILES:
            relative = path.relative_to(ROOT)
            backup_file = backup_dir / relative

            if backup_file.is_file():
                shutil.copy2(backup_file, path)

        raise


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print("[FAILED]", repr(exc))
        sys.exit(1)
