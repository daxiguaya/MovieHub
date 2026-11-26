"""Tests for conservative annual Douban rating-count enrichment."""
from types import SimpleNamespace

import pytest

from scripts.enrich_douban_rating_counts import _extract_count


def _movie(**overrides):
    values = {
        "id": 1,
        "douban_id": "1292052",
        "type": "movie",
        "title": "肖申克的救赎",
        "original_title": "The Shawshank Redemption",
        "rating_count": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_extracts_douban_rating_count_from_matching_subject():
    payload = {
        "id": "1292052",
        "title": "肖申克的救赎",
        "rating": {"value": 9.7, "count": 3000000},
    }
    assert _extract_count(_movie(), payload) == 3000000


def test_rejects_subject_id_mismatch():
    with pytest.raises(ValueError, match="ID"):
        _extract_count(_movie(), {
            "id": "999",
            "title": "肖申克的救赎",
            "rating": {"count": 10},
        })


def test_rejects_title_mismatch_even_when_id_matches():
    with pytest.raises(ValueError, match="title identity mismatch"):
        _extract_count(_movie(), {
            "id": "1292052",
            "title": "另一部电影",
            "rating": {"count": 10},
        })


@pytest.mark.parametrize("count", [None, "100", -1, True, 1.5])
def test_missing_or_invalid_rating_count_is_not_fabricated(count):
    assert _extract_count(_movie(), {
        "id": "1292052",
        "title": "肖申克的救赎",
        "rating": {"count": count},
    }) is None


def test_missing_rating_object_returns_unknown():
    assert _extract_count(_movie(), {
        "id": "1292052",
        "title": "肖申克的救赎",
    }) is None
