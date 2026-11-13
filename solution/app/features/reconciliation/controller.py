"""
Reconciliation controller: HTTP orchestration, exception handling, and DTO mapping.
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import HTTPException
from sqlalchemy import select

from solution.app.core.database import get_session
from solution.app.features.dispatch.models import Call
from solution.app.features.reconciliation.schemas import (
    InFlightCallDTO,
    InFlightCallsResponse,
    ReconciliationRunResponse,
)
from solution.app.features.reconciliation.service import Reconciler

logger = logging.getLogger("solution.reconciliation.controller")


class ReconciliationController:
    """Orchestrates reconciliation actions and maps in-flight call state to DTOs."""

    def __init__(self, reconciler: Optional[Reconciler] = None):
        self.reconciler = reconciler

    async def trigger_reconcile(
        self, reconciler: Optional[Reconciler] = None
    ) -> ReconciliationRunResponse:
        """Executes a single active call reconciliation sweep."""
        target_reconciler = reconciler or self.reconciler
        if not target_reconciler:
            raise HTTPException(
                status_code=503,
                detail="Reconciler service not initialized or available",
            )
        try:
            count = await target_reconciler.reconcile_once()
            return ReconciliationRunResponse(reconciled_count=count, success=True)
        except Exception as e:
            logger.error(f"Reconciliation sweep failed: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail=f"Reconciliation error: {str(e)}")

    def get_in_flight_calls(self) -> InFlightCallsResponse:
        """Queries database for all currently initiating or active calls."""
        try:
            with get_session() as session:
                rows = session.execute(
                    select(Call.request_id, Call.call_sid, Call.state).where(
                        Call.state.in_(["initiating", "active"])
                    )
                ).all()

                calls = [
                    InFlightCallDTO(
                        request_id=r[0],
                        call_sid=r[1],
                        state=r[2],
                    )
                    for r in rows
                ]
                return InFlightCallsResponse(total=len(calls), calls=calls)
        except Exception as e:
            logger.error(f"Failed to fetch in-flight calls: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail="Error retrieving in-flight calls")

