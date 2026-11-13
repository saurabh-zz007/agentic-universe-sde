"""
Unified FastAPI application and service runner for the Durable Campaign Dispatcher.
Features modular routers, background worker lifespan management, and CLI runner.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import signal
import sys
from contextlib import asynccontextmanager
from typing import Optional

import uvicorn
from fastapi import FastAPI

from solution.app.core.clock import ClockClient
from solution.app.core.config import FixturesData, load_fixtures, settings
from solution.app.core.database import init_db
from solution.app.core.http_client import TelephonyClient
from solution.app.features.dispatch.router import router as dispatch_router
from solution.app.features.dispatch.service import Dispatcher
from solution.app.features.reconciliation.router import (
    router as reconciliation_router,
)
from solution.app.features.reconciliation.service import Reconciler
from solution.app.features.reporting.router import router as reporting_router
from solution.app.features.reporting.service import (
    export_final_state_csv,
    validate_against_provider,
)
from solution.app.features.webhooks.router import router as webhooks_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("solution.app.main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    FastAPI lifespan manager for initialization, clock synchronization,
    database setup, and optional background workers.
    """
    fixtures: FixturesData = getattr(app.state, "fixtures", None) or load_fixtures()
    app.state.fixtures = fixtures

    client: TelephonyClient = getattr(app.state, "client", None) or TelephonyClient(
        settings.telephony_base_url
    )
    app.state.client = client

    clock: ClockClient = getattr(app.state, "clock", None) or ClockClient(
        settings.telephony_base_url
    )
    app.state.clock = clock

    # Attempt clock sync if telephony provider is reachable
    try:
        await clock.sync()
        logger.info(f"Clock synced: sim_now={clock.now().isoformat()} speed={clock.speed}x")
    except Exception as e:
        logger.warning(f"Simulated clock not reachable on startup: {e}. Using local time.")

    # Initialize database
    try:
        init_db(fixtures, clock.now())
    except Exception as e:
        logger.warning(f"Database initialization deferred or already configured: {e}")

    # Initialize workers
    reconciler = Reconciler(client, clock, fixtures)
    dispatcher = Dispatcher(client, clock, fixtures)
    app.state.reconciler = reconciler
    app.state.dispatcher = dispatcher

    reconciler_task = None
    dispatcher_task = None

    if getattr(app.state, "enable_background_workers", False):
        logger.info("Starting background reconciler and dispatcher tasks...")
        await reconciler.reconcile_once()
        reconciler_task = asyncio.create_task(reconciler.run_loop())
        dispatcher_task = asyncio.create_task(dispatcher.run_loop())

    yield

    # Clean shutdown
    if dispatcher:
        dispatcher.stop()
    if reconciler:
        reconciler.stop()
    if reconciler_task:
        reconciler_task.cancel()
    if dispatcher_task:
        dispatcher_task.cancel()
    await client.aclose()
    logger.info("Application lifespan shutdown complete.")


def create_app(
    fixtures: Optional[FixturesData] = None,
    enable_background_workers: bool = False,
) -> FastAPI:
    """Factory creating the unified FastAPI application with all modular feature routers."""
    app = FastAPI(
        title="AU Durable Campaign Dispatcher",
        version="2.0",
        lifespan=lifespan,
    )
    app.state.fixtures = fixtures
    app.state.enable_background_workers = enable_background_workers

    # Register feature routers
    app.include_router(webhooks_router)
    app.include_router(dispatch_router)
    app.include_router(reconciliation_router)
    app.include_router(reporting_router)

    return app


app = create_app()


