"""Opt-in synthetic SQLite LIKE-search benchmarks.

Run with:
    MOVIEHUB_RUN_SEARCH_BENCHMARKS=1 pytest -q -s backend/tests/test_search_performance.py

Only temporary SQLite databases are created. No production or Scout database is
opened. Results are observational; this benchmark intentionally has no
hardware-dependent pass/fail latency threshold.
"""

import os
import sqlite3
import time

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base, Movie
from app.services.movie_service import movie_service


pytestmark = pytest.mark.skipif(
    os.environ.get("MOVIEHUB_RUN_SEARCH_BENCHMARKS") != "1",
    reason="set MOVIEHUB_RUN_SEARCH_BENCHMARKS=1 to run opt-in benchmarks",
)


@pytest.mark.parametrize("record_count", [10_000, 100_000])
def test_sqlite_like_search_throughput(record_count, tmp_path):
    database_path = tmp_path / f"moviehub-search-{record_count}.sqlite"
    engine = create_engine(
        f"sqlite:///{database_path.as_posix()}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)

    # Generate rows in bounded batches. The benchmark data is deterministic
    # and includes sparse Chinese-title and original-title matches.
    with sqlite3.connect(database_path) as connection:
        for start in range(0, record_count, 2_000):
            stop = min(start + 2_000, record_count)
            connection.executemany(
                """
                INSERT INTO movies (
                    douban_id, title, original_title, year, rating,
                    rating_count, type, directors, actors
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    (
                        str(20_000_000 + index),
                        f"合成电影 {index}" + (" 星际穿越" if index % 1_000 == 0 else ""),
                        f"Synthetic Feature {index}" + (" Interstellar" if index % 997 == 0 else ""),
                        1980 + index % 45,
                        5.0 + (index % 50) / 10,
                        index % 100_000,
                        "movie" if index % 5 else "tv",
                        "[]",
                        "[]",
                    )
                    for index in range(start, stop)
                ),
            )

    BenchmarkSession = sessionmaker(
        bind=engine,
        autoflush=False,
        expire_on_commit=False,
    )
    scenarios = (
        ("sparse_chinese_title", "星际穿越"),
        ("sparse_original_title", "Interstellar"),
        ("no_match", "moviehub-no-such-title"),
        ("multi_term", "合成电影 星际穿越"),
    )

    try:
        with BenchmarkSession() as db:
            for label, term in scenarios:
                query = movie_service._apply_search(
                    db,
                    db.query(Movie),
                    term,
                )
                count_started = time.perf_counter()
                match_count = query.order_by(None).count()
                count_elapsed = time.perf_counter() - count_started

                page_started = time.perf_counter()
                page = query.order_by(Movie.id).limit(20).all()
                page_elapsed = time.perf_counter() - page_started

                compiled = str(
                    query.statement.compile(
                        compile_kwargs={"literal_binds": True}
                    )
                )
                plan = db.connection().exec_driver_sql(
                    "EXPLAIN QUERY PLAN " + compiled
                ).all()
                plan_summary = " | ".join(str(row[-1]) for row in plan)

                print(
                    "SQLite LIKE search benchmark: "
                    f"rows={record_count}, scenario={label}, "
                    f"matches={match_count}, page_rows={len(page)}, "
                    f"count_seconds={count_elapsed:.4f}, "
                    f"page_seconds={page_elapsed:.4f}, "
                    f"query_plan={plan_summary}"
                )
    finally:
        engine.dispose()
