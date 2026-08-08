# MootOS Current Checkpoint

**Last updated:** August 8, 2026  
**Repository:** `mootmoot1/MootOS`  
**Default branch:** `main`  
**Current release:** Version 0.1 foundation  
**Current schema:** `4 — tasks`

## Current production topology

MootOS is deployed privately on Railway as:

```text
one Railway service
one FastAPI application process
one replica
SQLite/WAL on the Railway volume
OpenAI for model-backed chat
```

Production launches `backend.application:app` and Railway uses `/ready` for deployment readiness. `/health` remains minimal liveness.

No Redis, Celery, distributed queue, vector database, background worker, scheduler, reminder-delivery system, external write-capable tool executor, or multi-replica coordination exists today.

## Production-verified capabilities

The following have direct production verification recorded in the project history/checkpoint process:

- private password/session login
- persistent SQLite on the Railway volume
- `/health` and `/ready`
- OpenAI-backed chat through the private phone interface
- persistent conversations/messages/projects
- explicit chat memory save and cross-chat recall
- protected memory review/search
- memory correction with preserved history
- recoverable archive/restore
- active-memory recall surviving Railway rebuilds
- hardened private HTTP boundary
- atomic provider-backed chat persistence behavior
- intelligent explicit memory correction from PR #29, verified through the real phone UI

## Latest production-verified memory milestone

PR #29 added deterministic explicit memory correction. After merge and Railway deployment, production testing confirmed:

1. an old test memory was saved
2. a correction using `Actually, ... Remember that instead.` was accepted
3. a brand-new conversation recalled only the replacement value
4. the old superseded value did not appear as a conflicting active memory

That verifies the new correction path against the persistent production database and real phone UI.

## Merged on main; production-smoke status tracked separately

The capabilities below are implemented and merged on `main`. Their implementation status should not be confused with a dated production-verification record unless such a record is explicitly added later.

### Curated bootstrap profile import

- protected `/profile` interface
- preview and atomic import APIs
- duplicate/lifecycle checks
- `bootstrap_profile` memory type
- reviewed manifest stays out of the model-provider path
- production composition through `backend.application:app`

### PR #27 — Model Run logging v0.1

- migration 3 adds `runs`
- normal model-provider attempts gain structured execution metadata
- failures record sanitized exception class metadata rather than prompt/response duplication
- Runs establish an execution/audit spine separate from Tasks

### PR #28 — Task v0.1

- migration 4 adds `tasks`
- create/list/get/complete/cancel lifecycle
- states: open/completed/cancelled
- optional timezone-aware `due_at` normalized to UTC
- canonical project scope
- authenticated Task API routes
- Task remains intention, not execution authority

### PR #30 — Chat-driven Task creation v0.1

- explicit commands such as `Create a task to call Mike`
- colon form such as `Add task: export stems`
- Task inherits the existing conversation project
- shared Task validation/storage
- conversation + user message + Task + assistant confirmation commit atomically
- false-positive task-like ordinary chat remains model chat
- memory command path regression-tested
- `Remind me ...` intentionally remains ordinary chat because no scheduler exists
- CI green and external second-pass review returned SAFE TO MERGE

## Current schema

Migrations are:

1. `initial_schema`
2. `memory_lifecycle`
3. `model_runs`
4. `tasks`

Current durable domains/tables include:

- `schema_migrations`
- projects
- conversations/messages
- memories/history/lifecycle
- runs
- tasks

There is no migration 5 on current `main`.

## Current memory boundary

Current memory behavior includes:

- explicit `remember` / `save` writes
- deterministic explicit correction commands
- unique strong-match requirement for chat-driven corrections
- refusal to guess on zero/multiple correction targets
- append-and-supersede correction history
- active/superseded/archived lifecycle
- protected review/search
- deterministic keyword plus reviewed concept-alias retrieval

There are no embeddings or vector database.

## Current Task boundary

MootOS can create durable Tasks, but `due_at` is only stored scheduling metadata.

Therefore:

```text
Create a task to call Mike
```

can create a Task, while:

```text
Remind me to call Mike tomorrow at 3
```

is still ordinary chat and must not be reported as a scheduled reminder.

**Task = intention/work item. Task does not authorize external execution.**

## Proposed next feature

The next proposed development area is **Scheduler / Reminder v0.1**.

Before implementation, the design should answer:

- reminder schedule/delivery storage model
- UTC and user-timezone representation
- relative-time resolution policy
- restart/offline catch-up
- duplicate-fire prevention and durable claiming
- retry/failure/delivery state
- cancellation and rescheduling
- whether a small scheduler loop belongs in the current process or another Railway process/service
- deterministic tests with controlled time

The scheduler should preserve this separation:

**Task = intention. Run = execution/audit record. Reminder/schedule = future trigger/delivery state.**

## Documentation status

PR #31 synchronizes current source-of-truth docs after PR #30 and also updates previously stale live guides such as the operations runbook, bootstrap-profile guide, and Task guide.

Historical ADRs, old branch-specific documents, and dated production-verification records should remain historically accurate even when they mention older schemas. They must not be mistaken for the current runtime map.

After PR #31 is reviewed and merged, a full independent repository audit can use the synchronized current docs as orientation while still verifying every important claim against code.