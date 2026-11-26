"""Shared validation for IMDb title identifiers."""

import re

_IMDB_ID_PATTERN = re.compile(r"^tt[0-9]{7,12}$")


def is_valid_imdb_id(value: object) -> bool:
    """Return whether value is a syntactically valid IMDb title ID."""
    return isinstance(value, str) and _IMDB_ID_PATTERN.fullmatch(value) is not None
