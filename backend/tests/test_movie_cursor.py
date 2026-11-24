"""Validation for opaque movie-list pagination cursors."""

import base64
import json

import pytest

from app.services.movie_service import movie_service


def encode_cursor(payload):
    raw = json.dumps(payload, allow_nan=True, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii")


@pytest.mark.parametrize(
    "payload",
    [
        {"id": True, "value": 1},
        {"id": 0, "value": 1},
        {"id": -1, "value": 1},
        {"id": 9_223_372_036_854_775_808, "value": 1},
        {"id": 1, "value": True},
        {"id": 1, "value": "1"},
        {"id": 1, "value": []},
        {"id": 1, "value": {}},
        {"id": 1, "value": float("nan")},
        {"id": 1, "value": float("inf")},
        {"id": 1, "value": 9_223_372_036_854_775_808},
        {"id": 1},
        {"id": 1, "value": 1, "unexpected": "field"},
        ["not", "an", "object"],
    ],
)
def test_decode_cursor_rejects_malformed_payloads(payload):
    assert movie_service._decode_cursor(encode_cursor(payload)) is None


@pytest.mark.parametrize("value", [None, 0, 9, 9.5, -1.25])
def test_decode_cursor_accepts_generated_numeric_values(value):
    cursor = encode_cursor({"id": 12, "value": value})

    assert movie_service._decode_cursor(cursor) == {
        "id": 12,
        "value": value,
    }


@pytest.mark.parametrize("cursor", ["not-base64", "!!!!", "", None])
def test_decode_cursor_rejects_invalid_encoding(cursor):
    assert movie_service._decode_cursor(cursor) is None
