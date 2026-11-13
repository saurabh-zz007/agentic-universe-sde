"""
Simulated clock integration and time utilities.
"""
from __future__ import annotations

import asyncio
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx

IST = timezone(timedelta(hours=5, minutes=30))


class ClockClient:
    """Synchronizes with and calculates simulated time from the telephony provider."""

    def __init__(
        self,
        base_url: str,
        sim_epoch: Optional[datetime] = None,
        real_epoch: Optional[float] = None,
        speed: float = 600.0,
    ):
        self.base_url = base_url.rstrip("/")
        self.sim_epoch = sim_epoch or datetime(2026, 11, 12, 17, 30, tzinfo=IST)
        self.real_epoch = real_epoch or time.time()
        self.speed = speed
        self._synced = False

    async def sync(self, client: Optional[httpx.AsyncClient] = None) -> None:
        """Fetch current clock state from telephony provider."""
        url = f"{self.base_url}/v1/clock"
        if client:
            resp = await client.get(url, timeout=5.0)
            data = resp.json()
        else:
            async with httpx.AsyncClient() as c:
                resp = await c.get(url, timeout=5.0)
                data = resp.json()

        self.sim_epoch = datetime.fromisoformat(data["sim_epoch"]).astimezone(IST)
        self.real_epoch = float(data["real_epoch"])
        self.speed = float(data["speed"])
        self._synced = True

    def now(self) -> datetime:
        """Calculates current simulated time."""
        elapsed_real = time.time() - self.real_epoch
        sim_elapsed_seconds = elapsed_real * self.speed
        return self.sim_epoch + timedelta(seconds=sim_elapsed_seconds)

    async def sleep_sim(self, sim_seconds: float) -> None:
        """Sleeps for the equivalent real-time duration of `sim_seconds`."""
        real_seconds = max(0.0, sim_seconds / self.speed)
        await asyncio.sleep(real_seconds)


class FakeClock:
    """Mock clock for deterministic unit testing without waiting for real time."""

    def __init__(self, current_sim_time: datetime, speed: float = 600.0):
        self._now = current_sim_time.astimezone(IST)
        self.speed = speed

    def now(self) -> datetime:
        return self._now

    def set_now(self, new_time: datetime) -> None:
        self._now = new_time.astimezone(IST)

    def advance(self, td: timedelta) -> None:
        self._now += td

    async def sleep_sim(self, sim_seconds: float) -> None:
        self._now += timedelta(seconds=sim_seconds)

