"""
Exports final_state.csv and validates output against mock provider admin endpoints.
"""
from __future__ import annotations

import csv
import logging
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import select

from solution.app.core.config import settings
from solution.app.core.database import get_session
from solution.app.core.http_client import TelephonyClient
from solution.app.features.dispatch.models import Lead

logger = logging.getLogger("solution.reporting.service")


def export_final_state_csv(output_path: Optional[str] = None) -> str:
    path = output_path or settings.output_csv_path

    with get_session() as session:
        leads = session.execute(
            select(Lead).order_by(Lead.campaign_id.asc(), Lead.lead_id.asc())
        ).scalars().all()

        fieldnames = [
            "campaign_id",
            "lead_id",
            "final_state",
            "attempts",
            "last_status",
            "last_disposition",
        ]

        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for lead in leads:
                writer.writerow(
                    {
                        "campaign_id": lead.campaign_id,
                        "lead_id": lead.lead_id,
                        "final_state": lead.state,
                        "attempts": lead.attempts,
                        "last_status": lead.last_status or "",
                        "last_disposition": lead.last_disposition or "",
                    }
                )

    logger.info(f"Exported final state to {path} ({len(leads)} leads)")
    return path


async def validate_against_provider(
    client: TelephonyClient, csv_path: Optional[str] = None
) -> Tuple[bool, Dict[str, Any]]:
    """
    Validates generated final_state.csv against GET /admin/leads and GET /admin/report.
    Returns (success, report_summary).
    """
    path = csv_path or settings.output_csv_path

    # Read exported CSV
    our_leads = {}
    with open(path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            our_leads[(row["campaign_id"], row["lead_id"])] = row

    # Fetch provider expectation
    provider_leads = await client.get_admin_leads()
    report = await client.get_admin_report()

    mismatches = []
    for exp in provider_leads:
        cid = exp["campaign_id"]
        lid = exp["lead_id"]
        key = (cid, lid)
        actual = our_leads.get(key)
        if not actual:
            mismatches.append(f"Missing lead in CSV: {cid}/{lid}")
            continue

        if actual["final_state"] != exp["expected_state"]:
            mismatches.append(
                f"State mismatch {cid}/{lid}: expected {exp['expected_state']}, got {actual['final_state']}"
            )
        if int(actual["attempts"]) != int(exp["attempts"]):
            mismatches.append(
                f"Attempts mismatch {cid}/{lid}: expected {exp['attempts']}, got {actual['attempts']}"
            )
        if actual["last_status"] != (exp.get("last_status") or ""):
            mismatches.append(
                f"Status mismatch {cid}/{lid}: expected '{exp.get('last_status')}', got '{actual['last_status']}'"
            )
        if actual["last_disposition"] != (exp.get("last_disposition") or ""):
            mismatches.append(
                f"Disposition mismatch {cid}/{lid}: expected '{exp.get('last_disposition')}', got '{actual['last_disposition']}'"
            )

    violation_count = report.get("violation_count", 0)
    success = (len(mismatches) == 0) and (violation_count == 0)

    summary = {
        "success": success,
        "violation_count": violation_count,
        "violations_by_type": report.get("violations_by_type", {}),
        "total_leads_checked": len(provider_leads),
        "mismatches_count": len(mismatches),
        "mismatches": mismatches[:10],
        "callback_lateness": report.get("callback_lateness_minutes", {}),
        "max_concurrency_seen": report.get("max_concurrency_seen", {}),
        "calls_total": report.get("calls_total", 0),
        "webhooks": report.get("webhooks", {}),
    }

    return success, summary

