"""
Pydantic schemas and DTOs for the reporting feature.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class LeadExportRow(BaseModel):
    campaign_id: str
    lead_id: str
    final_state: str
    attempts: int
    last_status: str = ""
    last_disposition: str = ""


class ExportSummaryResponse(BaseModel):
    output_path: str
    total_leads: int


class ValidationSummaryResponse(BaseModel):
    success: bool
    violation_count: int
    mismatches_count: int
    violations_by_type: Dict[str, Any] = Field(default_factory=dict)
    total_leads_checked: int = 0
    mismatches: List[str] = Field(default_factory=list)
    callback_lateness: Dict[str, Any] = Field(default_factory=dict)
    max_concurrency_seen: Dict[str, Any] = Field(default_factory=dict)
    calls_total: int = 0
    webhooks: Dict[str, Any] = Field(default_factory=dict)

