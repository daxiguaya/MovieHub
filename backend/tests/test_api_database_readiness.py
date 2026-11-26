"""API behavior when the MovieHub database has not been initialized."""

from fastapi.testclient import TestClient

import app.database as database
import app.main as main_module


def test_data_api_returns_503_without_creating_database(
    tmp_path,
    monkeypatch,
):
    missing_path = tmp_path / "missing-db" / "movies.db"
    monkeypatch.setattr(database, "get_db_path", lambda: str(missing_path))
    monkeypatch.setattr(main_module, "get_db_path", lambda: str(missing_path))
    monkeypatch.setattr(
        main_module.poster_cache_service,
        "clear_expired_cache",
        lambda: None,
    )

    with TestClient(main_module.app) as client:
        response = client.get("/api/movies")
        readiness = client.get("/api/ready")

    assert response.status_code == 503
    assert readiness.status_code == 503
    assert "python -m scripts.init_db" in response.json()["detail"]
    assert not missing_path.exists()
    assert not missing_path.parent.exists()


def test_data_api_returns_503_for_existing_database_with_old_schema(
    tmp_path,
    monkeypatch,
):
    import sqlite3

    old_schema_path = tmp_path / "old-schema" / "movies.db"
    old_schema_path.parent.mkdir(parents=True)
    connection = sqlite3.connect(old_schema_path)
    try:
        connection.execute("CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY)")
        connection.execute("INSERT INTO schema_migrations (version) VALUES (4)")
        connection.commit()
    finally:
        connection.close()

    monkeypatch.setattr(database, "get_db_path", lambda: str(old_schema_path))
    monkeypatch.setattr(main_module, "get_db_path", lambda: str(old_schema_path))
    monkeypatch.setattr(
        main_module.poster_cache_service,
        "clear_expired_cache",
        lambda: None,
    )

    with TestClient(main_module.app) as client:
        response = client.get("/api/movies")
        readiness = client.get("/api/ready")

    assert response.status_code == 503
    assert readiness.status_code == 503
    assert "schema is not ready" in response.json()["detail"]
    assert "python -m scripts.migrate" in response.json()["detail"]
    assert old_schema_path.is_file()
