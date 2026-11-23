
"""Initialize built-in chart definitions without overwriting user settings."""

import logging
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.cache import cache_manager
from app.database import Chart
from app.chart_definitions import INITIAL_CHARTS

logger = logging.getLogger("moviehub.chart_init")


def _get(definition: Any, name: str, default: Any = None) -> Any:
    if isinstance(definition, dict):
        return definition.get(name, default)
    return getattr(definition, name, default)


def initialize_chart_definitions(db: Session) -> dict[str, int]:
    """Insert missing built-in charts.

    Existing chart settings are deliberately left unchanged:
    enabled, display_order, name, description and other user edits
    are not reset during initialization.
    
    The caller must provide a fresh session without an active transaction.
    """
    if db.in_transaction():
        raise RuntimeError(
            "Chart initialization requires a session without an active transaction"
        )

    created = 0
    existing = 0
    now = datetime.utcnow()

    try:
        with db.begin():
            for definition in INITIAL_CHARTS:
                slug = _get(definition, "slug")
                name = _get(definition, "name")
                source = _get(definition, "source", "douban")
                category = _get(definition, "category", "general")

                if not slug or not name:
                    logger.warning(
                        "Skipping invalid built-in chart definition: %r",
                        definition,
                    )
                    continue

                chart = db.scalar(
                    select(Chart).where(Chart.slug == slug)
                )

                if chart is not None:
                    existing += 1
                    continue

                chart = Chart(
                    slug=slug,
                    name=name,
                    source=source,
                    category=category,
                    period=_get(definition, "period"),
                    description=_get(definition, "description"),
                    enabled=True,
                    display_order=_get(
                        definition,
                        "display_order",
                        0,
                    ),
                    last_updated=None,
                    created_at=now,
                    updated_at=now,
                )

                db.add(chart)
                created += 1

        if created:
            cache_manager.clear()

        logger.info(
            "Chart initialization completed: created=%s existing=%s",
            created,
            existing,
        )

        return {
            "created": created,
            "existing": existing,
        }

    except Exception:
        db.rollback()
        logger.exception("Chart initialization failed")
        raise

