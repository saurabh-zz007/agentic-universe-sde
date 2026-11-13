"""
Unit tests for resilience: HMAC verification, webhook deduplication, 504 resolution, and lost webhook recovery.
"""
import asyncio
import hashlib
import hmac
import json
from datetime import datetime
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from solution.app.core.clock import FakeClock, IST
from solution.app.core.config import RetryPolicy
from solution.app.core.database import get_engine
from solution.app.core.http_client import (
    CallPlacementResult,
    CallPlacementStatus,
    TelephonyClient,
)
from solution.app.features.dispatch.models import Call, Campaign, Lead, Tenant
from solution.app.features.reconciliation.service import Reconciler
from solution.app.features.webhooks.router import create_webhook_app
from solution.app.features.webhooks.service import (
    process_call_completion,
    verify_signature,
)


def test_hmac_signature_verification():
    secret = "test_whsec_12345"
    body = b'{"event":"call.completed","call_sid":"CA999"}'
    valid_sig = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()

    assert verify_signature(secret, body, valid_sig) is True
    assert verify_signature(secret, body, "tampered_signature") is False
    assert verify_signature(secret, body, None) is False


def test_webhook_endpoint_hmac_and_processing(test_db_session, sample_fixtures):
    app = create_webhook_app(sample_fixtures)
    client = TestClient(app)

    body_dict = {
        "event": "call.completed",
        "call_sid": "CA_ENDPOINT",
        "request_id": "req_endpoint",
        "campaign_id": "camp_a1",
        "lead_id": "l_endpoint",
        "phone": "+919000000000",
        "status": "completed",
        "disposition": "interested",
        "started_at": "2026-11-12T17:30:00+05:30",
        "ended_at": "2026-11-12T17:32:00+05:30",
        "duration_sec": 120,
    }
    raw_bytes = json.dumps(body_dict).encode("utf-8")

    # 1. Without signature: 401
    resp = client.post("/webhooks/telephony", content=raw_bytes)
    assert resp.status_code == 401

    # 2. With invalid signature: 401
    resp = client.post(
        "/webhooks/telephony",
        content=raw_bytes,
        headers={"X-AU-Signature": "invalid_hex"},
    )
    assert resp.status_code == 401

    # 3. With valid signature: 200
    valid_sig = hmac.new(
        sample_fixtures.webhook_secret.encode("utf-8"), raw_bytes, hashlib.sha256
    ).hexdigest()
    with patch(
        "solution.app.features.webhooks.controller.process_call_completion",
        return_value=True,
    ):
        resp = client.post(
            "/webhooks/telephony",
            content=raw_bytes,
            headers={"X-AU-Signature": valid_sig},
        )
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_webhook_deduplication(test_db_session, sample_fixtures):
    session = test_db_session
    t = datetime(2026, 11, 12, 17, 30, tzinfo=IST)

    tenant = Tenant(tenant_id="tenant_a", max_concurrent_calls=2)
    camp = Campaign(
        campaign_id="camp_a1",
        tenant_id="tenant_a",
        leads_file="f.csv",
        window_start="10:00",
        window_end="19:00",
        window_days_json=json.dumps(["thu"]),
        max_attempts=3,
    )
    lead = Lead(
        campaign_id="camp_a1",
        lead_id="l_dedup",
        phone="+919000000000",
        state="in_flight",
        attempts=1,
        next_eligible_at=t,
        updated_at=t,
    )
    call = Call(
        request_id="req_dedup",
        call_sid="CA_DEDUP",
        campaign_id="camp_a1",
        lead_id="l_dedup",
        tenant_id="tenant_a",
        phone="+919000000000",
        attempt_no=1,
        state="active",
        created_at=t,
    )
    session.add_all([tenant, camp, lead, call])
    session.commit()

    payload = {
        "call_sid": "CA_DEDUP",
        "request_id": "req_dedup",
        "campaign_id": "camp_a1",
        "lead_id": "l_dedup",
        "phone": "+919000000000",
        "status": "completed",
        "disposition": "interested",
        "started_at": t.isoformat(),
        "ended_at": t.isoformat(),
        "duration_sec": 120,
    }

    # First delivery: processed
    first_processed = process_call_completion(
        session, payload, sample_fixtures.retry_policy, sample_fixtures.regulatory_window
    )
    session.commit()
    assert first_processed is True

    # Duplicate delivery: ignored gracefully
    duplicate_processed = process_call_completion(
        session, payload, sample_fixtures.retry_policy, sample_fixtures.regulatory_window
    )
    session.commit()
    assert duplicate_processed is False

    lead_after = session.get(Lead, ("camp_a1", "l_dedup"))
    assert lead_after.state == "completed"


def test_ambiguous_504_resolution_when_placed():
    async def _test():
        client = TelephonyClient("http://127.0.0.1:8099")
        mock_call_data = {
            "call_sid": "CA_RESOLVED",
            "request_id": "req_504",
            "state": "active",
        }
        client.get_call_by_request_id = AsyncMock(return_value=mock_call_data)

        res = await client.resolve_ambiguous_call("req_504")
        assert res.status == CallPlacementStatus.ACCEPTED
        assert res.call_sid == "CA_RESOLVED"

    asyncio.run(_test())


def test_ambiguous_504_resolution_when_not_placed():
    async def _test():
        client = TelephonyClient("http://127.0.0.1:8099")
        client.get_call_by_request_id = AsyncMock(return_value=None)

        res = await client.resolve_ambiguous_call("req_504_none")
        assert res.status == CallPlacementStatus.NOT_PLACED
        assert res.status_code == 404

    asyncio.run(_test())

