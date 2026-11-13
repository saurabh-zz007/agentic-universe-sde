"""
Active call reconciliation worker for recovering dropped webhooks and resolving in-flight states.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Optional

from sqlalchemy import select

from solution.app.core.clock import ClockClient, IST
from solution.app.core.config import FixturesData, settings
from solution.app.core.database import get_session
from solution.app.core.http_client import TelephonyClient
from solution.app.features.dispatch.models import Call, Lead
from solution.app.features.webhooks.service import process_call_completion

logger = logging.getLogger("solution.reconciliation.service")


class Reconciler:
    def __init__(
        self,
        telephony_client: TelephonyClient,
        clock: ClockClient,
        fixtures: FixturesData,
    ):
        self.client = telephony_client
        self.clock = clock
        self.fixtures = fixtures
        self._running = False

    async def reconcile_once(self) -> int:
        """
        Polls active and initiating calls from provider to recover dropped webhooks.
        Returns number of ended calls reconciled.
        """
        reconciled_count = 0

        # Step 1: Read active calls in a quick session
        with get_session() as session:
            in_flight_calls = session.execute(
                select(Call.request_id, Call.call_sid, Call.state).where(
                    Call.state.in_(["initiating", "active"])
                )
            ).all()

        if not in_flight_calls:
            return 0

        # Step 2: Fetch state from provider asynchronously (no DB lock held!)
        for req_id, call_sid, current_db_state in in_flight_calls:
            call_data = None
            if call_sid:
                call_data = await self.client.get_call_by_sid(call_sid)
            elif req_id:
                call_data = await self.client.get_call_by_request_id(req_id)

            if not call_data:
                continue

            state = call_data.get("state")
            sid = call_data.get("call_sid")

            # Step 3: Process updates in short transactions
            if state == "ended":
                result = call_data.get("result")
                if result:
                    logger.info(
                        f"Reconciled ended call {call_sid or req_id} via polling"
                    )
                    with get_session() as session:
                        process_call_completion(
                            session=session,
                            payload=result,
                            retry_policy=self.fixtures.retry_policy,
                            regulatory_window=self.fixtures.regulatory_window,
                        )
                        session.commit()
                    reconciled_count += 1

            elif state == "active":
                with get_session() as session:
                    call = session.get(Call, req_id)
                    if call and call.state != "ended":
                        if sid and not call.call_sid:
                            call.call_sid = sid
                        if call.state != "active":
                            call.state = "active"
                    session.commit()

        return reconciled_count

    async def run_loop(self, poll_interval: Optional[float] = None) -> None:
        """Background loop executing reconciliation periodically."""
        interval = poll_interval or settings.reconciler_poll_interval
        self._running = True
        logger.info(f"Reconciler loop started (interval={interval}s).")
        while self._running:
            try:
                await self.reconcile_once()
            except Exception as e:
                logger.error(f"Error in reconciler loop: {e}", exc_info=True)
            await asyncio.sleep(interval)

    def stop(self) -> None:
        self._running = False

