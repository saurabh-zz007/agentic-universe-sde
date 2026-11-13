"""
HTTP client for the mock telephony provider with connection pooling, idempotency, and ambiguous 504 resolution.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger("solution.client")


class CallPlacementStatus:
    ACCEPTED = "accepted"
    RETRYABLE_ERROR = "retryable_error"
    NOT_PLACED = "not_placed"
    UNKNOWN = "unknown"


@dataclass
class CallPlacementResult:
    status: str  # accepted | retryable_error | not_placed
    status_code: int
    call_sid: Optional[str] = None
    call_data: Optional[Dict[str, Any]] = None
    error_detail: Optional[str] = None


class TelephonyClient:
    """Client for placing calls and querying carrier state with persistent connection pool."""

    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")
        self._http_client: Optional[httpx.AsyncClient] = None

    def get_http_client(self) -> httpx.AsyncClient:
        if self._http_client is None or self._http_client.is_closed:
            self._http_client = httpx.AsyncClient(timeout=10.0)
        return self._http_client

    async def aclose(self):
        if self._http_client and not self._http_client.is_closed:
            await self._http_client.aclose()

    async def place_call(
        self,
        request_id: str,
        campaign_id: str,
        lead_id: str,
        phone: str,
        callback_url: str,
        client: Optional[httpx.AsyncClient] = None,
    ) -> CallPlacementResult:
        """
        Places a call through the telephony provider.
        Idempotent via request_id. Handles 503 and ambiguous 504 automatically.
        """
        url = f"{self.base_url}/v1/calls"
        payload = {
            "request_id": request_id,
            "campaign_id": campaign_id,
            "lead_id": lead_id,
            "phone": phone,
            "callback_url": callback_url,
        }
        c = client or self.get_http_client()

        try:
            resp = await c.post(url, json=payload, timeout=10.0)

            # 201 Created or 200 OK (idempotent replay)
            if resp.status_code in (200, 201):
                data = resp.json()
                return CallPlacementResult(
                    status=CallPlacementStatus.ACCEPTED,
                    status_code=resp.status_code,
                    call_sid=data.get("call_sid"),
                    call_data=data,
                )

            # 503 Service Unavailable: transient, call not placed
            if resp.status_code == 503:
                return CallPlacementResult(
                    status=CallPlacementStatus.RETRYABLE_ERROR,
                    status_code=503,
                    error_detail="503 Service Unavailable",
                )

            # 504 Gateway Timeout: outcome unknown, must resolve
            if resp.status_code == 504:
                logger.warning(
                    f"504 Gateway Timeout for request_id {request_id}. "
                    "Resolving status via GET /v1/calls..."
                )
                return await self.resolve_ambiguous_call(request_id, c)

            # Any other 4xx or 5xx
            return CallPlacementResult(
                status=CallPlacementStatus.NOT_PLACED,
                status_code=resp.status_code,
                error_detail=resp.text,
            )

        except (httpx.TimeoutException, httpx.NetworkError) as e:
            logger.warning(
                f"Network/Timeout exception placing call for {request_id}: {e}. "
                "Resolving status via GET /v1/calls..."
            )
            return await self.resolve_ambiguous_call(request_id, c)

    async def resolve_ambiguous_call(
        self,
        request_id: str,
        client: Optional[httpx.AsyncClient] = None,
        retries: int = 3,
    ) -> CallPlacementResult:
        """
        Queries GET /v1/calls?request_id=... to determine if an ambiguous call was accepted.
        """
        c = client or self.get_http_client()
        for attempt in range(retries):
            call_info = await self.get_call_by_request_id(request_id, c)
            if call_info is not None:
                # Call was accepted and exists on the carrier
                return CallPlacementResult(
                    status=CallPlacementStatus.ACCEPTED,
                    status_code=200,
                    call_sid=call_info.get("call_sid"),
                    call_data=call_info,
                )
            await asyncio.sleep(0.5)

        # Provider returned 404: the call was never placed
        return CallPlacementResult(
            status=CallPlacementStatus.NOT_PLACED,
            status_code=404,
            error_detail="Call not found on provider after ambiguous 504",
        )

    async def get_call_by_request_id(
        self,
        request_id: str,
        client: Optional[httpx.AsyncClient] = None,
    ) -> Optional[Dict[str, Any]]:
        """Queries provider for a call by request_id."""
        url = f"{self.base_url}/v1/calls"
        params = {"request_id": request_id}
        c = client or self.get_http_client()
        try:
            resp = await c.get(url, params=params, timeout=5.0)
            if resp.status_code == 200:
                return resp.json()
            return None
        except Exception as e:
            logger.error(f"Error querying call by request_id {request_id}: {e}")
            return None

    async def get_call_by_sid(
        self,
        call_sid: str,
        client: Optional[httpx.AsyncClient] = None,
    ) -> Optional[Dict[str, Any]]:
        """Queries provider for a call by call_sid."""
        url = f"{self.base_url}/v1/calls/{call_sid}"
        c = client or self.get_http_client()
        try:
            resp = await c.get(url, timeout=5.0)
            if resp.status_code == 200:
                return resp.json()
            return None
        except Exception as e:
            logger.error(f"Error querying call by sid {call_sid}: {e}")
            return None

    async def get_admin_report(
        self,
        client: Optional[httpx.AsyncClient] = None,
    ) -> Dict[str, Any]:
        """Fetches /admin/report from mock provider."""
        url = f"{self.base_url}/admin/report"
        c = client or self.get_http_client()
        resp = await c.get(url, timeout=5.0)
        return resp.json()

    async def get_admin_leads(
        self,
        client: Optional[httpx.AsyncClient] = None,
    ) -> List[Dict[str, Any]]:
        """Fetches /admin/leads from mock provider."""
        url = f"{self.base_url}/admin/leads"
        c = client or self.get_http_client()
        resp = await c.get(url, timeout=5.0)
        return resp.json()

