from datetime import date

import pytest

from app.adapters.douban_top250 import (
    DOUBAN_BASE_URL,
    PAGE_COUNT,
    PAGE_SIZE,
    ROBOTS_URL,
    TOP250_URL,
    DoubanCollectionError,
    DoubanTop250Collector,
    parse_top250_page,
)


def _item(rank: int) -> str:
    douban_id = str(1000000 + rank)
    return f"""
    <div class="item">
      <div class="pic">
        <em class="">{rank}</em>
        <a href="{DOUBAN_BASE_URL}/subject/{douban_id}/">
          <img src="https://img1.doubanio.com/view/photo/s_ratio_poster/public/{douban_id}.jpg" />
        </a>
      </div>
      <div class="info">
        <div class="hd">
          <a href="{DOUBAN_BASE_URL}/subject/{douban_id}/">
            <span class="title">电影 {rank}</span>
            <span class="title"> / Original Movie {rank}</span>
          </a>
        </div>
        <div class="bd">
          <p>导演: 导演 {rank}<br/>2000 / 中国大陆 / 剧情 科幻</p>
          <span class="rating_num">8.5</span>
          <span class="pl">(123,456人评价)</span>
        </div>
      </div>
    </div>
    """


def _page(start: int) -> str:
    return "<html><body>" + "".join(
        _item(rank)
        for rank in range(start + 1, start + PAGE_SIZE + 1)
    ) + "</body></html>"


class FakeResponse:
    def __init__(self, status_code: int, text: str = "", headers=None):
        self.status_code = status_code
        self.text = text
        self.content = text.encode("utf-8")
        self.headers = headers or {}


class FakeClient:
    def __init__(self, page_status: int = 200, robots_text: str = "User-agent: *\nAllow: /"):
        self.page_status = page_status
        self.robots_text = robots_text
        self.requests = []

    def get(self, url, params=None):
        self.requests.append((url, params))
        if url == ROBOTS_URL:
            return FakeResponse(200, self.robots_text)
        if url == TOP250_URL:
            if self.page_status != 200:
                return FakeResponse(
                    self.page_status,
                    "blocked",
                    {"Retry-After": "60"},
                )
            start = int(params["start"])
            return FakeResponse(200, _page(start))
        raise AssertionError(f"Unexpected URL: {url}")


def test_parse_top250_page_extracts_normalized_movie_fields():
    html = open("tests/fixtures/douban_top250_page.html", encoding="utf-8").read()

    [movie] = parse_top250_page(html)

    assert movie.douban_id == "1292052"
    assert movie.rank == 1
    assert movie.title == "肖申克的救赎"
    assert movie.original_title == "The Shawshank Redemption"
    assert movie.year == 1994
    assert movie.rating == 9.7
    assert movie.rating_count == 3367321
    assert movie.regions == ["美国"]
    assert movie.genres == ["犯罪", "剧情"]
    assert movie.posters == [
        "https://img1.doubanio.com/view/photo/s_ratio_poster/public/example.jpg"
    ]
    assert movie.douban_url == f"{DOUBAN_BASE_URL}/subject/1292052/"


def test_collector_checks_robots_and_paces_all_ten_top250_pages():
    client = FakeClient()
    sleeps = []
    collector = DoubanTop250Collector(
        client=client,
        sleeper=sleeps.append,
    )

    snapshot = collector.collect(date(2026, 11, 23))

    page_requests = [
        (url, params)
        for url, params in client.requests
        if url == TOP250_URL
    ]
    assert len(page_requests) == PAGE_COUNT
    assert [params["start"] for _, params in page_requests] == list(
        range(0, 250, PAGE_SIZE)
    )
    assert len(sleeps) == PAGE_COUNT - 1
    assert all(delay >= 2.0 for delay in sleeps)
    assert snapshot.slug == "top250"
    assert snapshot.source == "douban"
    assert snapshot.snapshot_date == date(2026, 11, 23)
    assert len(snapshot.movies) == 250
    assert snapshot.movies[0].rank == 1
    assert snapshot.movies[-1].rank == 250
    assert snapshot.movies[-1].douban_id == "1000250"


def test_collector_refuses_robots_disallowed_path_without_fetching_pages():
    client = FakeClient(
        robots_text="User-agent: *\nDisallow: /top250"
    )
    collector = DoubanTop250Collector(client=client)

    with pytest.raises(DoubanCollectionError, match="robots.txt disallows"):
        collector.collect(date(2026, 11, 23))

    assert client.requests == [(ROBOTS_URL, None)]


def test_collector_stops_on_rate_limit_without_retrying():
    client = FakeClient(page_status=429)
    collector = DoubanTop250Collector(client=client)

    with pytest.raises(DoubanCollectionError, match="HTTP 429"):
        collector.collect(date(2026, 11, 23))

    assert len([url for url, _ in client.requests if url == TOP250_URL]) == 1


def test_collector_rejects_request_delay_below_safe_minimum():
    with pytest.raises(ValueError, match="at least 2.0 seconds"):
        DoubanTop250Collector(client=FakeClient(), request_delay=0.1)


def test_top250_collector_honors_robots_crawl_delay():
    client = FakeClient(
        robots_text="User-agent: *\nAllow: /\nCrawl-delay: 5"
    )
    sleeps = []
    DoubanTop250Collector(
        client=client,
        sleeper=sleeps.append,
    ).collect(date(2026, 11, 23))

    assert len(sleeps) == PAGE_COUNT - 1
    assert all(delay == 5.0 for delay in sleeps)


def test_top250_parser_falls_back_to_visible_text_for_rating_count_and_credits():
    html = f"""
    <div class="item">
      <div class="pic">
        <em>1</em>
        <a href="{DOUBAN_BASE_URL}/subject/1292052/">
          <img src="https://img1.doubanio.com/poster.jpg" />
        </a>
      </div>
      <div class="info">
        <div class="hd">
          <a href="{DOUBAN_BASE_URL}/subject/1292052/">
            <span class="title">肖申克的救赎</span>
          </a>
        </div>
        <div class="bd">
          <p>导演: 弗兰克·德拉邦特 Frank Darabont 主演: 蒂姆·罗宾斯 Tim Robbins / 摩根·弗里曼 Morgan Freeman<br/>1994 / 美国 / 犯罪 剧情</p>
          <span class="rating_num">9.7</span>
          <span>3367640人评价</span>
        </div>
      </div>
    </div>
    """

    [movie] = parse_top250_page(html)

    assert movie.rating_count == 3367640
    assert movie.directors == ["弗兰克·德拉邦特 Frank Darabont"]
    assert movie.actors == [
        "蒂姆·罗宾斯 Tim Robbins",
        "摩根·弗里曼 Morgan Freeman",
    ]
