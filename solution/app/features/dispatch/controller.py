"""
Dispatch controller: HTTP orchestration, exception handling, and DTO mapping.
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import HTTPException
from sqlalchemy import func, select

from solution.app.core.clock import ClockClient, IST
from solution.app.core.config import settings
from solution.app.core.database import get_session
from solution.app.features.dispatch.models import Call, Lead
from solution.app.features.dispatch.schemas import (
    DispatchStatusResponse,
    DispatchStepResponse,
)
from solution.app.features.dispatch.service import Dispatcher

logger = logging.getLogger("solution.dispatch.controller")


class DispatchController:
    """Orchestrates HTTP dispatch operations, handles exceptions, and maps to DTOs."""

    def __init__(self, dispatcher: Optional[Dispatcher] = None):
        self.dispatcher = dispatcher

    def get_status(self, clock: Optional[ClockClient] = None) -> DispatchStatusResponse:
        """Queries database for current execution status across all leads and calls."""
        try:
            with get_session() as session:
                incomplete = session.execute(
                    select(func.count(Lead.lead_id)).where(
                        Lead.state.notin_(["completed", "exhausted", "dnd_blocked"])
                    )
                ).scalar() or 0

                active_calls = session.execute(
                    select(func.count(Call.request_id)).where(
                        Call.state.in_(["initiating", "active"])
                    )
                ).scalar() or 0

                is_finished = (incomplete == 0) and (active_calls == 0)
                sim_now = clock.now().isoformat() if clock else None

                return DispatchStatusResponse(
                    is_finished=is_finished,
                    active_calls=active_calls,
                    incomplete_leads=incomplete,
                    sim_now=sim_now,
                )
        except Exception as e:
            logger.error(f"Failed to retrieve dispatch status: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail="Error fetching dispatch status")

    async def execute_step(self, dispatcher: Optional[Dispatcher] = None) -> DispatchStepResponse:
        """Executes a single dispatch step via the Dispatcher service."""
        target_dispatcher = dispatcher or self.dispatcher
        if not target_dispatcher:
            raise HTTPException(
                status_code=503, detail="Dispatcher service not initialized or running"
            )

        try:
            dispatched = await target_dispatcher.step()
            finished = target_dispatcher.is_finished()
            sim_now = target_dispatcher.clock.now().isoformat()

            return DispatchStepResponse(
                calls_dispatched=dispatched,
                sim_now=sim_now,
                is_finished=finished,
            )
        except Exception as e:
            logger.error(f"Error during manual dispatch step execution: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail=f"Dispatch step failed: {str(e)}")

