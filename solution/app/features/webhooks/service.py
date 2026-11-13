"""
Outcome state transitions, signature verification, and call completion handling.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from solution.app.core.clock import IST
from solution.app.core.config import RetryPolicy, settings
from solution.app.features.dispatch.models import Call, Campaign, Lead
from solution.app.features.dispatch.service import next_window_open
from solution.app.features.webhooks.models import DndRecord, ProcessedWebhook

logger = logging.getLogger("solution.webhooks.service")

TERMINAL_DISPOSITIONS = {"interested", "not_interested", "wrong_number", "dnd"}


def verify_signature(secret: str, raw_body: bytes, signature_header: Optional[str]) -> bool:
    """Verifies the HMAC-SHA256 signature on an incoming webhook."""
    if not signature_header:
        return False
    expected = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(signature_header, expected)


def parse_dt(val: Any) -> Optional[datetime]:
    if not val:
        return None
    if isinstance(val, datetime):
        return val.astimezone(IST) if val.tzinfo else val.replace(tzinfo=IST)
    dt = datetime.fromisoformat(val)
    return dt.astimezone(IST) if dt.tzinfo else dt.replace(tzinfo=IST)


def process_call_completion(
    session: Session,
    payload: Dict[str, Any],
    retry_policy: RetryPolicy,
    regulatory_window: dict,
) -> bool:
    """
    Atomically processes a call outcome from a webhook or reconciler poll.
    Returns True if processed, False if duplicate / already handled.
    """
    call_sid = payload.get("call_sid")
    request_id = payload.get("request_id")
    campaign_id = payload.get("campaign_id")
    lead_id = payload.get("lead_id")
    phone = payload.get("phone")
    status = payload.get("status")
    disposition = payload.get("disposition")
    started_at = parse_dt(payload.get("started_at"))
    ended_at = parse_dt(payload.get("ended_at")) or datetime.now(IST)
    callback_at = parse_dt(payload.get("callback_at"))
    duration_sec = int(payload.get("duration_sec", 0))

    if not call_sid or not request_id:
        logger.error(f"Missing call_sid or request_id in outcome payload: {payload}")
        return False

    # Check deduplication
    existing_webhook = session.get(ProcessedWebhook, call_sid)
    call: Optional[Call] = session.get(Call, request_id)
    if not call and call_sid:
        call = session.execute(
            select(Call).where(Call.call_sid == call_sid)
        ).scalar_one_or_none()

    if existing_webhook and call and call.state == "ended":
        logger.debug(f"Webhook already processed for call_sid {call_sid}")
        return False

    # Mark as processed in processed_webhooks
    if not existing_webhook:
        session.add(
            ProcessedWebhook(
                call_sid=call_sid,
                processed_at=datetime.now(IST),
            )
        )

    # Update or insert call record
    if not call:
        call = Call(
            request_id=request_id,
            call_sid=call_sid,
            campaign_id=campaign_id,
            lead_id=lead_id,
            tenant_id=payload.get("tenant_id", ""),
            phone=phone,
            attempt_no=1,
            state="ended",
            created_at=started_at or ended_at,
            started_at=started_at,
            ended_at=ended_at,
            status=status,
            disposition=disposition,
            callback_at=callback_at,
            duration_sec=duration_sec,
        )
        session.add(call)
    else:
        call.call_sid = call_sid
        call.state = "ended"
        call.status = status
        call.disposition = disposition
        if started_at:
            call.started_at = started_at
        call.ended_at = ended_at
        call.callback_at = callback_at
        call.duration_sec = duration_sec

    # Update Lead
    lead: Optional[Lead] = session.get(Lead, (campaign_id, lead_id))
    if not lead:
        logger.warning(f"Lead not found for outcome: {campaign_id}/{lead_id}")
        return True

    camp: Optional[Campaign] = session.get(Campaign, campaign_id)
    max_attempts = camp.max_attempts if camp else 3
    camp_window = camp.window_dict if camp else {"start": "09:00", "end": "21:00", "days": None}

    # Ensure attempts is updated for accepted call
    if lead.attempts < call.attempt_no:
        lead.attempts = call.attempt_no

    lead.last_status = status
    lead.last_disposition = disposition
    lead.last_ended_at = ended_at
    lead.active_call_sid = None
    lead.active_request_id = None
    lead.updated_at = ended_at

    # Rule R7: Terminal dispositions end the lead
    if disposition in TERMINAL_DISPOSITIONS:
        lead.state = "completed"

        # Rule R8: DND is global
        if disposition == "dnd":
            # Record in DND registry
            existing_dnd = session.get(DndRecord, phone)
            if not existing_dnd:
                session.add(
                    DndRecord(
                        phone=phone,
                        registered_at=ended_at,
                        source_campaign_id=campaign_id,
                        source_lead_id=lead_id,
                    )
                )

            # Block other non-terminal leads with this phone (R8, R9)
            other_leads = session.execute(
                select(Lead).where(
                    Lead.phone == phone,
                    or_(
                        Lead.campaign_id != campaign_id,
                        Lead.lead_id != lead_id,
                    ),
                    Lead.state.notin_(["completed", "exhausted"]),
                )
            ).scalars().all()
            for other in other_leads:
                other.state = "dnd_blocked"
                other.updated_at = ended_at

    # Rule R5: Retries after no_answer, busy, or failed
    elif status in ("no_answer", "busy", "failed"):
        if lead.attempts >= max_attempts:
            lead.state = "exhausted"
        else:
            delay_mins = (
                retry_policy.failed_minutes
                if status == "failed"
                else (
                    retry_policy.busy_minutes
                    if status == "busy"
                    else retry_policy.no_answer_minutes
                )
            )
            earliest_retry = ended_at + timedelta(minutes=delay_mins)
            lead.next_eligible_at = next_window_open(
                earliest_retry, camp_window, regulatory_window
            )
            lead.state = "retry_pending"

    # Rule R6: Callbacks
    elif disposition == "callback_requested":
        if lead.attempts >= max_attempts:
            lead.state = "exhausted"
        else:
            due_time = callback_at or (ended_at + timedelta(minutes=30))
            lead.next_eligible_at = next_window_open(
                due_time, camp_window, regulatory_window
            )
            lead.state = "callback_pending"

    session.flush()
    return True

