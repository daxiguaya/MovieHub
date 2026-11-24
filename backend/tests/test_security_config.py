"""Security defaults for cross-origin API access."""

from fastapi.middleware.cors import CORSMiddleware

from app.config import Settings
from app.main import app


def test_cors_origins_are_explicitly_configurable_from_environment(monkeypatch):
    monkeypatch.setenv(
        "MOVIEHUB_CORS_ORIGINS",
        '["https://moviehub.example.com","https://admin.example.com"]',
    )

    configured = Settings()
    assert configured.cors_origins == [
        "https://moviehub.example.com",
        "https://admin.example.com",
    ]


def test_app_disables_wildcard_credentialed_cors_by_default():
    cors = next(
        middleware
        for middleware in app.user_middleware
        if middleware.cls is CORSMiddleware
    )

    assert cors.kwargs["allow_origins"] == []
    assert cors.kwargs["allow_credentials"] is False
