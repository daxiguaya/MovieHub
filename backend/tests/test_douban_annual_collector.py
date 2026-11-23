from datetime import date
import json

import pytest

from app.adapters.douban_annual import (
    ANNUAL_CHARTS,
    ANNUAL_ROBOTS_URL,
    ANNUAL_SOURCE_URL,
    DoubanAnnualChartCollector,
    parse_annual_article,
)
from app.adapters.douban_top250 import DoubanCollectionError


ARTICLE = """
<html><body>
<h1>豆瓣2025年度书影音榜单</h1>
<h2>2025评分最高的华语电影</h2>
<table><tr><th>排名</th><th>片名</th><th>导演</th><th>评分</th></tr>
<tr><td>1、</td><td><a href="https://movie.douban.com/subject/36809864/">南京照相馆</a></td><td>申奥</td><td>8.8</td></tr>
<tr><td>2、</td><td><a href="https://movie.douban.com/subject/34780991/">哪吒之魔童闹海</a></td><td>饺子</td><td>8.4</td></tr>
<tr><td>9、</td><td>空缺</td><td></td><td></td></tr>
</table>
<h2>2025评分最高的外语电影</h2>
<table><tr><td>1、</td><td><a href="https://movie.douban.com/subject/35689244/">F1：狂飙飞车</a></td><td>约瑟夫·科辛斯基</td><td>8.7</td></tr></table>
<h2>2025年度冷门佳片</h2>
<table><tr><td>1、</td><td><a href="https://movie.douban.com/subject/36752929/">夜班</a></td><td>佩特拉·比翁迪娜·沃尔普</td><td>8.4</td></tr></table>
<h2>2025评分最高华语剧集</h2>
<table><tr><td>1、</td><td><a href="https://movie.douban.com/subject/36656706/">无尽的尽头</a></td><td>臧溪川</td><td>8.5</td></tr></table>
</body></html>
"""


class Response:
    def __init__(self, status_code, text="", headers=None):
        self.status_code = status_code
        self.text = text
        self.content = text.encode("utf-8")
        self.headers = headers or {}


class Client:
    def __init__(self, robots="User-agent: *\nAllow: /", article=ARTICLE, status=200):
        self.robots = robots
        self.article = article
        self.status = status
        self.requests = []

    def get(self, url):
        self.requests.append(url)
        if url == ANNUAL_ROBOTS_URL:
            return Response(200, self.robots)
        if url == ANNUAL_SOURCE_URL:
            return Response(self.status, self.article)
        raise AssertionError(url)


def test_parser_builds_four_separate_2025_charts_and_preserves_rank_gaps():
    snapshots = parse_annual_article(ARTICLE, date(2026, 11, 23))

    assert set(snapshots) == set(ANNUAL_CHARTS)
    assert len(snapshots["annual-2025-chinese-movies"].movies) == 2
    chinese = snapshots["annual-2025-chinese-movies"].movies
    assert [item.rank for item in chinese] == [1, 2]
    assert [item.douban_id for item in chinese] == ["36809864", "34780991"]
    assert chinese[0].rating == 8.8
    assert chinese[0].directors == ["申奥"]

    assert snapshots["annual-2025-chinese-tv"].movies[0].type == "tv"
    assert snapshots["annual-2025-hidden-gems"].movies[0].type == "movie"
    assert all(item.category == "annual" and item.period == "2025" for item in snapshots.values())


def test_parser_finds_subject_link_when_title_cell_is_not_second_cell():
    shifted = ARTICLE.replace(
        '<tr><td>1、</td><td><a href="https://movie.douban.com/subject/36656706/">无尽的尽头</a></td><td>臧溪川</td><td>8.5</td></tr>',
        '<tr><td>1、</td><td></td><td><a href="//movie.douban.com/subject/36656706/">无尽的尽头</a></td><td>臧溪川</td><td>8.5</td></tr>',
    )
    snapshots = parse_annual_article(shifted, date(2026, 11, 23))
    item = snapshots["annual-2025-chinese-tv"].movies[0]
    assert item.douban_id == "36656706"
    assert item.title == "无尽的尽头"
    assert item.directors == ["臧溪川"]
    assert item.rating == 8.5


def test_parser_rejects_untrusted_subject_hosts_and_missing_chart_sections():
    unsafe = ARTICLE.replace(
        "https://movie.douban.com/subject/36809864/",
        "https://evil.example/subject/36809864/",
    )
    with pytest.raises(DoubanCollectionError, match="without a valid Douban subject link"):
        parse_annual_article(unsafe, date(2026, 11, 23))

    with pytest.raises(DoubanCollectionError, match="did not yield entries"):
        parse_annual_article("<h2>2025年度书影音</h2>", date(2026, 11, 23))


def test_collector_checks_robots_and_fetches_article_once():
    client = Client()
    sleeps = []
    snapshots = DoubanAnnualChartCollector(
        client=client,
        sleeper=sleeps.append,
    ).collect(date(2026, 11, 23))

    assert len(snapshots) == 4
    assert client.requests == [ANNUAL_ROBOTS_URL, ANNUAL_SOURCE_URL]
    assert len(sleeps) == 1 and sleeps[0] >= 2.0


def test_collector_fails_closed_on_robots_denial_and_http_rate_limit():
    denied = Client(robots="User-agent: *\nDisallow: /douban/")
    with pytest.raises(DoubanCollectionError, match="robots.txt disallows"):
        DoubanAnnualChartCollector(client=denied).collect(date(2026, 11, 23))
    assert denied.requests == [ANNUAL_ROBOTS_URL]

    limited = Client(status=429)
    with pytest.raises(DoubanCollectionError, match="rate-limited"):
        DoubanAnnualChartCollector(client=limited).collect(date(2026, 11, 23))
    assert limited.requests == [ANNUAL_ROBOTS_URL, ANNUAL_SOURCE_URL]


def test_parser_rejects_duplicate_ids_and_out_of_range_ranks():
    duplicate = ARTICLE.replace(
        "https://movie.douban.com/subject/34780991/",
        "https://movie.douban.com/subject/36809864/",
    )
    with pytest.raises(DoubanCollectionError, match="Duplicate ID or rank"):
        parse_annual_article(duplicate, date(2026, 11, 23))

    invalid_rank = ARTICLE.replace("<td>1、</td>", "<td>11、</td>", 1)
    with pytest.raises(DoubanCollectionError, match="Unexpected annual rank"):
        parse_annual_article(invalid_rank, date(2026, 11, 23))
