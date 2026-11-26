"""IMDb title identifier validation tests."""

import pytest
from pydantic import ValidationError

from app.routers.discovery import FavoriteSnapshot
from app.routers.favorites import ExternalFavoriteSnapshot
from app.services.imdb_ids import is_valid_imdb_id


@pytest.mark.parametrize(
    "value",
    ["tt1234567", "tt0000042", "tt123456789012"],
)
def test_valid_imdb_title_ids(value):
    assert is_valid_imdb_id(value)


@pytest.mark.parametrize(
    "value",
    [
        None,
        "",
        "tt123456",
        "tt1234567890123",
        "ttabcdefg",
        "TT1234567",
        " tt1234567",
        "tt1234567 ",
        1234567,
    ],
)
def test_invalid_imdb_title_ids(value):
    assert not is_valid_imdb_id(value)


@pytest.mark.parametrize(
    "snapshot_model",
    [ExternalFavoriteSnapshot, FavoriteSnapshot],
)
def test_favorite_payload_models_reject_malformed_imdb_ids(snapshot_model):
    with pytest.raises(ValidationError):
        snapshot_model.model_validate({
            "title": "Example",
            "imdb_id": "tt-not-an-id",
        })


@pytest.mark.parametrize(
    "snapshot_model",
    [ExternalFavoriteSnapshot, FavoriteSnapshot],
)
def test_favorite_payload_models_allow_missing_imdb_ids(snapshot_model):
    snapshot = snapshot_model.model_validate({"title": "Example", "imdb_id": None})
    assert snapshot.imdb_id is None
