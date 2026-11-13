"""
Pydantic schemas and DTOs for the reconciliation feature.
"""
from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, ConfigDict


class InFlightCallDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    request_id: str
    call_sid: Optional[str] = None
    state: str


class ReconciliationRunResponse(BaseModel):
    reconciled_count: int
    success: bool = True


class InFlightCallsResponse(BaseModel):
    total: int
    calls: List[InFlightCallDTO]

