"""Tests for idempotent built-in chart definition initialization."""

from datetime import datetime

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.database import Base, Chart
from app.services import chart_init_service


def _session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return engine, Session(engine, expire_on_commit=False)


def test_chart_initialization_preserves_existing_user_settings(monkeypatch):
    definitions = [
        {
            "slug": "built-in-chart",
            "name": "Default name",
            "source": "test",
            "category": "general",
            "display_order": 1,
        },
        {
            "slug": "new-built-in-chart",
            "name": "New chart",
            "source": "test",
            "category": "general",
            "display_order": 2,
        },
    ]
    monkeypatch.setattr(chart_init_service, "INITIAL_CHARTS", definitions)
    engine, db = _session()
    try:
        customized = Chart(
            slug="built-in-chart",
            name="User customized name",
            source="custom-source",
            category="custom-category",
            enabled=False,
            display_order=99,
            description="Keep this description",
            created_at=datetime(2026, 1, 1),
            updated_at=datetime(2026, 1, 2),
        )
        db.add(customized)
        db.commit()

        result = chart_init_service.initialize_chart_definitions(db)
        assert result == {"created": 1, "existing": 1}

        preserved = db.scalar(
            select(Chart).where(Chart.slug == "built-in-chart")
        )
        assert preserved.name == "User customized name"
        assert preserved.source == "custom-source"
        assert preserved.category == "custom-category"
        assert preserved.enabled is False
        assert preserved.display_order == 99
        assert preserved.description == "Keep this description"

        created = db.scalar(
            select(Chart).where(Chart.slug == "new-built-in-chart")
        )
        assert created is not None
        assert created.enabled is True
        assert created.display_order == 2

        # The reads above trigger SQLAlchemy autobegin. End that read-only
        # transaction before calling the initializer, which intentionally
        # requires ownership of a transaction-free session.
        db.rollback()

        second_run = chart_init_service.initialize_chart_definitions(db)
        assert second_run == {"created": 0, "existing": 2}
        assert db.query(Chart).count() == 2
    finally:
        db.close()
        engine.dispose()


def test_chart_initialization_requires_fresh_session(monkeypatch):
    monkeypatch.setattr(chart_init_service, "INITIAL_CHARTS", [])
    engine, db = _session()
    try:
        # A query starts an implicit SQLAlchemy transaction.
        db.query(Chart).count()
        try:
            chart_init_service.initialize_chart_definitions(db)
        except RuntimeError as exc:
            assert "without an active transaction" in str(exc)
        else:
            raise AssertionError("An active transaction must be rejected")
    finally:
        db.close()
        engine.dispose()
