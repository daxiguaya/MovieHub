from datetime import date
import json

import pytest

from app.adapters.douban_top250 import ROBOTS_URL
from app.adapters.douban_tagged_chart import (
    SEARCH_SUBJECTS_URL,
    DoubanTaggedChartCollector,
)
from app.adapters.douban_top250 import DoubanCollectionError


class FakeResponse:
    def __init__(self, status_code, payload=None, text=None, headers=None):
        self.status_code = status_code
        self.payload = payload
        self.text = text if text is not None else json.dumps(payload or {})
        self.content = self.text.encode("utf-8")
        self.headers = headers or {}

    def json(self):
        return self.payload


class FakeClient:
    def __init__(self, robots_text="User-agent: *\nAllow: /", page_status=200):
        self.robots_text = robots_text
        self.page_status = page_status
        self.requests = []

    def get(self, url, params=None):
        self.requests.append((url, params))
        if url == ROBOTS_URL:
            return FakeResponse(200, text=self.robots_text)
        if url == SEARCH_SUBJECTS_URL:
            if self.page_status != 200:
                return FakeResponse(
                    self.page_status,
                    payload={},
                    headers={"Retry-After": "60"},
                )
            start = int(params["page_start"])
            limit = int(params["page_limit"])
            subjects = [
                {
                    "id": str(2000000 + rank),
                    "title": f"Tagged Movie {rank}",
                    "rate": "8.8",
                    "cover": (
                        "https://img2.doubanio.com/view/photo/s_ratio_poster/"
                        f"public/{rank}.jpg"
                    ),
                    "url": f"https://movie.douban.com/subject/{2000000 + rank}/",
                }
                for rank in range(start + 1, start + limit + 1)
            ]
            return FakeResponse(200, payload={"subjects": subjects})
        raise AssertionError(f"Unexpected URL: {url}")


def test_popular_collector_paginates_and_builds_normalized_snapshot():
    client = FakeClient()
    sleeps = []
    collector = DoubanTaggedChartCollector(
        client=client,
        sleeper=sleeps.append,
        max_items=45,
    )

    snapshot = collector.collect("popular", date(2026, 11, 23))

    requests = [
        params for url, params in client.requests if url == SEARCH_SUBJECTS_URL
    ]
    assert [item["page_start"] for item in requests] == [0, 20, 40]
    assert [item["page_limit"] for item in requests] == [20, 20, 5]
    assert all(item["tag"] == "热门" for item in requests)
    assert len(sleeps) == 2
    assert all(delay >= 2.0 for delay in sleeps)
    assert snapshot.slug == "popular"
    assert snapshot.category == "popular"
    assert snapshot.source == "douban"
    assert len(snapshot.movies) == 45
    assert snapshot.movies[0].rank == 1
    assert snapshot.movies[-1].rank == 45
    assert snapshot.movies[0].year is None
    assert snapshot.movies[0].rating == 8.8


def test_high_rated_collector_uses_high_rated_tag():
    client = FakeClient()
    snapshot = DoubanTaggedChartCollector(
        client=client,
        sleeper=lambda _: None,
        max_items=5,
    ).collect("high-rated", date(2026, 11, 23))

    request = next(
        params for url, params in client.requests if url == SEARCH_SUBJECTS_URL
    )
    assert request["tag"] == "豆瓣高分"
    assert snapshot.slug == "high-rated"
    assert snapshot.category == "rating"
    assert len(snapshot.movies) == 5


def test_tagged_collector_respects_robots_and_stops_on_rate_limit():
    blocked = FakeClient(robots_text="User-agent: *\nDisallow: /j/")
    with pytest.raises(DoubanCollectionError, match="robots.txt disallows"):
        DoubanTaggedChartCollector(client=blocked).collect(
            "popular", date(2026, 11, 23)
        )
    assert blocked.requests == [(ROBOTS_URL, None)]

    limited = FakeClient(page_status=429)
    with pytest.raises(DoubanCollectionError, match="HTTP 429"):
        DoubanTaggedChartCollector(client=limited).collect(
            "popular", date(2026, 11, 23)
        )
    assert len([
        url for url, _ in limited.requests if url == SEARCH_SUBJECTS_URL
    ]) == 1


def test_tagged_collector_rejects_duplicate_ids_and_unsafe_poster_hosts():
    class DuplicateClient(FakeClient):
        def get(self, url, params=None):
            response = super().get(url, params)
            if url == SEARCH_SUBJECTS_URL:
                response.payload["subjects"][1]["id"] = response.payload["subjects"][0]["id"]
                response.text = json.dumps(response.payload)
                response.content = response.text.encode("utf-8")
            return response

    with pytest.raises(DoubanCollectionError, match="Duplicate movie ID"):
        DoubanTaggedChartCollector(
            client=DuplicateClient(),
            max_items=20,
        ).collect("popular", date(2026, 11, 23))

    client = FakeClient()
    snapshot = DoubanTaggedChartCollector(
        client=client,
        sleeper=lambda _: None,
        max_items=1,
    ).collect("popular", date(2026, 11, 23))
    assert snapshot.movies[0].posters[0].startswith("https://img2.doubanio.com/")


def test_tagged_collector_validates_chart_and_request_bounds():
    with pytest.raises(ValueError, match="Unsupported Douban chart"):
        DoubanTaggedChartCollector(client=FakeClient()).collect(
            "annual", date(2026, 11, 23)
        )
    with pytest.raises(ValueError, match="max_items"):
        DoubanTaggedChartCollector(client=FakeClient(), max_items=501)
    with pytest.raises(ValueError, match="at least 2.0 seconds"):
        DoubanTaggedChartCollector(client=FakeClient(), request_delay=1.0)


def test_tagged_collector_honors_robots_crawl_delay():
    client = FakeClient(
        robots_text="User-agent: *\\nAllow: /\\nCrawl-delay: 4"
    )
    sleeps = []
    DoubanTaggedChartCollector(
        client=client,
        sleeper=sleeps.append,
        max_items=45,
    ).collect("popular", date(2026, 11, 23))

    assert len(sleeps) == 2
    assert all(delay == 4.0 for delay in sleeps)
