"""
Webhook controller: signature validation, payload parsing, and delegation to domain logic.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, Optional

from fastapi import HTTPException

from solution.app.core.config import FixturesData
from solution.app.core.database import get_session
from solution.app.features.webhooks.schemas import WebhookResponse
from solution.app.features.webhooks.service import (
    process_call_completion,
    verify_signature,
)

logger = logging.getLogger("solution.webhooks.controller")


class WebhookController:
    """Orchestrates webhook authentication, validation, and outcome processing."""

    def __init__(self, fixtures: FixturesData):
        self.fixtures = fixtures

    async def handle_telephony_webhook(
        self,
        raw_body: bytes,
        signature_header: Optional[str],
    ) -> WebhookResponse:
        """
        Validates HMAC signature, parses JSON payload, and delegates to outcome state machine.
        """
        if not verify_signature(self.fixtures.webhook_secret, raw_body, signature_header):
            logger.warning("Rejected webhook due to invalid signature")
            raise HTTPException(status_code=401, detail="Invalid signature")

        try:
            payload: Dict[str, Any] = json.loads(raw_body)
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid JSON body")

        with get_session() as session:
            processed = process_call_completion(
                session=session,
                payload=payload,
                retry_policy=self.fixtures.retry_policy,
                regulatory_window=self.fixtures.regulatory_window,
            )

        return WebhookResponse(status="ok", processed=processed)