async def run_services(
    fixtures_path: Optional[str] = None,
    output_path: Optional[str] = None,
):
    """
    Unified workflow runner: initializes clock, runs FastAPI webhook receiver,
    starts the active call reconciler and priority dispatcher, runs until all
    leads reach a terminal state, and outputs final_state.csv.
    """
    fixtures = load_fixtures(fixtures_path)
    client = TelephonyClient(settings.telephony_base_url)

    # 1. Sync simulated clock from telephony provider
    clock = ClockClient(settings.telephony_base_url)
    logger.info("Synchronizing simulated clock from telephony provider...")
    for attempt in range(10):
        try:
            await clock.sync()
            logger.info(
                f"Clock synced: sim_now={clock.now().isoformat()} speed={clock.speed}x"
            )
            break
        except Exception as e:
            if attempt == 9:
                logger.error(
                    f"Failed to connect to provider clock at {settings.telephony_base_url}: {e}"
                )
                raise
            logger.warning("Provider clock not ready yet, retrying in 1s...")
            await asyncio.sleep(1.0)

    # 2. Initialize database & seed fixtures idempotently
    logger.info("Initializing database...")
    init_db(fixtures, clock.now())

    # 3. Startup Recovery: Reconcile in-flight calls from previous process crash
    reconciler = Reconciler(client, clock, fixtures)
    logger.info("Running startup reconciliation for in-flight calls...")
    recovered = await reconciler.reconcile_once()
    if recovered:
        logger.info(f"Startup recovery: resolved {recovered} previously interrupted calls.")

    # 4. Start Unified FastAPI App (embedded uvicorn server)
    api_app = create_app(fixtures=fixtures, enable_background_workers=False)
    api_app.state.client = client
    api_app.state.clock = clock
    api_app.state.reconciler = reconciler

    uvicorn_config = uvicorn.Config(
        api_app,
        host=settings.webhook_host,
        port=settings.webhook_port,
        log_level="warning",
    )
    server = uvicorn.Server(uvicorn_config)
    server_task = asyncio.create_task(server.serve())

    # Allow server to bind port
    await asyncio.sleep(0.5)
    logger.info(f"Unified FastAPI server listening on {settings.webhook_url}")

    # 5. Start Reconciler background worker
    reconciler_task = asyncio.create_task(reconciler.run_loop())

    # 6. Start Dispatcher
    dispatcher = Dispatcher(client, clock, fixtures)
    api_app.state.dispatcher = dispatcher
    logger.info("Starting dispatcher engine...")

    try:
        # Run dispatcher until all leads reach a final state
        await dispatcher.run_loop()

        # Final reconciliation sweep
        await reconciler.reconcile_once()

        # 7. Export final_state.csv
        csv_file = export_final_state_csv(output_path)
        logger.info(f"Generated {csv_file}")

        # 8. Validate against mock provider
        try:
            success, summary = await validate_against_provider(client, csv_file)
            logger.info("=" * 60)
            logger.info(f"RUN RESULT: {'SUCCESS (0 VIOLATIONS)' if success else 'FAILED'}")
            logger.info(f"Total violations: {summary['violation_count']}")
            if summary["violations_by_type"]:
                logger.info(f"Violations by type: {summary['violations_by_type']}")
            logger.info(f"Mismatches with provider: {summary['mismatches_count']}")
            logger.info(f"Max concurrency seen: {summary['max_concurrency_seen']}")
            logger.info(f"Callback lateness: {summary['callback_lateness']}")
            logger.info("=" * 60)
        except Exception as e:
            logger.warning(f"Could not validate against provider admin endpoints: {e}")

    finally:
        reconciler.stop()
        dispatcher.stop()
        server.should_exit = True
        try:
            await asyncio.wait_for(server_task, timeout=2.0)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            pass
        await client.aclose()


def main():
    parser = argparse.ArgumentParser(description="Agentic Universe Dispatcher Runner")
    parser.add_argument("--fixtures", default=settings.fixtures_path)
    parser.add_argument("--output", default=settings.output_csv_path)
    args = parser.parse_args()

    try:
        asyncio.run(run_services(args.fixtures, args.output))
    except KeyboardInterrupt:
        logger.info("Dispatcher stopped by user.")
        sys.exit(0)


if __name__ == "__main__":
    main()

