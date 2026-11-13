"""
Dispatch service: calling windows, priority scheduling, and call execution engine.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Set, Tuple

from sqlalchemy import and_, case, func, select
from sqlalchemy.orm import Session

from solution.app.core.clock import ClockClient, IST
from solution.app.core.config import FixturesData, settings
from solution.app.core.database import get_session
from solution.app.core.http_client import (
    CallPlacementResult,
    CallPlacementStatus,
    TelephonyClient,
)
from solution.app.features.dispatch.models import Call, Campaign, Lead, Tenant
from solution.app.features.webhooks.models import DndRecord

logger = logging.getLogger("solution.dispatch.service")

DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def parse_hm(s: str) -> Tuple[int, int]:
    h, m = s.split(":")
    return int(h), int(m)


def in_window(
    t: datetime,
    start: str,
    end: str,
    days: Optional[List[str]] = None,
    grace_s: float = 0.0,
) -> bool:
    """
    Returns True if t is within [start, end) on an allowed day,
    tolerating `grace_s` seconds.
    """
    for probe in (t, t - timedelta(seconds=grace_s), t + timedelta(seconds=grace_s)):
        lt = probe.astimezone(IST)
        if days is not None and DAYS[lt.weekday()] not in days:
            continue
        sh, sm = parse_hm(start)
        eh, em = parse_hm(end)
        s = lt.replace(hour=sh, minute=sm, second=0, microsecond=0)
        e = lt.replace(hour=eh, minute=em, second=0, microsecond=0)
        if s <= lt < e:
            return True
    return False


def is_window_open(
    t: datetime,
    campaign_window: dict,
    regulatory_window: Optional[dict] = None,
    grace_s: float = 0.0,
    safety_buffer_s: float = 120.0,
) -> bool:
    """
    Checks if time t satisfies both regulatory and campaign windows.
    Ensures that t + safety_buffer_s is also within the window so calls
    do not cross the boundary during dispatch latency.
    """
    reg = regulatory_window or {"start": "09:00", "end": "21:00"}

    # Must be currently in window
    if not in_window(t, reg["start"], reg["end"], days=None, grace_s=grace_s):
        return False
    if not in_window(
        t,
        campaign_window["start"],
        campaign_window["end"],
        days=campaign_window.get("days"),
        grace_s=grace_s,
    ):
        return False

    # Safety buffer before close: do not dial within safety_buffer_s of window end
    if safety_buffer_s > 0:
        probe = t + timedelta(seconds=safety_buffer_s)
        if not in_window(probe, reg["start"], reg["end"], days=None, grace_s=0.0):
            return False
        if not in_window(
            probe,
            campaign_window["start"],
            campaign_window["end"],
            days=campaign_window.get("days"),
            grace_s=0.0,
        ):
            return False

    return True


def next_window_open(
    t: datetime,
    campaign_window: dict,
    regulatory_window: Optional[dict] = None,
) -> datetime:
    """
    Calculates the earliest instant >= t that satisfies both
    the regulatory window (09:00-21:00 IST) and the campaign window.
    """
    reg = regulatory_window or {"start": "09:00", "end": "21:00"}
    camp_days = campaign_window.get("days", DAYS)
    c_sh, c_sm = parse_hm(campaign_window["start"])
    c_eh, c_em = parse_hm(campaign_window["end"])
    r_sh, r_sm = parse_hm(reg["start"])
    r_eh, r_em = parse_hm(reg["end"])

    lt = t.astimezone(IST)

    for d in range(0, 14):  # Check up to 2 weeks ahead
        day = (lt + timedelta(days=d)).replace(second=0, microsecond=0)
        day_name = DAYS[day.weekday()]
        if day_name not in camp_days:
            continue

        c_start = day.replace(hour=c_sh, minute=c_sm)
        c_end = day.replace(hour=c_eh, minute=c_em)
        r_start = day.replace(hour=r_sh, minute=r_sm)
        r_end = day.replace(hour=r_eh, minute=r_em)

        eff_start = max(c_start, r_start)
        eff_end = min(c_end, r_end)

        if eff_start >= eff_end:
            continue

        if d == 0:
            if lt < eff_start:
                return eff_start
            if lt < eff_end - timedelta(seconds=120):
                return lt
            continue

        return eff_start

    return lt


class Dispatcher:
    """
    Decides who to call and when, places calls through the telephony provider,
    and enforces rules R1-R9 with at-most-once dialling guarantees.
    """

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

    async def step(self) -> int:
        """
        Executes one dispatch tick.
        Selects eligible leads obeying concurrency and window rules, then places calls.
        Returns the number of calls placed in this tick.
        """
        sim_now = self.clock.now()
        calls_dispatched = 0

        # Step 1: Identify eligible leads to call in this tick
        to_dial: List[Tuple[Lead, Campaign, Tenant, str, int]] = []

        with get_session() as session:
            # Active phones across all campaigns
            active_phone_rows = session.execute(
                select(Call.phone).where(Call.state.in_(["initiating", "active"]))
            ).scalars().all()
            active_phones: Set[str] = set(active_phone_rows)

            # Global DND phones
            dnd_phone_rows = session.execute(
                select(DndRecord.phone)
            ).scalars().all()
            dnd_phones: Set[str] = set(dnd_phone_rows)

            tenants = session.execute(select(Tenant)).scalars().all()

            for tenant in tenants:
                # Rule R2: Check tenant concurrency
                active_calls_count = session.execute(
                    select(func.count(Call.request_id)).where(
                        Call.tenant_id == tenant.tenant_id,
                        Call.state.in_(["initiating", "active"]),
                    )
                ).scalar() or 0

                available_slots = tenant.max_concurrent_calls - active_calls_count
                if available_slots <= 0:
                    continue

                # Rule R1: Find which campaigns of this tenant have their window open
                tenant_campaigns = session.execute(
                    select(Campaign).where(Campaign.tenant_id == tenant.tenant_id)
                ).scalars().all()

                open_camp_ids = []
                camp_map = {}
                for camp in tenant_campaigns:
                    camp_map[camp.campaign_id] = camp
                    if is_window_open(
                        sim_now,
                        camp.window_dict,
                        self.fixtures.regulatory_window,
                        grace_s=0.0,
                        safety_buffer_s=300.0,
                    ):
                        open_camp_ids.append(camp.campaign_id)

                if not open_camp_ids:
                    continue

                # Rule R6: Priority ordering: Due callbacks > retries > fresh leads
                # Rule R3: One call per phone
                # Rule R8: Not in DND
                # Rule R4: attempts < max_attempts
                priority_expr = case(
                    (Lead.state == "callback_pending", 1),
                    (Lead.state == "retry_pending", 2),
                    (Lead.state == "fresh", 3),
                    else_=4,
                )

                candidate_leads = session.execute(
                    select(Lead)
                    .where(
                        Lead.campaign_id.in_(open_camp_ids),
                        Lead.state.in_(["callback_pending", "retry_pending", "fresh"]),
                        Lead.next_eligible_at <= sim_now,
                        Lead.phone.notin_(active_phones) if active_phones else True,
                        Lead.phone.notin_(dnd_phones) if dnd_phones else True,
                    )
                    .order_by(priority_expr, Lead.next_eligible_at.asc())
                ).scalars().all()

                # Pick up to available_slots leads
                slots_filled = 0
                for lead in candidate_leads:
                    if slots_filled >= available_slots:
                        break
                    if lead.phone in active_phones:
                        continue

                    # Reserve phone and slot
                    active_phones.add(lead.phone)
                    slots_filled += 1

                    camp = camp_map[lead.campaign_id]
                    attempt_no = lead.attempts + 1
                    req_id = f"req_{lead.campaign_id}_{lead.lead_id}_att{attempt_no}"

                    # Mark call as initiating in database BEFORE placing call
                    call = session.get(Call, req_id)
                    if not call:
                        call = Call(
                            request_id=req_id,
                            campaign_id=lead.campaign_id,
                            lead_id=lead.lead_id,
                            tenant_id=tenant.tenant_id,
                            phone=lead.phone,
                            attempt_no=attempt_no,
                            state="initiating",
                            created_at=sim_now,
                        )
                        session.add(call)
                    else:
                        call.state = "initiating"
                        call.created_at = sim_now
                        call.call_sid = None
                        call.started_at = None
                        call.ended_at = None
                        call.status = None
                        call.disposition = None

                    lead.state = "in_flight"
                    lead.active_request_id = req_id
                    lead.updated_at = sim_now

                    to_dial.append((lead, camp, tenant, req_id, attempt_no))

            session.commit()

        # Step 2: Place reserved calls concurrently via Telephony Provider API
        async def _place_one(item: Tuple[Lead, Campaign, Tenant, str, int]) -> bool:
            lead, camp, tenant, req_id, attempt_no = item
            current_sim = self.clock.now()

            # Double check window immediately before network call
            if not is_window_open(
                current_sim,
                camp.window_dict,
                self.fixtures.regulatory_window,
                safety_buffer_s=120.0,
            ):
                logger.info(
                    f"Aborting dial for {lead.campaign_id}/{lead.lead_id}: "
                    f"window closed right before placement (sim_now={current_sim.isoformat()})"
                )
                with get_session() as session:
                    call_db = session.get(Call, req_id)
                    if call_db:
                        call_db.state = "failed_to_place"
                    lead_db = session.get(Lead, (lead.campaign_id, lead.lead_id))
                    if lead_db:
                        lead_db.state = "fresh" if lead_db.attempts == 0 else "retry_pending"
                        lead_db.next_eligible_at = next_window_open(
                            current_sim, camp.window_dict, self.fixtures.regulatory_window
                        )
                        lead_db.active_request_id = None
                        lead_db.updated_at = current_sim
                    session.commit()
                return False

            try:
                res: CallPlacementResult = await self.client.place_call(
                    request_id=req_id,
                    campaign_id=lead.campaign_id,
                    lead_id=lead.lead_id,
                    phone=lead.phone,
                    callback_url=settings.webhook_url,
                )

                with get_session() as session:
                    call_db = session.get(Call, req_id)
                    lead_db = session.get(Lead, (lead.campaign_id, lead.lead_id))

                    if res.status == CallPlacementStatus.ACCEPTED:
                        # Rule R4: Attempt accepted
                        if call_db and call_db.state != "ended":
                            call_db.call_sid = res.call_sid
                            call_db.state = "active"
                            call_db.started_at = current_sim
                        if lead_db:
                            if lead_db.attempts < attempt_no:
                                lead_db.attempts = attempt_no
                            lead_db.active_call_sid = res.call_sid
                            lead_db.updated_at = current_sim
                        session.commit()
                        return True

                    elif res.status in (CallPlacementStatus.RETRYABLE_ERROR, CallPlacementStatus.NOT_PLACED):
                        # Transient 503 or unplaced 504: do not increment attempt count
                        if call_db:
                            call_db.state = "failed_to_place"
                        if lead_db:
                            lead_db.state = "fresh" if lead_db.attempts == 0 else "retry_pending"
                            lead_db.active_request_id = None
                            lead_db.updated_at = current_sim
                        session.commit()
                        return False

            except Exception as e:
                logger.error(f"Unexpected error dispatching call {req_id}: {e}", exc_info=True)
                return False

        if to_dial:
            results = await asyncio.gather(*[_place_one(item) for item in to_dial])
            calls_dispatched = sum(1 for r in results if r)

        return calls_dispatched

    def is_finished(self) -> bool:
        """Checks if all leads have reached a final terminal state."""
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

            return (incomplete == 0) and (active_calls == 0)

    async def run_loop(self, poll_interval: Optional[float] = None) -> None:
        """Continuous dispatch loop until all leads are resolved."""
        interval = poll_interval or settings.dispatcher_poll_interval
        self._running = True
        logger.info(f"Dispatcher loop started (interval={interval}s).")

        while self._running:
            try:
                await self.step()
                if self.is_finished():
                    logger.info("All leads have reached a final state! Dispatcher complete.")
                    break
            except Exception as e:
                logger.error(f"Error in dispatcher loop: {e}", exc_info=True)

            await asyncio.sleep(interval)

    def stop(self) -> None:
        self._running = False

