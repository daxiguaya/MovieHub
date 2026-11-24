"""Ensure chart snapshot import is not reachable without the server API key."""

from fastapi.testclient import TestClient

import app.main as main_module
from app.config import settings


def test_chart_snapshot_import_rejects_missing_and_invalid_api_keys(monkeypatch):
    monkeypatch.setattr(settings, "api_key", "chart-import-test-secret")
    monkeypatch.setattr(
        main_module.poster_cache_service,
        "clear_expired_cache",
        lambda: None,
    )
    payload = {
        "slug": "private-test-chart",
        "name": "Private Test Chart",
        "source": "operator",
        "category": "movie",
        "snapshot_date": "2026-11-24",
        "movies": [
            {
                "douban_id": "1234567",
                "rank": 1,
                "title": "Security Fixture",
                "type": "movie",
            }
        ],
    }

    with TestClient(main_module.app) as client:
        missing = client.post("/api/charts/import", json=payload)
        invalid = client.post(
            "/api/charts/import",
            headers={"X-API-Key": "wrong-secret"},
            json=payload,
        )

    assert missing.status_code == 401
    assert invalid.status_code == 401
