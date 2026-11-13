"""
Pytest fixtures for unit and integration testing of the feature-first app.
"""
from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import datetime
from typing import Generator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from solution.app.core.clock import FakeClock, IST
from solution.app.core.config import (
    CampaignConfig,
    CampaignWindow,
    FixturesData,
    RetryPolicy,
    TenantConfig,
)
from solution.app.core.database import Base
from solution.app.features.dispatch.models import Call, Campaign, Lead, Tenant
from solution.app.features.webhooks.models import DndRecord, ProcessedWebhook


@pytest.fixture
def fake_sim_start() -> datetime:
    # Thursday 12 Nov 2026, 17:30 IST
    return datetime(2026, 11, 12, 17, 30, tzinfo=IST)


@pytest.fixture
def fake_clock(fake_sim_start: datetime) -> FakeClock:
    return FakeClock(fake_sim_start, speed=600.0)


@pytest.fixture
def sample_fixtures() -> FixturesData:
    return FixturesData(
        sim_start="2026-11-12T17:30:00+05:30",
        timezone="Asia/Kolkata",
        regulatory_window={"start": "09:00", "end": "21:00"},
        window_grace_seconds=120,
        retry_policy=RetryPolicy(
            no_answer_minutes=60,
            busy_minutes=60,
            failed_minutes=15,
        ),
        webhook_secret="test_secret_key_123",
        tenants=[
            TenantConfig(tenant_id="tenant_a", max_concurrent_calls=2),
            TenantConfig(tenant_id="tenant_b", max_concurrent_calls=1),
        ],
        campaigns=[
            CampaignConfig(
                campaign_id="camp_a1",
                tenant_id="tenant_a",
                leads_file="leads_a1.csv",
                window=CampaignWindow(
                    start="10:00",
                    end="19:00",
                    days=["mon", "tue", "wed", "thu", "fri"],
                ),
                max_attempts=3,
            ),
            CampaignConfig(
                campaign_id="camp_a2",
                tenant_id="tenant_a",
                leads_file="leads_a2.csv",
                window=CampaignWindow(
                    start="11:00",
                    end="20:00",
                    days=["mon", "tue", "wed", "thu", "fri", "sat", "sun"],
                ),
                max_attempts=3,
            ),
        ],
    )


@pytest.fixture
def test_db_session() -> Generator[Session, None, None]:
    """In-memory SQLite database with StaticPool for test isolation."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(
        bind=engine, autocommit=False, autoflush=False, expire_on_commit=False
    )
    session = session_factory()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)
