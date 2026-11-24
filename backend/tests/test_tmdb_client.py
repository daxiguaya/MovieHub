"""TMDB client response sanitization tests."""
from app.services.tmdb_client import _strip_unapproved_synopsis


def test_tmdb_overview_is_removed_recursively_before_persistence():
    payload = {
        "id": 10,
        "title": "Example",
        "overview": "Do not persist this synopsis",
        "results": [
            {"id": 11, "title": "Nested", "overview": "Also remove this"},
            {"id": 12, "title": "No synopsis"}
        ],
        "credits": {"cast": [{"name": "Actor", "overview": "Nested arbitrary text"}]}
    }
    sanitized = _strip_unapproved_synopsis(payload)

    assert "overview" not in sanitized
    assert all("overview" not in item for item in sanitized["results"])
    assert "overview" not in sanitized["credits"]["cast"][0]
    assert sanitized["results"][0]["title"] == "Nested"
