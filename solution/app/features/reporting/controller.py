"""
Reporting controller: HTTP orchestration, exception handling, and DTO mapping.
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import HTTPException
from sqlalchemy import func, select

from solution.app.core.database import get_session
from solution.app.core.http_client import TelephonyClient
from solution.app.features.dispatch.models import Lead
from solution.app.features.reporting.schemas import (
    ExportSummaryResponse,
    ValidationSummaryResponse,
)
from solution.app.features.reporting.service import (
    export_final_state_csv,
    validate_against_provider,
)

logger = logging.getLogger("solution.reporting.controller")


class ReportingController:
    """Orchestrates CSV export and provider compliance validation."""

    def export(self, output_path: Optional[str] = None) -> ExportSummaryResponse:
        """Exports the latest state of all leads to final_state.csv."""
        try:
            exported_path = export_final_state_csv(output_path)
            with get_session() as session:
                count = session.execute(select(func.count(Lead.lead_id))).scalar() or 0
            return ExportSummaryResponse(output_path=exported_path, total_leads=count)
        except Exception as e:
            logger.error(f"Error exporting final state CSV: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail=f"Export failed: {str(e)}")

    async def validate(
        self,
        client: TelephonyClient,
        csv_path: Optional[str] = None,
    ) -> ValidationSummaryResponse:
        """Validates generated final_state.csv against carrier admin expectations."""
        try:
            success, summary = await validate_against_provider(client, csv_path)
            return ValidationSummaryResponse(
                success=success,
                violation_count=summary["violation_count"],
                mismatches_count=summary["mismatches_count"],
                violations_by_type=summary.get("violations_by_type", {}),
                total_leads_checked=summary.get("total_leads_checked", 0),
                mismatches=summary.get("mismatches", []),
                callback_lateness=summary.get("callback_lateness", {}),
                max_concurrency_seen=summary.get("max_concurrency_seen", {}),
                calls_total=summary.get("calls_total", 0),
                webhooks=summary.get("webhooks", {}),
            )
        except Exception as e:
            logger.error(f"Error during provider validation: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail=f"Validation error: {str(e)}")

