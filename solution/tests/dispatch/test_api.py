"""
Tests for dispatch API endpoints and controller DTO mapping.
"""
from contextlib import contextmanager
from unittest.mock import AsyncMock, MagicMock
from fastapi.testclient import TestClient

from solution.app.features.dispatch.models import Lead
from solution.app.features.dispatch.schemas import (
    DispatchStatusResponse,
    DispatchStepResponse,
)
from solution.app.main import create_app


def test_dispatch_api_status(test_db_session, sample_fixtures, monkeypatch):
    @contextmanager
    def mock_session():
        yield test_db_session

    monkeypatch.setattr("solution.app.core.database.get_session", mock_session)
    monkeypatch.setattr("solution.app.features.dispatch.controller.get_session", mock_session)

    app = create_app(sample_fixtures)
    client = TestClient(app)

    resp = client.get("/dispatch/status")
    assert resp.status_code == 200
    data = resp.json()
    assert "is_finished" in data
    assert "active_calls" in data
    assert "incomplete_leads" in data


def test_dispatch_api_step(sample_fixtures):
    app = create_app(sample_fixtures)
    mock_dispatcher = MagicMock()
    mock_dispatcher.step = AsyncMock(return_value=3)
    mock_dispatcher.is_finished = MagicMock(return_value=False)
    mock_clock = MagicMock()
    mock_clock.now = MagicMock(return_value=MagicMock(isoformat=lambda: "2026-11-12T17:30:00+05:30"))
    mock_dispatcher.clock = mock_clock

    app.state.dispatcher = mock_dispatcher
    client = TestClient(app)

    resp = client.post("/dispatch/step")
    assert resp.status_code == 200
    data = resp.json()
    assert data["calls_dispatched"] == 3
    assert data["is_finished"] is False
