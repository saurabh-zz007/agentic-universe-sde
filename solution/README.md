# Solution: Feature-First Architecture

This package implements the **Durable Campaign Dispatcher** organized under a modular **Feature-First Architecture**.

## Target Layout

```text
solution/
├── app/
│   ├── main.py                  # Unified FastAPI app & background worker lifespan
│   ├── core/                    # Shared infrastructure & cross-cutting utilities
│   │   ├── config.py            # Environment configuration & fixture loaders
│   │   ├── database.py          # PostgreSQL connection & session management
│   │   ├── clock.py             # Provider simulated clock & FakeClock
│   │   └── http_client.py       # Telephony HTTP client with connection pooling & 504 resolution
│   │
│   ├── features/
│   │   ├── dispatch/            # Job scheduling, execution & time windows
│   │   │   ├── router.py        # FastAPI APIRouter endpoints (/dispatch/status, /dispatch/step)
│   │   │   ├── controller.py    # HTTP orchestration, exception handling & DTO mapping
│   │   │   ├── service.py       # Core logic from dispatcher & windows
│   │   │   ├── models.py        # ORM models: Tenant, Campaign, Lead, Call
│   │   │   └── schemas.py       # Pydantic DTOs
│   │   │
│   │   ├── reconciliation/      # State verification & recovery
│   │   │   ├── router.py        # FastAPI APIRouter endpoints (/reconciliation/reconcile, /in-flight)
│   │   │   ├── controller.py    # HTTP orchestration & DTO mapping
│   │   │   ├── service.py       # Core logic from reconciler
│   │   │   ├── models.py        # Reconciliation state/audit ORM models
│   │   │   └── schemas.py       # Pydantic DTOs
│   │   │
│   │   ├── webhooks/            # Inbound external callbacks & outcome state machine
│   │   │   ├── router.py        # Routes migrated from webhook receiver (/webhooks/telephony)
│   │   │   ├── controller.py    # Signature validation & delegation
│   │   │   ├── service.py       # Outcome state transitions
│   │   │   ├── models.py        # Webhook/outcome ORM models (ProcessedWebhook, DndRecord)
│   │   │   └── schemas.py       # Pydantic DTOs
│   │   │
│   │   └── reporting/           # Data aggregation & exports
│   │       ├── router.py        # FastAPI APIRouter endpoints (/reporting/export, /reporting/validate)
│   │       ├── controller.py    # HTTP orchestration & DTO mapping
│   │       ├── service.py       # Core logic from export
│   │       └── schemas.py       # Pydantic DTOs
│   │
├── tests/                       # Reorganized to mirror app/features/
│   ├── conftest.py              # Update fixtures & imports for the new app structure
│   ├── dispatch/
│   │   ├── test_scheduler.py
│   │   ├── test_windows.py
│   │   └── test_api.py
│   ├── reconciliation/
│   │   ├── test_resilience.py
│   │   └── test_api.py
│   ├── webhooks/
│   │   └── test_state_machine.py
│   └── reporting/
│       └── test_export.py
│
├── implementation.md
└── README.md
```

## Running the Application

### 1. Run Unit & Feature Tests
```bash
pytest solution/tests
```

### 2. Run the Dispatcher Workflow
```bash
python -m solution.app.main
# or:
python -m solution
```

### 3. Run as Unified FastAPI Web Service
```bash
uvicorn solution.app.main:app --host 127.0.0.1 --port 8200
```
