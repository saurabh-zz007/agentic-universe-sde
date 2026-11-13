"""
Tests for reconciliation API endpoints and controller DTO mapping.
"""
from contextlib import contextmanager
from unittest.mock import AsyncMock, MagicMock
from fastapi.testclient import TestClient

from solution.app.main import create_app


def test_reconciliation_api_in_flight(test_db_session, sample_fixtures, monkeypatch):
    @contextmanager
    def mock_session():
        yield test_db_session

    monkeypatch.setattr("solution.app.core.database.get_session", mock_session)
    monkeypatch.setattr("solution.app.features.reconciliation.controller.get_session", mock_session)

    app = create_app(sample_fixtures)
    client = TestClient(app)

    resp = client.get("/reconciliation/in-flight")
    assert resp.status_code == 200
    data = resp.json()
    assert "total" in data
    assert "calls" in data
    assert data["total"] == 0


def test_reconciliation_api_reconcile(sample_fixtures):
    app = create_app(sample_fixtures)
    mock_reconciler = MagicMock()
    mock_reconciler.reconcile_once = AsyncMock(return_value=2)
    app.state.reconciler = mock_reconciler

    client = TestClient(app)
    resp = client.post("/reconciliation/reconcile")
    assert resp.status_code == 200
    data = resp.json()
    assert data["reconciled_count"] == 2
    assert data["success"] is True
