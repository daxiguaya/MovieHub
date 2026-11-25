import sqlite3

from app.adapters.tmdb_overview import OverviewLookup
from scripts.audit_production_tmdb_overview import audit_database


class StubClient:
    def __init__(self):
        self.calls = []

    def lookup(self, item, language):
        self.calls.append((item.tmdb_id, language))
        return OverviewLookup(
            status="overview_available" if language == "zh-CN" else "no_overview",
            media_type="movie",
            tmdb_id=int(item.tmdb_id),
            match_method="tmdb_id",
            language=language,
            overview_length=24 if language == "zh-CN" else 0,
            overview_sha256="a" * 64 if language == "zh-CN" else None,
            source_url=f"https://www.themoviedb.org/movie/{item.tmdb_id}",
        )


def _database(path):
    connection = sqlite3.connect(path)
    connection.execute("""
        CREATE TABLE movies (
            id INTEGER PRIMARY KEY,
            douban_id TEXT,
            tmdb_id TEXT,
            imdb_id TEXT,
            title TEXT NOT NULL,
            original_title TEXT,
            year INTEGER,
            type TEXT NOT NULL,
            directors TEXT NOT NULL DEFAULT '[]'
        )
    """)
    connection.executemany(
        """
        INSERT INTO movies
        (id, douban_id, tmdb_id, imdb_id, title, original_title, year, type, directors)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (1, "1001", "278", None, "肖申克的救赎", "The Shawshank Redemption", 1994, "movie", "[]"),
            (2, "1002", None, None, "No TMDB identity", None, 2020, "movie", "[]"),
            (3, "1003", "999", None, "Yearless record", None, None, "movie", "[]"),
        ],
    )
    connection.commit()
    connection.close()


def test_audit_reads_known_tmdb_ids_and_skips_unverified_rows(tmp_path):
    database = tmp_path / "movies.db"
    _database(database)
    client = StubClient()

    report = audit_database(database, client, ["zh-CN", "zh-TW"])

    assert report["mode"] == "read_only_dry_run"
    assert report["movie_count"] == 3
    assert report["record_count"] == 6
    assert report["summary"]["zh-CN"] == {
        "insufficient_identity": 1,
        "no_tmdb_id": 1,
        "overview_available": 1,
    }
    assert report["summary"]["zh-TW"] == {
        "insufficient_identity": 1,
        "no_overview": 1,
        "no_tmdb_id": 1,
    }
    assert client.calls == [("278", "zh-CN"), ("278", "zh-TW")]
    assert "overview" not in str(report).lower()
    connection = sqlite3.connect(database)
    try:
        assert connection.execute("SELECT tmdb_id FROM movies WHERE id=1").fetchone()[0] == "278"
    finally:
        connection.close()


def test_audit_rejects_duplicate_languages_and_negative_limit(tmp_path):
    database = tmp_path / "movies.db"
    _database(database)
    client = StubClient()

    import pytest
    with pytest.raises(ValueError, match="unique language"):
        audit_database(database, client, ["zh-CN", "zh-CN"])
    with pytest.raises(ValueError, match="limit"):
        audit_database(database, client, ["zh-CN"], limit=-1)


def test_audit_stops_on_tmdb_rate_limit(tmp_path):
    import httpx
    import pytest

    class RateLimitedClient:
        def lookup(self, item, language):
            request = httpx.Request("GET", "https://api.themoviedb.org/3/movie/278")
            response = httpx.Response(429, request=request)
            raise httpx.HTTPStatusError("rate limited", request=request, response=response)

    database = tmp_path / "movies.db"
    _database(database)
    with pytest.raises(RuntimeError, match="HTTP 429"):
        audit_database(database, RateLimitedClient(), ["zh-CN"])
