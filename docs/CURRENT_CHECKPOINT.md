# MootOS Current Checkpoint

**Last updated:** August 8, 2026  
**Repository:** `mootmoot1/MootOS`  
**Default branch:** `main`  
**Current release:** Version 0.1 foundation  
**Production schema:** `4 — tasks`

## Verified production foundation

MootOS is deployed privately on Railway and accessible from the phone-friendly web interface.

Previously production-verified foundation includes:

- private password/session login
- persistent Railway SQLite volume
- `/health` and `/ready`
- OpenAI-backed chat
- persistent conversations/messages/projects
- memory save, search, review, correction, archive, restore
- cross-chat memory recall and persistence across Railway rebuilds
- hardened private HTTP boundary
- atomic provider-backed chat persistence
- curated bootstrap-profile feature and supporting composition entrypoint

## Latest verified user-facing memory milestone

PR #29 added intelligent explicit memory correction. After merge and Railway deployment, production testing confirmed:

1. an old test memory was saved
2. a correction using `Actually, ... Remember that instead.` was accepted
3. a brand-new conversation recalled only the replacement value
4. the old superseded value did not appear as a conflicting active memory

This confirms the new correction path works through the real phone UI and persistent production database.

## Latest merged Task milestones

### PR #27 — Model Run logging v0.1

- migration 3 adds `runs`
- normal model-provider attempts gain structured execution metadata
- failures record sanitized class metadata rather than prompt/response content
- Runs establish an audit/execution spine separate from Tasks

### PR #28 — Task v0.1

- migration 4 adds `tasks`
- create/list/get/complete/cancel lifecycle
- states: open/completed/cancelled
- optional timezone-aware `due_at` normalized to UTC
- exact project canonicalization
- Task API routes
- Task remains intention, not execution authority

### PR #29 — Intelligent chat memory corrections

- deterministic explicit correction parser
- unique strong active target required
- ambiguous/missing targets refuse to guess
- shared atomic correction storage
- preserved history
- project/global correction scope consistent with recall policy
- CI green and external review returned SAFE TO MERGE
- production phone verification passed

### PR #30 — Chat-driven Task creation v0.1

- explicit commands such as `Create a task to call Mike`
- colon form such as `Add task: export stems`
- Task inherits existing conversation project
- shared Task validation/storage
- conversation + user message + Task + assistant confirmation committed atomically
- false-positive task-like ordinary chat remains model chat
- memory command path regression-tested
- `Remind me ...` intentionally remains ordinary chat because no scheduler exists
- CI green and external second-pass review returned SAFE TO MERGE

## Current architecture checkpoint

Production remains deliberately simple:

```text
one Railway service
one application process
one replica
FastAPI
SQLite/WAL on Railway volume
OpenAI for model-backed chat
```

No Redis, queue, vector database, background worker, scheduler, reminder delivery system, external-tool executor, or multiple application replicas exist today.

## Current schema

Migrations are now:

1. `initial_schema`
2. `memory_lifecycle`
3. `model_runs`
4. `tasks`

Current durable domains:

- projects
- conversations/messages
- memories/history/lifecycle
- runs
- tasks

## Current product boundary

MootOS can create a Task but cannot yet promise to wake up later and notify Moot.

Therefore:

```text
Create a task to call Mike
```

can create durable Task state, while:

```text
Remind me to call Mike tomorrow at 3
```

is still ordinary chat and must not be reported as a scheduled reminder.

## Proposed next feature

The next proposed development area is **Scheduler / Reminder v0.1**.

Before implementation, the design must answer:

- whether reminder schedule/delivery state belongs in a separate table or Task extension
- UTC plus user-timezone representation
- relative-time resolution policy
- restart/offline catch-up
- duplicate-fire prevention and durable claiming
- retry/failure/delivery state
- cancellation and rescheduling
- whether the current single Railway process should host a small scheduler loop or use a separate process/service
- deterministic tests with controlled time

The scheduler must preserve the existing boundary:

**Task = intention. Run = execution/audit record. Reminder/schedule = future trigger/delivery state.**

## Documentation status

This documentation-sync branch updates the central source-of-truth documents after PR #30. Historical production-verification records and ADRs should remain unchanged when they accurately describe their original checkpoint, even if they mention older schema versions.

After this documentation PR is reviewed and merged, a full independent repository audit can use these synchronized docs as an orientation map while still verifying all claims against code.
