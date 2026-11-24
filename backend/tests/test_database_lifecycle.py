"""Database lifecycle guards for the API dependency."""

import pytest

import app.database as database


def test_get_db_does_not_create_a_missing_database_or_parent_directory(
    tmp_path,
    monkeypatch,
):
    missing_path = tmp_path / "not-created" / "movies.db"
    monkeypatch.setattr(
        database,
        "get_db_path",
        lambda: str(missing_path),
    )

    with pytest.raises(database.DatabaseNotInitializedError):
        next(database.get_db())

    assert not missing_path.exists()
    assert not missing_path.parent.exists()
