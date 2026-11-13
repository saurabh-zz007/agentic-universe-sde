"""
FastAPI router for reporting and validation endpoints.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query, Request

from solution.app.core.http_client import TelephonyClient
from solution.app.features.reporting.controller import ReportingController
from solution.app.features.reporting.schemas import (
    ExportSummaryResponse,
    ValidationSummaryResponse,
)

router = APIRouter(prefix="/reporting", tags=["Reporting"])


def get_reporting_controller() -> ReportingController:
    return ReportingController()


@router.post("/export", response_model=ExportSummaryResponse)
async def export_final_state(
    output_path: Optional[str] = Query(None),
    controller: ReportingController = Depends(get_reporting_controller),
) -> ExportSummaryResponse:
    """Exports current lead states to CSV."""
    return controller.export(output_path=output_path)


@router.post("/validate", response_model=ValidationSummaryResponse)
async def validate_results(
    request: Request,
    csv_path: Optional[str] = Query(None),
    controller: ReportingController = Depends(get_reporting_controller),
) -> ValidationSummaryResponse:
    """Validates generated CSV results against mock telephony provider."""
    client = getattr(request.app.state, "client", None)
    if not client:
        client = TelephonyClient(base_url="http://127.0.0.1:8099")
    return await controller.validate(client=client, csv_path=csv_path)

