"""
Unit tests for reporting service, CSV export, and reporting router/controller.
"""
import csv
import os
import tempfile
from contextlib import contextmanager
from datetime import datetime

from fastapi.testclient import TestClient

from solution.app.core.clock import IST
from solution.app.features.dispatch.models import Campaign, Lead, Tenant
from solution.app.features.reporting.controller import ReportingController
from solution.app.features.reporting.service import export_final_state_csv
from solution.app.main import create_app


def test_export_final_state_csv(test_db_session, monkeypatch):
    session = test_db_session
    t = datetime(2026, 11, 12, 17, 30, tzinfo=IST)

    @contextmanager
    def mock_session():
        yield session

    monkeypatch.setattr("solution.app.core.database.get_session", mock_session)
    monkeypatch.setattr("solution.app.features.reporting.service.get_session", mock_session)
    monkeypatch.setattr("solution.app.features.reporting.controller.get_session", mock_session)

    lead = Lead(
        campaign_id="camp_rep",
        lead_id="l_rep_1",
        phone="+919999999991",
        state="completed",
        attempts=2,
        last_status="completed",
        last_disposition="interested",
        next_eligible_at=t,
        updated_at=t,
    )
    session.add(lead)
    session.commit()

    with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as tmp:
        tmp_path = tmp.name

    try:
        exported = export_final_state_csv(tmp_path)
        assert exported == tmp_path
        assert os.path.exists(tmp_path)

        with open(tmp_path, "r", encoding="utf-8") as f:
            reader = list(csv.DictReader(f))
            assert len(reader) == 1
            assert reader[0]["campaign_id"] == "camp_rep"
            assert reader[0]["lead_id"] == "l_rep_1"
            assert reader[0]["final_state"] == "completed"
            assert reader[0]["attempts"] == "2"
            assert reader[0]["last_status"] == "completed"
            assert reader[0]["last_disposition"] == "interested"
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)


def test_reporting_router(test_db_session, sample_fixtures, monkeypatch):
    @contextmanager
    def mock_session():
        yield test_db_session

    monkeypatch.setattr("solution.app.core.database.get_session", mock_session)
    monkeypatch.setattr("solution.app.features.reporting.service.get_session", mock_session)
    monkeypatch.setattr("solution.app.features.reporting.controller.get_session", mock_session)

    app = create_app(sample_fixtures)
    client = TestClient(app)

    with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as tmp:
        tmp_path = tmp.name

    try:
        resp = client.post(f"/reporting/export?output_path={tmp_path}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["output_path"] == tmp_path
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
