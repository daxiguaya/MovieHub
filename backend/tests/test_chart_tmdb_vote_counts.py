"""Tests for source-safe TMDB vote counts on annual chart cards."""

from types import SimpleNamespace

import pytest

from app.routers.charts import _extract_tmdb_votes


@pytest.mark.parametrize(
    "item,payload,expected",
    [
        (
            SimpleNamespace(id=1, tmdb_id="123", type="movie", title="测试电影", original_title=None),
            {"id": 123, "title": "测试电影", "vote_average": 7.8, "vote_count": 1200},
            (7.8, 1200),
        ),
        (
            SimpleNamespace(id=2, tmdb_id="812583", type="movie", title="利刃出鞘3", original_title=None),
            {"id": 812583, "title": "利刃出鞘3亡者归来", "vote_average": 7.2, "vote_count": 900},
            (7.2, 900),
        ),
        (
            SimpleNamespace(id=3, tmdb_id="225941", type="tv", title="异人之下之决战！碧游村", original_title=None),
            {"id": 225941, "name": "异人之下", "vote_average": 8.0, "vote_count": 500},
            None,
        ),
        (
            SimpleNamespace(id=4, tmdb_id="123", type="movie", title="测试电影", original_title=None),
            {"id": 999, "title": "测试电影", "vote_average": 7.8, "vote_count": 1200},
            None,
        ),
        (
            SimpleNamespace(id=5, tmdb_id="123", type="movie", title="测试电影", original_title=None),
            {"id": 123, "title": "测试电影", "vote_average": 7.8, "vote_count": -1},
            None,
        ),
    ],
)
def test_extract_tmdb_votes_requires_exact_identity_and_valid_count(item, payload, expected):
    assert _extract_tmdb_votes(item, payload) == expected
