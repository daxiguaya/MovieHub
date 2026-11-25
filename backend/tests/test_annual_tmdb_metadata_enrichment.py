"""Tests for identity-checked annual TMDB metadata enrichment."""
from types import SimpleNamespace

import pytest

from scripts.enrich_annual_tmdb_metadata import _blank, _extract


def _movie(**overrides):
    values = {
        "id": 251,
        "tmdb_id": "1500536",
        "type": "movie",
        "title": "南京照相馆",
        "original_title": None,
        "year": None,
        "directors": '["申奥"]',
        "actors": "[]",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_extracts_missing_fields_from_existing_tmdb_identity():
    payload = {
        "id": 1500536,
        "title": "南京照相馆",
        "original_title": "Dead to Rights",
        "release_date": "2025-07-25",
        "genres": [{"name": "剧情"}, {"name": "历史"}],
        "production_countries": [{"iso_3166_1": "CN"}],
        "credits": {
            "crew": [{"job": "Director", "name": "申奥"}],
            "cast": [{"name": "刘昊然"}, {"name": "王传君"}],
        },
    }
    result = _extract(_movie(), payload)
    assert result["original_title"] == "Dead to Rights"
    assert result["year"] == 2025
    assert result["actors"] == ["刘昊然", "王传君"]
    assert result["genres"] == ["剧情", "历史"]
    assert result["regions"] == ["中国大陆"]


def test_rejects_tmdb_title_or_director_identity_mismatch():
    payload = {
        "id": 1500536,
        "title": "完全不同的电影",
        "original_title": "Another Film",
        "release_date": "2025-01-01",
        "credits": {"crew": [{"job": "Director", "name": "其他导演"}], "cast": []},
    }
    with pytest.raises(ValueError, match="title identity mismatch"):
        _extract(_movie(), payload)


def test_blank_treats_empty_json_list_as_missing_but_preserves_values():
    assert _blank(None)
    assert _blank("")
    assert _blank("[]")
    assert not _blank('["已有演员"]')
    assert not _blank(2025)
