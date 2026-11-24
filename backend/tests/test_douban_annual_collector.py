import re
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


def test_director_names_preserve_multiword_names_and_split_explicit_separators():
    split_directors = lambda value: [
        name.strip() for name in re.split(r"\\s*/\\s*|[、,，;；]", value) if name.strip()
    ]
    assert split_directors("木头 / 顾杰") == ["木头", "顾杰"]
    assert split_directors("唐铁军、吴迪") == ["唐铁军", "吴迪"]
    assert split_directors("Christopher Nolan") == ["Christopher Nolan"]
    assert split_directors("保罗·托马斯·安德森") == ["保罗·托马斯·安德森"]


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


def test_parser_stops_collecting_when_article_moves_to_books_and_music():
    non_movie_sections = ARTICLE.replace(
        "</body></html>",
        """
        <h2>2025年度图书</h2>
        <table><tr><td>1、</td><td>《一本书》</td><td>作者</td><td>9.0</td></tr></table>
        <h2>2025年度高分外语专辑</h2>
        <table><tr><td>1、</td><td>Album</td><td>Artist</td><td>9.0</td></tr></table>
        </body></html>
        """,
    )
    snapshots = parse_annual_article(non_movie_sections, date(2026, 11, 23))
    assert len(snapshots["annual-2025-chinese-tv"].movies) == 1
    assert snapshots["annual-2025-chinese-tv"].movies[0].title == "无尽的尽头"


def test_parser_rejects_untrusted_subject_hosts_and_missing_chart_sections():
    unsafe = ARTICLE.replace(
        "https://movie.douban.com/subject/36809864/",
        "https://evil.example/subject/36809864/",
    )
    with pytest.raises(DoubanCollectionError, match="has no valid Douban subject link"):
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


def test_annual_snapshot_files_are_published_as_a_complete_set(tmp_path, monkeypatch):
    from datetime import date
    import scripts.collect_douban_annual as command

    capture_date = date(2026, 11, 23)
    snapshots = parse_annual_article(ARTICLE, capture_date)
    output_dir = tmp_path / "annual"
    real_replace = command.os.replace
    calls = {"count": 0}

    def fail_second_publish(source, target):
        calls["count"] += 1
        if calls["count"] == 2:
            raise OSError("simulated disk publication failure")
        return real_replace(source, target)

    monkeypatch.setattr(command.os, "replace", fail_second_publish)

    with pytest.raises(OSError, match="simulated disk publication failure"):
        command.write_snapshots(snapshots, output_dir, capture_date)

    assert list(output_dir.glob("annual-*.json")) == []
    assert list(output_dir.glob(".moviehub-annual-*")) == []


def test_annual_snapshot_overwrite_failure_restores_previous_files(tmp_path, monkeypatch):
    from datetime import date
    import scripts.collect_douban_annual as command

    capture_date = date(2026, 11, 23)
    snapshots = parse_annual_article(ARTICLE, capture_date)
    output_dir = tmp_path / "annual"
    output_dir.mkdir()
    targets = {
        slug: output_dir / f"{slug}-{capture_date.isoformat()}.json"
        for slug in ANNUAL_CHARTS
    }
    for path in targets.values():
        path.write_text("old-content", encoding="utf-8")

    real_replace = command.os.replace
    calls = {"count": 0}

    def fail_second_publish(source, target):
        calls["count"] += 1
        if calls["count"] == 2:
            raise OSError("simulated overwrite failure")
        return real_replace(source, target)

    monkeypatch.setattr(command.os, "replace", fail_second_publish)

    with pytest.raises(OSError, match="simulated overwrite failure"):
        command.write_snapshots(snapshots, output_dir, capture_date, overwrite=True)

    assert all(path.read_text(encoding="utf-8") == "old-content" for path in targets.values())
    assert list(output_dir.glob(".moviehub-annual-*")) == []
