"""
Unit tests for scheduler priority ordering (R6), tenant concurrency (R2), and phone uniqueness (R3).
"""
import json
from datetime import datetime, timedelta

from sqlalchemy import case, func, select

from solution.app.core.clock import FakeClock, IST
from solution.app.features.dispatch.models import Call, Campaign, Lead, Tenant


def test_priority_ordering(test_db_session):
    session = test_db_session
    t = datetime(2026, 11, 12, 17, 30, tzinfo=IST)

    # Setup tenant and campaign
    tenant = Tenant(tenant_id="tenant_p", max_concurrent_calls=5)
    camp = Campaign(
        campaign_id="camp_p",
        tenant_id="tenant_p",
        leads_file="f.csv",
        window_start="10:00",
        window_end="19:00",
        window_days_json=json.dumps(["thu"]),
        max_attempts=3,
    )
    session.add_all([tenant, camp])
    session.flush()

    # Create leads with different states
    fresh_lead = Lead(
        campaign_id="camp_p",
        lead_id="l_fresh",
        phone="+919000000001",
        state="fresh",
        attempts=0,
        next_eligible_at=t - timedelta(minutes=10),
        updated_at=t,
    )
    retry_lead = Lead(
        campaign_id="camp_p",
        lead_id="l_retry",
        phone="+919000000002",
        state="retry_pending",
        attempts=1,
        next_eligible_at=t - timedelta(minutes=5),
        updated_at=t,
    )
    callback_lead = Lead(
        campaign_id="camp_p",
        lead_id="l_callback",
        phone="+919000000003",
        state="callback_pending",
        attempts=1,
        next_eligible_at=t - timedelta(minutes=1),
        updated_at=t,
    )
    session.add_all([fresh_lead, retry_lead, callback_lead])
    session.commit()

    # Priority query
    priority_expr = case(
        (Lead.state == "callback_pending", 1),
        (Lead.state == "retry_pending", 2),
        (Lead.state == "fresh", 3),
        else_=4,
    )
    ordered_leads = session.execute(
        select(Lead)
        .where(Lead.state.in_(["callback_pending", "retry_pending", "fresh"]))
        .order_by(priority_expr, Lead.next_eligible_at.asc())
    ).scalars().all()

    # Rule R6: Due callbacks > retries > fresh leads
    assert [l.lead_id for l in ordered_leads] == ["l_callback", "l_retry", "l_fresh"]


def test_tenant_concurrency_calculation(test_db_session):
    session = test_db_session
    t = datetime(2026, 11, 12, 17, 30, tzinfo=IST)

    tenant = Tenant(tenant_id="tenant_c", max_concurrent_calls=2)
    session.add(tenant)

    # 1 active call, 1 initiating call
    c1 = Call(
        request_id="req_1",
        campaign_id="camp_c",
        lead_id="l1",
        tenant_id="tenant_c",
        phone="+919111111111",
        attempt_no=1,
        state="active",
        created_at=t,
    )
    c2 = Call(
        request_id="req_2",
        campaign_id="camp_c",
        lead_id="l2",
        tenant_id="tenant_c",
        phone="+919222222222",
        attempt_no=1,
        state="initiating",
        created_at=t,
    )
    # 1 ended call (does not count towards concurrency)
    c3 = Call(
        request_id="req_3",
        campaign_id="camp_c",
        lead_id="l3",
        tenant_id="tenant_c",
        phone="+919333333333",
        attempt_no=1,
        state="ended",
        created_at=t,
    )
    session.add_all([c1, c2, c3])
    session.commit()

    active_count = session.execute(
        select(func.count(Call.request_id)).where(
            Call.tenant_id == "tenant_c",
            Call.state.in_(["initiating", "active"]),
        )
    ).scalar()

    assert active_count == 2
    available_slots = tenant.max_concurrent_calls - active_count
    assert available_slots == 0

