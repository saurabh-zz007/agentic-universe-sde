"""
Pydantic schemas and DTOs for telephony webhooks.
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class TelephonyWebhookPayload(BaseModel):
    event: Optional[str] = "call.completed"
    call_sid: str
    request_id: str
    campaign_id: str
    lead_id: str
    tenant_id: Optional[str] = None
    phone: str
    status: Optional[str] = None
    disposition: Optional[str] = None
    started_at: Optional[str] = None
    ended_at: Optional[str] = None
    callback_at: Optional[str] = None
    duration_sec: int = Field(default=0)


class WebhookResponse(BaseModel):
    status: str = "ok"
    processed: bool

