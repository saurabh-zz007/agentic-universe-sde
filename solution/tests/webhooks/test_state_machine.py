"""
Unit tests for the state machine, retry delays (R5), DND propagation (R8), and precedence (R9).
"""
import json
from datetime import datetime, timedelta

from solution.app.core.clock import IST
from solution.app.core.config import RetryPolicy
from solution.app.features.dispatch.models import Campaign, Lead, Tenant
from solution.app.features.webhooks.models import DndRecord
from solution.app.features.webhooks.service import process_call_completion


def setup_sample_campaign(session):
    t = datetime(2026, 11, 12, 17, 30, tzinfo=IST)
    tenant = Tenant(tenant_id="tenant_x", max_concurrent_calls=5)
    camp1 = Campaign(
        campaign_id="camp_1",
        tenant_id="tenant_x",
        leads_file="f1.csv",
        window_start="10:00",
        window_end="19:00",
        window_days_json=json.dumps(["mon", "tue", "wed", "thu", "fri"]),
        max_attempts=3,
    )
    camp2 = Campaign(
        campaign_id="camp_2",
        tenant_id="tenant_x",
        leads_file="f2.csv",
        window_start="10:00",
        window_end="19:00",
        window_days_json=json.dumps(["mon", "tue", "wed", "thu", "fri"]),
        max_attempts=3,
    )
    session.add_all([tenant, camp1, camp2])
    session.flush()
    return t


def test_retry_delay_calculation(test_db_session):
    session = test_db_session
    t = setup_sample_campaign(session)

    lead = Lead(
        campaign_id="camp_1",
        lead_id="l_busy",
        phone="+919876543210",
        state="in_flight",
        attempts=1,
        next_eligible_at=t,
        updated_at=t,
    )
    session.add(lead)
    session.commit()

    rp = RetryPolicy(no_answer_minutes=60, busy_minutes=60, failed_minutes=15)
    reg_window = {"start": "09:00", "end": "21:00"}

    # Process busy outcome
    payload = {
        "call_sid": "CA111",
        "request_id": "req_1",
        "campaign_id": "camp_1",
        "lead_id": "l_busy",
        "phone": "+919876543210",
        "status": "busy",
        "disposition": None,
        "started_at": t.isoformat(),
        "ended_at": t.isoformat(),
        "duration_sec": 10,
    }
    process_call_completion(session, payload, rp, reg_window)
    session.commit()

    lead_after = session.get(Lead, ("camp_1", "l_busy"))
    assert lead_after.state == "retry_pending"
    # Delay for busy is 60 simulated minutes
    expected_next = t + timedelta(minutes=60)
    assert lead_after.next_eligible_at == expected_next


def test_exhausted_after_max_attempts(test_db_session):
    session = test_db_session
    t = setup_sample_campaign(session)

    lead = Lead(
        campaign_id="camp_1",
        lead_id="l_att3",
        phone="+919876543210",
        state="in_flight",
        attempts=3,  # Already used 3 attempts
        next_eligible_at=t,
        updated_at=t,
    )
    session.add(lead)
    session.commit()

    rp = RetryPolicy(no_answer_minutes=60, busy_minutes=60, failed_minutes=15)
    reg_window = {"start": "09:00", "end": "21:00"}

    payload = {
        "call_sid": "CA222",
        "request_id": "req_2",
        "campaign_id": "camp_1",
        "lead_id": "l_att3",
        "phone": "+919876543210",
        "status": "no_answer",
        "disposition": None,
        "started_at": t.isoformat(),
        "ended_at": t.isoformat(),
        "duration_sec": 30,
    }
    process_call_completion(session, payload, rp, reg_window)
    session.commit()

    lead_after = session.get(Lead, ("camp_1", "l_att3"))
    assert lead_after.state == "exhausted"


def test_global_dnd_and_precedence(test_db_session):
    session = test_db_session
    t = setup_sample_campaign(session)
    shared_phone = "+919999999999"

    # Lead 1 in Camp 1: will receive DND
    lead1 = Lead(
        campaign_id="camp_1",
        lead_id="l1",
        phone=shared_phone,
        state="in_flight",
        attempts=1,
        next_eligible_at=t,
        updated_at=t,
    )
    # Lead 2 in Camp 2: fresh, shares same phone
    lead2 = Lead(
        campaign_id="camp_2",
        lead_id="l2",
        phone=shared_phone,
        state="fresh",
        attempts=0,
        next_eligible_at=t,
        updated_at=t,
    )
    # Lead 3 in Camp 2: already completed (should stay completed due to precedence R9)
    lead3 = Lead(
        campaign_id="camp_2",
        lead_id="l3",
        phone=shared_phone,
        state="completed",
        attempts=1,
        last_status="completed",
        last_disposition="interested",
        next_eligible_at=t,
        updated_at=t,
    )
    # Lead 4 in Camp 2: already exhausted (should stay exhausted due to precedence R9)
    lead4 = Lead(
        campaign_id="camp_2",
        lead_id="l4",
        phone=shared_phone,
        state="exhausted",
        attempts=3,
        last_status="busy",
        next_eligible_at=t,
        updated_at=t,
    )
    session.add_all([lead1, lead2, lead3, lead4])
    session.commit()

    rp = RetryPolicy(no_answer_minutes=60, busy_minutes=60, failed_minutes=15)
    reg_window = {"start": "09:00", "end": "21:00"}

    # Process DND disposition on Lead 1
    payload = {
        "call_sid": "CA_DND",
        "request_id": "req_dnd",
        "campaign_id": "camp_1",
        "lead_id": "l1",
        "phone": shared_phone,
        "status": "completed",
        "disposition": "dnd",
        "started_at": t.isoformat(),
        "ended_at": t.isoformat(),
        "duration_sec": 45,
    }
    process_call_completion(session, payload, rp, reg_window)
    session.commit()

    # Rule R7 & R9: Lead 1 is completed
    assert session.get(Lead, ("camp_1", "l1")).state == "completed"
    # Rule R8: Phone is registered in global DND
    assert session.get(DndRecord, shared_phone) is not None
    # Rule R8: Lead 2 becomes dnd_blocked
    assert session.get(Lead, ("camp_2", "l2")).state == "dnd_blocked"
    # Rule R9 Precedence: completed > exhausted > dnd_blocked
    assert session.get(Lead, ("camp_2", "l3")).state == "completed"
    assert session.get(Lead, ("camp_2", "l4")).state == "exhausted"

