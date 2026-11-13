"""
Database connection, session management, and schema initialization for PostgreSQL.
"""
from __future__ import annotations

import json
import logging
from contextlib import contextmanager
from datetime import datetime
from typing import Generator, Optional

from sqlalchemy import DateTime, TypeDecorator, create_engine, text
from sqlalchemy.orm import Session, declarative_base, sessionmaker

from solution.app.core.clock import IST
from solution.app.core.config import FixturesData, load_campaign_leads, settings

logger = logging.getLogger("solution.database")

Base = declarative_base()


class AwareDateTime(TypeDecorator):
    """DateTime type that always returns timezone-aware datetimes in IST."""
    impl = DateTime(timezone=True)
    cache_ok = True

    def process_result_value(self, value, dialect):
        if value is not None and value.tzinfo is None:
            return value.replace(tzinfo=IST)
        return value


_engine = None
_session_factory = None


def get_engine(db_url: Optional[str] = None):
    global _engine
    if _engine is not None and db_url is None:
        return _engine

    url = db_url or settings.database_url
    # Normalize postgresql:// to use psycopg if not specified
    if url.startswith("postgresql://") and "+psycopg" not in url:
        url = url.replace("postgresql://", "postgresql+psycopg://", 1)

    engine = create_engine(
        url,
        pool_pre_ping=True,
        echo=False,
    )
    _engine = engine
    return _engine


def get_session_factory(engine=None):
    global _session_factory
    if _session_factory is None or engine is not None:
        eng = engine or get_engine()
        _session_factory = sessionmaker(
            bind=eng, autocommit=False, autoflush=False, expire_on_commit=False
        )
    return _session_factory


@contextmanager
def get_session() -> Generator[Session, None, None]:
    """Provide a transactional database session."""
    factory = get_session_factory()
    session: Session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def init_db(fixtures: FixturesData, sim_now: datetime) -> None:
    """
    Creates tables if they do not exist and idempotently seeds
    tenants, campaigns, and leads if not already present.
    Preserves all existing states on crash/restart.
    """
    from solution.app.features.dispatch.models import Campaign, Lead, Tenant
    from solution.app.features.dispatch.service import next_window_open
    from solution.app.features.webhooks.models import DndRecord, ProcessedWebhook

    engine = get_engine()
    Base.metadata.create_all(bind=engine)

    with get_session() as session:
        # Seed Tenants
        for t in fixtures.tenants:
            existing_tenant = session.get(Tenant, t.tenant_id)
            if not existing_tenant:
                session.add(
                    Tenant(
                        tenant_id=t.tenant_id,
                        max_concurrent_calls=t.max_concurrent_calls,
                    )
                )

        # Seed Campaigns
        for c in fixtures.campaigns:
            existing_camp = session.get(Campaign, c.campaign_id)
            if not existing_camp:
                session.add(
                    Campaign(
                        campaign_id=c.campaign_id,
                        tenant_id=c.tenant_id,
                        leads_file=c.leads_file,
                        window_start=c.window.start,
                        window_end=c.window.end,
                        window_days_json=json.dumps(c.window.days),
                        max_attempts=c.max_attempts,
                    )
                )
        session.flush()

        # Seed Leads
        for c in fixtures.campaigns:
            camp_dict = {
                "start": c.window.start,
                "end": c.window.end,
                "days": c.window.days,
            }
            earliest_eligible = next_window_open(
                sim_now, camp_dict, fixtures.regulatory_window
            )

            leads_data = load_campaign_leads(settings.fixtures_path, c.leads_file)
            for row in leads_data:
                lid = row["lead_id"]
                phone = row["phone"]
                name = row.get("customer_name")
                existing_lead = session.get(Lead, (c.campaign_id, lid))
                if not existing_lead:
                    session.add(
                        Lead(
                            campaign_id=c.campaign_id,
                            lead_id=lid,
                            phone=phone,
                            customer_name=name,
                            state="fresh",
                            attempts=0,
                            next_eligible_at=earliest_eligible,
                            updated_at=sim_now,
                        )
                    )
        session.commit()
    logger.info("Database initialized successfully.")
