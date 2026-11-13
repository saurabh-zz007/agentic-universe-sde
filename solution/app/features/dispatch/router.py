"""
FastAPI router for dispatch endpoints.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Request

from solution.app.features.dispatch.controller import DispatchController
from solution.app.features.dispatch.schemas import (
    DispatchStatusResponse,
    DispatchStepResponse,
)

router = APIRouter(prefix="/dispatch", tags=["Dispatch"])


def get_controller(request: Request) -> DispatchController:
    dispatcher = getattr(request.app.state, "dispatcher", None)
    return DispatchController(dispatcher=dispatcher)


@router.get("/status", response_model=DispatchStatusResponse)
async def get_dispatch_status(
    request: Request,
    controller: DispatchController = Depends(get_controller),
) -> DispatchStatusResponse:
    """Returns current dispatch progress and termination status."""
    clock = getattr(request.app.state, "clock", None)
    return controller.get_status(clock=clock)


@router.post("/step", response_model=DispatchStepResponse)
async def trigger_dispatch_step(
    controller: DispatchController = Depends(get_controller),
) -> DispatchStepResponse:
    """Manually triggers one scheduling and call placement tick."""
    return await controller.execute_step()

