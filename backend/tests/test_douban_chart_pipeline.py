"""End-to-end chart collection to MovieHub snapshot import test."""

import json
from datetime import date

from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.adapters.douban_top250 import ROBOTS_URL
from app.adapters.douban_tagged_chart import SEARCH_SUBJECTS_URL, DoubanTaggedChartCollector
from app.database import Base, ChartItem, ChartSnapshot, Movie
from app.services.chart_import_service import ChartImportService


class Response:
    def __init__(self, status_code, payload=None, text=None):
        self.status_code = status_code
        self.payload = payload
        self.text = text if text is not None else json.dumps(payload or {})
        self.content = self.text.encode("utf-8")
        self.headers = {}

    def json(self):
        return self.payload


class DoubanFixtureClient:
    def get(self, url, params=None):
        if url == ROBOTS_URL:
            return Response(200, text="User-agent: *\nAllow: /")
        if url == SEARCH_SUBJECTS_URL:
            subjects = [
                {
                    "id": str(810000 + index),
                    "title": f"Pipeline Movie {index}",
                    "rate": str(8.0 + index / 10),
                    "cover": "",
                    "url": f"https://movie.douban.com/subject/{810000 + index}/",
                }
                for index in range(1, 4)
            ]
            return Response(200, payload={"subjects": subjects})
        raise AssertionError(f"Unexpected request: {url}")


def test_douban_tagged_collection_flows_into_internal_movie_ids_and_chart_snapshot():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(connection, record):
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    db = Session(engine, expire_on_commit=False)

    try:
        snapshot = DoubanTaggedChartCollector(
            client=DoubanFixtureClient(),
            sleeper=lambda _: None,
            max_items=3,
        ).collect("popular", date(2026, 11, 23))

        result = ChartImportService().import_snapshot(db, snapshot)
        db.commit()

        assert result.imported_count == 3
        stored_snapshot = db.scalar(
            select(ChartSnapshot).where(
                ChartSnapshot.snapshot_date == "2026-11-23"
            )
        )
        assert stored_snapshot is not None
        assert stored_snapshot.item_count == 3

        items = db.scalars(
            select(ChartItem)
            .where(ChartItem.snapshot_id == stored_snapshot.id)
            .order_by(ChartItem.rank)
        ).all()
        assert [item.rank for item in items] == [1, 2, 3]

        movies = db.scalars(
            select(Movie).where(Movie.douban_id.in_(["810001", "810002", "810003"]))
        ).all()
        assert len(movies) == 3
        movie_ids = {movie.id for movie in movies}
        assert all(item.movie_id in movie_ids for item in items)
        assert {movie.douban_id for movie in movies} == {
            "810001",
            "810002",
            "810003",
        }
    finally:
        db.close()
        engine.dispose()
