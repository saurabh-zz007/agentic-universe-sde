"""
Database models for webhooks, outcome deduplication, and global DND registry.
"""
from __future__ import annotations

from sqlalchemy import Column, String

from solution.app.core.database import AwareDateTime, Base


class DndRecord(Base):
    __tablename__ = "dnd_registry"

    phone = Column(String, primary_key=True)
    registered_at = Column(AwareDateTime, nullable=False)
    source_campaign_id = Column(String, nullable=False)
    source_lead_id = Column(String, nullable=False)


class ProcessedWebhook(Base):
    __tablename__ = "processed_webhooks"

    call_sid = Column(String, primary_key=True)
    processed_at = Column(AwareDateTime, nullable=False)

