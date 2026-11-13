# AI Usage Disclosure

## Tools used
- Google Antigravity / Gemini 3.8

## What I used them for
- Scaffolding the initial SQLAlchemy models and FastAPI webhook server endpoints.
- Generating boilerplate for Pytest test cases across calling window boundaries, regulatory windows, and state machine transitions.
- Automating background runs of the mock telephony server, running timer-based simulated clock checks, and analyzing mock provider logs.

## What I wrote or decided myself
- **Lead State Machine & At-Most-Once Dialling:** Engineered the durable state machine where call attempts with deterministic `request_id` keys (`req_{campaign}_{lead}_att{attempt}`) are committed to the interaction ledger *before* issuing network requests, guaranteeing crash survival without duplicate dials.
- **Clock Skew & Window Close Safety Buffers:** Identified that at 600x–1200x simulated clock speeds, network latency (200–400ms) equates to several simulated minutes. Designed the pre-dial safety buffer (120s–300s) and immediate pre-placement window re-validation to eliminate `outside_calling_window` violations.
- **Concurrent Batch Dispatching:** Converted sequential single-call dispatch into concurrent `asyncio.gather` execution to eliminate serial pipeline latency across tenant concurrency slots.
- **Transaction & Network Decoupling:** Decoupled database transaction lifecycles from async HTTP requests in the active call reconciler, preventing database lock contention when webhooks arrive simultaneously.
- **Global DND & Precedence Hierarchy:** Designed the multi-campaign global DND sweep ensuring the exact business rule precedence:
  $$\text{completed} > \text{exhausted} > \text{dnd\_blocked}$$

## Where the AI was wrong or unhelpful
- **Database Lock Contention:** The initial AI draft held the SQLAlchemy session context manager open across `await client.get_call_by_sid()` in `reconciler.py`. Under SQLite, this held an exclusive file lock while awaiting network responses, causing incoming webhooks on `/webhooks/telephony` to fail with `sqlite3.OperationalError: database is locked`. I diagnosed the lock contention and restructured the reconciler to fetch in-flight IDs in a quick read transaction, perform async HTTP queries without holding locks, and commit outcomes in short, isolated transactions.
- **Sequential Dial Clock Drift:** The initial dialer loop iterated sequentially over candidate leads. At 1200x speed, placing each call took ~0.3s real time (6 simulated minutes), meaning the 3rd and 4th calls crossed the campaign window end time before being placed. I redesigned the loop to use `asyncio.gather` with a pre-dial window check to guarantee all batch calls start within the valid window.
- **Unique Constraint on Failed Placement:** When an attempt failed transiently (e.g. 503 or window abort), re-attempting the lead generated the same `request_id` and triggered an `IntegrityError` upon `session.add(Call)`. I updated the persistence layer to fetch and reuse existing `failed_to_place` call records instead of failing on duplicate primary keys.

## How I verified AI-generated code
- **Comprehensive Unit Test Suite:** Wrote and executed 15 unit tests (`pytest solution/tests`) verifying window calculations, multi-day gap jumps, scheduler priority ordering (`callback_pending > retry_pending > fresh`), retry delays, global DND propagation, and HMAC signature authentication.
- **End-to-End Clean Integration Run:** Executed the service against `mock_telephony --speed 600 --failure-scale 0`, verifying 0 violations on `/admin/report` and 100% lead parity with `/admin/leads`.
- **End-to-End Chaos Run with Mid-Run `kill -9`:** Executed against `mock_telephony --speed 600 --failure-scale 1.0` (with 503s, ambiguous 504s, lost webhooks, and duplicate webhooks), terminated the dispatcher process mid-run (`kill -9`), restarted it, and verified that all 200 leads completed with **0 violations** and **0 mismatches** against the provider.
