"""
Database models for dispatch jobs, campaigns, tenants, and calling windows.
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import List, Optional

from sqlalchemy import (
    Column,
    ForeignKey,
    Integer,
    PrimaryKeyConstraint,
    String,
    Text,
)
from sqlalchemy.orm import relationship

from solution.app.core.database import AwareDateTime, Base


class Tenant(Base):
    __tablename__ = "tenants"

    tenant_id = Column(String, primary_key=True)
    max_concurrent_calls = Column(Integer, nullable=False, default=1)

    campaigns = relationship("Campaign", back_populates="tenant")


class Campaign(Base):
    __tablename__ = "campaigns"

    campaign_id = Column(String, primary_key=True)
    tenant_id = Column(String, ForeignKey("tenants.tenant_id"), nullable=False)
    leads_file = Column(String, nullable=False)
    window_start = Column(String, nullable=False)
    window_end = Column(String, nullable=False)
    window_days_json = Column(Text, nullable=False)  # JSON list of days
    max_attempts = Column(Integer, nullable=False, default=3)

    tenant = relationship("Tenant", back_populates="campaigns")
    leads = relationship("Lead", back_populates="campaign")

    @property
    def window_days(self) -> List[str]:
        return json.loads(self.window_days_json)

    @property
    def window_dict(self) -> dict:
        return {
            "start": self.window_start,
            "end": self.window_end,
            "days": self.window_days,
        }


class Lead(Base):
    __tablename__ = "leads"

    campaign_id = Column(String, ForeignKey("campaigns.campaign_id"), nullable=False)
    lead_id = Column(String, nullable=False)
    phone = Column(String, nullable=False, index=True)
    customer_name = Column(String, nullable=True)

    # State: fresh | in_flight | retry_pending | callback_pending | completed | exhausted | dnd_blocked
    state = Column(String, nullable=False, default="fresh", index=True)
    attempts = Column(Integer, nullable=False, default=0)
    next_eligible_at = Column(AwareDateTime, nullable=False, index=True)

    last_status = Column(String, nullable=True)
    last_disposition = Column(String, nullable=True)
    last_ended_at = Column(AwareDateTime, nullable=True)

    active_call_sid = Column(String, nullable=True)
    active_request_id = Column(String, nullable=True)
    updated_at = Column(AwareDateTime, nullable=False)

    __table_args__ = (PrimaryKeyConstraint("campaign_id", "lead_id"),)

    campaign = relationship("Campaign", back_populates="leads")


class Call(Base):
    __tablename__ = "calls"

    request_id = Column(String, primary_key=True)
    call_sid = Column(String, nullable=True, index=True)
    campaign_id = Column(String, nullable=False, index=True)
    lead_id = Column(String, nullable=False, index=True)
    tenant_id = Column(String, nullable=False, index=True)
    phone = Column(String, nullable=False, index=True)
    attempt_no = Column(Integer, nullable=False)

    # State: initiating | active | ended | failed_to_place
    state = Column(String, nullable=False, default="initiating", index=True)
    created_at = Column(AwareDateTime, nullable=False)
    started_at = Column(AwareDateTime, nullable=True)
    ended_at = Column(AwareDateTime, nullable=True)

    status = Column(String, nullable=True)
    disposition = Column(String, nullable=True)
    callback_at = Column(AwareDateTime, nullable=True)
    duration_sec = Column(Integer, nullable=False, default=0)

