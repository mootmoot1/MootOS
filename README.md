# MootOS

MootOS is Moot's private, mobile-friendly personal AI foundation. It runs as a single FastAPI application backed by SQLite on a persistent Railway volume and is intentionally developed in small, reviewable steps.

## Current status

**Version:** 0.1.0  
**Primary branch:** `main`  
**Production shape:** one Railway service, one replica  
**Database:** SQLite on the Railway volume  
**Current schema:** `4 — tasks`  
**Current model provider:** OpenAI through a replaceable provider interface

The current codebase includes persistent chat, long-term memory, memory lifecycle controls, deterministic memory retrieval, a curated profile-import path, model Run logging, Task v0.1, and explicit chat-driven Task creation.

See [`docs/CURRENT_CHECKPOINT.md`](docs/CURRENT_CHECKPOINT.md) for the latest project checkpoint and [`docs/CURRENT_IMPLEMENTATION.md`](docs/CURRENT_IMPLEMENTATION.md) for the code-level architecture map.

**In development, not yet merged:** a V0.2A Tool Foundation on branch `claude/motos-v0.2a-tool-foundation-u46ew4` — a small, fail-closed Tool System that lets the model invoke four controlled internal tools (read Projects/Memory/Tasks automatically; propose a Task write only with explicit human approval). See [`docs/TOOL_SYSTEM.md`](docs/TOOL_SYSTEM.md).

## What works today

- Private password login and signed HTTP-only sessions
- Fail-closed Railway auth and storage checks
- Public minimal `/health` and `/ready` endpoints
- Mobile chat interface with persistent conversations
- Five default projects: MootOS, Studio, Social Media, Cars, Personal
- OpenAI Responses API behind a replaceable model-provider boundary
- Atomic provider-backed chat persistence after successful generation
- Model-input budgeting and capability guidance
- Persistent long-term memory in SQLite
- Explicit chat memory saves such as `Remember that ...`
- Intelligent explicit memory corrections such as `Actually, ... Remember that instead.`
- Memory correction history, archive/forget, restore, and protected review UI
- Deterministic keyword plus reviewed concept-alias retrieval; no embeddings/vector database
- Curated bootstrap-profile preview/import using existing memory lifecycle
- Model Run logging for provider attempts without duplicating prompt/response content
- Task v0.1 storage with open/completed/cancelled lifecycle
- Optional timezone-aware Task due timestamps normalized to UTC
- Explicit chat Task creation such as `Create a task to call Mike` and `Add task: export stems`
- Project inheritance for chat-created Tasks
- Mobile Task viewer/creation page at `/task`
- Read-only Activity page at `/activity` (recent model Runs, Tasks, and memories)
- Read-only Settings page at `/settings` (current provider/model/schema version; no secrets, no runtime mutation)
- A direct "add a memory" form on `/memory`, in addition to chat-command and bootstrap-profile saves
- WAL-mode SQLite with foreign keys, busy timeout, migrations, and schema checks
- CI across Python 3.9, 3.10, and 3.11

## Important current boundaries

MootOS does **not** yet have a scheduler, reminder delivery, recurrence, conditional automation, calendar/email/tool execution, or background-agent system.

A Task represents an intention or work item. It is not execution authority. Future write-capable external actions must not execute directly from mutable Task fields; they require separate execution/audit and approval boundaries.

`Remind me ...` remains ordinary model chat today because MootOS cannot truthfully promise reminder delivery yet.

## Deterministic chat writes

MootOS intercepts only narrow, explicit command families for durable writes.

Memory examples:

```text
Remember that my preferred DAW is Pro Tools.
Save this to memory: use concise explanations.
Actually, my preferred DAW is Pro Tools Ultimate. Remember that instead.
```

Task examples:

```text
Create a task to call Mike
Add task: export stems
```

These paths write through MootOS storage and return confirmation only after the write succeeds. Ordinary chat goes through the configured model provider.

## Memory model

Memory lifecycle states are:

```text
active
superseded
archived
```

Correction is append-and-supersede rather than destructive overwrite. Archived and superseded versions remain outside normal model recall. Project chats can use global memory plus relevant project/cross-project matches according to the deterministic retrieval rules.

## Task model

Task lifecycle states are:

```text
open
completed
cancelled
```

Task fields currently include title, optional project, optional UTC-normalized due time, lifecycle timestamps, and status. Scheduler/reminder state is intentionally not stored in Task v0.1 yet.

## Database migrations

Current ordered migrations:

1. `initial_schema`
2. `memory_lifecycle`
3. `model_runs`
4. `tasks`

`backend/migrations.py` is the source of truth for the current schema version.

## Production architecture

MootOS deliberately remains simple while it is single-user:

```text
Phone browser
    ↓
FastAPI / backend.application:app
    ↓
SQLite on Railway volume
    ↓
OpenAI only for model-backed chat
```

There is currently no Redis, Celery, external queue, vector database, second application replica, microservice split, or background worker.

## Next proposed capability

The next proposed feature is **Scheduler / Reminder v0.1**. Before implementation, the repository should be reviewed for the smallest reliable design covering durable due state, timezone handling, restart recovery, duplicate-fire prevention, delivery state, and testing with controlled time.

Do not document scheduler/reminder behavior as implemented until code, tests, review, deployment, and production verification are complete.

## Documentation

Start here:

1. [`docs/CURRENT_CHECKPOINT.md`](docs/CURRENT_CHECKPOINT.md)
2. [`docs/CURRENT_IMPLEMENTATION.md`](docs/CURRENT_IMPLEMENTATION.md)
3. [`docs/API_REFERENCE.md`](docs/API_REFERENCE.md)
4. [`V0.1_REQUIREMENTS.md`](V0.1_REQUIREMENTS.md)
5. [`ROADMAP.md`](ROADMAP.md)
6. [`docs/README.md`](docs/README.md)

Historical PR/production-verification documents describe the repository at the time they were written; they are not the current source of truth when they conflict with the files above.
