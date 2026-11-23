"""Security and status behavior for the protected Scout import API."""

from fastapi.testclient import TestClient

import app.main as main_module
from app.config import settings
from app.routers import data_import as data_import_router
from app.schemas import ImportStatus


def test_import_api_requires_key_and_confines_sources_to_import_directory(
    tmp_path,
    monkeypatch,
):
    import_root = tmp_path / "imports"
    import_root.mkdir()
    allowed_source = import_root / "scout.sqlite"
    allowed_source.write_bytes(b"fixture placeholder")

    outside_source = tmp_path / "outside.sqlite"
    outside_source.write_bytes(b"must not be read")

    escaped_link = import_root / "outside-link.sqlite"
    escaped_link.symlink_to(outside_source)

    monkeypatch.setattr(settings, "import_dir", import_root)
    monkeypatch.setattr(settings, "api_key", "test-api-key")
    monkeypatch.setattr(
        main_module.poster_cache_service,
        "clear_expired_cache",
        lambda: None,
    )

    calls = []

    def fake_start_import(source_path, force_full=False, resume_run_id=None):
        calls.append((source_path, force_full, resume_run_id))
        return ImportStatus(status="running", message="fixture import")

    monkeypatch.setattr(
        data_import_router.import_service,
        "start_import",
        fake_start_import,
    )

    try:
        with TestClient(main_module.app) as client:
            unauthorized = client.post(
                "/api/import",
                json={"source_path": "scout.sqlite"},
            )
            outside = client.post(
                "/api/import",
                headers={"X-API-Key": "test-api-key"},
                json={"source_path": str(outside_source)},
            )
            symlink_escape = client.post(
                "/api/import",
                headers={"X-API-Key": "test-api-key"},
                json={"source_path": "outside-link.sqlite"},
            )
            allowed = client.post(
                "/api/import",
                headers={"X-API-Key": "test-api-key"},
                json={
                    "source_path": "scout.sqlite",
                    "force_full": True,
                    "resume_run_id": "run-123",
                },
            )
            status_response = client.get(
                "/api/import/status",
                headers={"X-API-Key": "test-api-key"},
            )

        assert unauthorized.status_code == 401
        assert outside.status_code == 403
        assert symlink_escape.status_code == 403
        assert allowed.status_code == 200
        assert allowed.json()["status"] == "running"
        assert status_response.status_code == 200
        assert calls == [(str(allowed_source.resolve()), True, "run-123")]
    finally:
        escaped_link.unlink(missing_ok=True)
