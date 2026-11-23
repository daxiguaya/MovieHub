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

    assert response.status_code == 503
    assert "python -m scripts.init_db" in response.json()["detail"]
    assert not missing_path.exists()
    assert not missing_path.parent.exists()
