"""
FastAPI router for incoming webhook callbacks.
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse

from solution.app.core.config import FixturesData, load_fixtures
from solution.app.features.webhooks.controller import WebhookController
from solution.app.features.webhooks.schemas import WebhookResponse

logger = logging.getLogger("solution.webhooks.router")

router = APIRouter(tags=["Webhooks"])


def get_webhook_controller(request: Request) -> WebhookController:
    fixtures: Optional[FixturesData] = getattr(request.app.state, "fixtures", None)
    if not fixtures:
        fixtures = load_fixtures()
    return WebhookController(fixtures=fixtures)


@router.post("/webhooks/telephony", response_model=WebhookResponse)
async def handle_telephony_webhook(
    request: Request,
    x_au_signature: Optional[str] = Header(None, alias="X-AU-Signature"),
    controller: WebhookController = Depends(get_webhook_controller),
) -> WebhookResponse:
    """Receives and processes telephony call outcome callbacks with HMAC authentication."""
    raw_body = await request.body()
    return await controller.handle_telephony_webhook(raw_body, x_au_signature)


@router.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "healthy"}


def create_webhook_app(fixtures: Optional[FixturesData] = None) -> FastAPI:
    """Factory creating a standalone webhook receiver FastAPI application."""
    cfg = fixtures or load_fixtures()
    app = FastAPI(title="AU Dispatcher - Webhook Receiver", version="1.0")
    app.state.fixtures = cfg
    app.include_router(router)
    return app

