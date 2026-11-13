"""
Pydantic schemas and DTOs for the dispatch feature.
"""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict


class TenantDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    tenant_id: str
    max_concurrent_calls: int


class CampaignDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    campaign_id: str
    tenant_id: str
    leads_file: str
    window_start: str
    window_end: str
    window_days: List[str]
    max_attempts: int


class LeadDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    campaign_id: str
    lead_id: str
    phone: str
    customer_name: Optional[str] = None
    state: str
    attempts: int
    next_eligible_at: datetime
    last_status: Optional[str] = None
    last_disposition: Optional[str] = None
    active_call_sid: Optional[str] = None
    active_request_id: Optional[str] = None
    updated_at: datetime


class CallDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    request_id: str
    call_sid: Optional[str] = None
    campaign_id: str
    lead_id: str
    tenant_id: str
    phone: str
    attempt_no: int
    state: str
    created_at: datetime
    started_at: Optional[datetime] = None
    ended_at: Optional[datetime] = None
    status: Optional[str] = None
    disposition: Optional[str] = None
    callback_at: Optional[datetime] = None
    duration_sec: int = 0


class DispatchStepResponse(BaseModel):
    calls_dispatched: int
    sim_now: str
    is_finished: bool


class DispatchStatusResponse(BaseModel):
    is_finished: bool
    active_calls: int
    incomplete_leads: int
    sim_now: Optional[str] = None

