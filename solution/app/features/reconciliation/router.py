"""
FastAPI router for reconciliation endpoints.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from solution.app.features.reconciliation.controller import ReconciliationController
from solution.app.features.reconciliation.schemas import (
    InFlightCallsResponse,
    ReconciliationRunResponse,
)

router = APIRouter(prefix="/reconciliation", tags=["Reconciliation"])


def get_controller(request: Request) -> ReconciliationController:
    reconciler = getattr(request.app.state, "reconciler", None)
    return ReconciliationController(reconciler=reconciler)


@router.post("/reconcile", response_model=ReconciliationRunResponse)
async def trigger_reconciliation(
    request: Request,
    controller: ReconciliationController = Depends(get_controller),
) -> ReconciliationRunResponse:
    """Triggers an immediate reconciliation poll of all in-flight carrier calls."""
    reconciler = getattr(request.app.state, "reconciler", None)
    return await controller.trigger_reconcile(reconciler=reconciler)


@router.get("/in-flight", response_model=InFlightCallsResponse)
async def get_in_flight_calls(
    controller: ReconciliationController = Depends(get_controller),
) -> InFlightCallsResponse:
    """Returns all currently in-flight calls from the database."""
    return controller.get_in_flight_calls()

