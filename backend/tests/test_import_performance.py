"""Opt-in synthetic Scout import throughput benchmarks.

Run with:
    MOVIEHUB_RUN_IMPORT_BENCHMARKS=1 pytest -q -s backend/tests/test_import_performance.py

These tests use temporary SQLite databases only. They never open a real Scout
or MovieHub database.
"""

import json
import os
import sqlite3
import time

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from app.database import Base, Movie
import app.services.import_service as import_service_module


pytestmark = pytest.mark.skipif(
    os.environ.get("MOVIEHUB_RUN_IMPORT_BENCHMARKS") != "1",
    reason="set MOVIEHUB_RUN_IMPORT_BENCHMARKS=1 to run opt-in benchmarks",
)


@pytest.mark.parametrize("record_count", [10_000, 100_000])
def test_synthetic_scout_import_throughput(record_count, tmp_path, monkeypatch):
    source_path = tmp_path / f"scout-{record_count}.sqlite"
    target_path = tmp_path / f"moviehub-{record_count}.sqlite"

    # Generate the source in bounded executemany chunks so fixture creation
    # itself does not require retaining 100k Python tuples in memory.
    with sqlite3.connect(source_path) as source:
        source.execute(
            """
            CREATE TABLE item (
                douban_id TEXT,
                imdb_id TEXT,
                douban_title TEXT,
                year INTEGER,
                rating REAL,
                raw_data TEXT,
                type TEXT,
                update_time INTEGER
            )
            """
        )
        for start in range(0, record_count, 2_000):
            stop = min(start + 2_000, record_count)
            source.executemany(
                "INSERT INTO item VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    (
                        str(10_000_000 + index),
                        None,
                        f"Synthetic Movie {index}",
                        1980 + index % 45,
                        6.0 + (index % 40) / 10,
                        json.dumps(
                            {"detail": {"summary": f"Overview {index}"}},
                            separators=(",", ":"),
                        ),
                        "movie",
                        1_800_000_000 + index,
                    )
                    for index in range(start, stop)
                ),
            )

    engine = create_engine(
        f"sqlite:///{target_path.as_posix()}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    BenchmarkSession = sessionmaker(
        bind=engine,
        autoflush=False,
        expire_on_commit=False,
    )
    monkeypatch.setattr(
        import_service_module, "SessionLocal", BenchmarkSession
    )
    monkeypatch.setattr(
        import_service_module.cache_manager, "clear", lambda: None
    )

    service = import_service_module.ImportService()
    assert service._run_lock.acquire(blocking=False)
    started = time.perf_counter()
    try:
        service._run_import(source_path, force_full=True)
        elapsed = time.perf_counter() - started

        assert service.status.status == "completed", service.status.message
        assert service.status.processed == record_count
        assert service.status.total == record_count

        with BenchmarkSession() as db:
            imported_count = db.scalar(select(func.count()).select_from(Movie))
        assert imported_count == record_count

        throughput = record_count / elapsed if elapsed else 0
        print(
            f"Scout import benchmark: rows={record_count}, "
            f"seconds={elapsed:.2f}, rows_per_second={throughput:.1f}, "
            f"batch_size={service._BATCH_SIZE}"
        )
    finally:
        if service._run_lock.locked():
            service._run_lock.release()
        engine.dispose()
