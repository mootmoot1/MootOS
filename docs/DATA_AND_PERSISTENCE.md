# MootOS Data and Persistence

**Applies to:** `main`, including the merged V0.2A Tool System  
**Current schema:** `5 — tool_system`

## 1. Database choice

MootOS uses SQLite as the single durable source of truth for the current single-user, one-process, one-replica deployment.

That is intentional because it keeps operation simple, low-cost, portable, and compatible with the local-first direction. It is not a statement that SQLite is the forever database for multi-user or multi-replica deployment.

## 2. Production database location

Normal Railway production resolves SQLite from the attached volume:

```text
/data/mootos.db
```

The exact path is derived from Railway volume metadata. Production storage validation fails closed when the expected persistent mount is unavailable. A separate explicit high-risk override exists for recovery/testing scenarios and should not be used casually.

Local development may use the repository-local data path or an approved override.

## 3. Connection policy

All application SQLite connections go through `backend/db.py` and use a common policy including:

- foreign keys enabled
- WAL journal mode
- `synchronous=NORMAL`
- connection timeout
- SQLite busy timeout
- `sqlite3.Row` row factory
- centralized commit/rollback/close behavior

Write operations that require serialized lifecycle changes commonly use `BEGIN IMMEDIATE`.

## 4. Current schema and migrations

`backend/migrations.py` is authoritative.

Current ordered migrations on `main`:

1. `initial_schema`
2. `memory_lifecycle`
3. `model_runs`
4. `tasks`
5. `tool_system` — adds `tool_name`/`tool_version` columns to `runs`, and a new `tool_operations` table. See `docs/TOOL_SYSTEM.md`.

Startup migrations run in order, reject gaps/newer unsupported schemas, verify required tables/columns and important constraints, and roll back on failure.

Do not manually edit `schema_migrations` to force compatibility.

## 5. Durable tables

### `projects`

Stores the project catalog. Default projects are MootOS, Studio, Social Media, Cars, and Personal.

### `conversations`

Stores conversation identity, optional project, title, and timestamps.

### `messages`

Stores user/assistant conversation messages with provider/model metadata. `messages.conversation_id` has an enforced foreign key to `conversations.id`.

### `memories`

Stores durable long-term memory plus lifecycle/history fields:

- content
- optional project
- memory type/source
- created/updated timestamps
- status
- `replaces_memory_id`
- `superseded_by_id`

Memory states are `active`, `superseded`, and `archived`.

### `runs`

Added by migration 3. Stores execution/audit metadata for model/tool-type Runs, including status, timestamps, provider/model, optional linked message IDs, sanitized failure class, optional usage/cost metadata, and data-exposure classification.

Run rows intentionally do not duplicate prompts or model responses, and (V0.2A) never duplicate tool arguments.

**V0.2A (branch only):** migration 5 adds nullable `tool_name`/`tool_version` columns, populated only on `run_type = 'tool'` rows. `provider`/`model` remain model-provider-only fields; they are not repurposed for tool identity. See `docs/TOOL_SYSTEM.md` §8 and ADR-027.

### `tool_operations` (V0.2A)

Added by migration 5. Freezes one model-selected write-tool request for human approval:

- id, `tool_name`, `tool_version`
- `status` (`pending`, `executing`, `succeeded`, `rejected`, `failed`, `expired`)
- `arguments_json` — the already-schema-validated tool arguments, frozen at creation; this is the one place the Tool System *does* durably store tool arguments, by design, so a human can review exactly what would run
- `conversation_id`, `project`
- `created_at`, `updated_at`, `expires_at`, `decided_at`
- `result_run_id`, `result_reference`, `error_class`

See `docs/TOOL_SYSTEM.md` §9 for the state machine and duplicate/expiry safety guarantees.

### `tasks`

Added by migration 4. Stores:

- id
- title
- optional project
- status (`open`, `completed`, `cancelled`)
- optional `due_at`
- created/updated timestamps
- completed/cancelled timestamps

Task `due_at` is a timestamp field, **not a scheduler**. The current application does not automatically fire, deliver, retry, or notify when a Task becomes due.

## 6. Atomicity boundaries

Important multi-row operations are designed so partial durable state is not committed.

Examples:

- explicit memory save: conversation + user message + memory + confirmation
- explicit memory correction: replacement + supersede/history links, plus chat turn when invoked through chat
- chat-driven Task creation: conversation + user message + Task + confirmation
- provider-backed normal chat: provider call happens before the short write transaction; successful user/assistant pair commits atomically
- profile import: accepted batch imports atomically

When a transaction context raises, the connection layer rolls back rather than committing partial writes.

## 7. WAL and concurrency model

WAL and busy timeout improve reliability for the current workload, but they do not make the architecture multi-replica safe.

Current assumptions:

- one Railway application process
- one replica
- modest personal workload
- in-process conversation locks for serializing same-conversation model turns
- SQLite write serialization for lifecycle-sensitive operations

Before adding multiple application replicas, reevaluate coordination and database choice.

## 8. Backup and recovery

The Railway volume protects data across normal service rebuilds, but the volume itself is not a complete disaster-recovery strategy.

A manual WAL-safe snapshot/off-volume restore drill has been performed and documented. Automated encrypted backups, retention, scheduled restore verification, and point-in-time recovery are not implemented yet.

Historical backup-verification documents may mention schema 1 or 2 because that was the production schema at the time. Those records should remain historically accurate.

## 9. Scheduler implications

A future Scheduler / Reminder v0.1 introduces new persistence requirements that are not solved merely by Task `due_at`.

The design must explicitly address:

- durable pending/claimed/delivered/failed/cancelled state
- timezone/source-time metadata if needed for user-visible interpretation
- atomic claim so one reminder cannot be delivered twice
- restart/offline catch-up
- retry policy
- rescheduling/cancellation
- indexes for efficiently finding due pending rows
- test clocks rather than waiting on wall time

Whether that belongs in a separate reminder/schedule table or a carefully bounded extension must be decided before its own migration. (Migration 5 was used by the V0.2A Tool System, ADR-027 — the scheduler's migration will be the next one after whichever of these two branches merges first.)

## 10. Scaling direction

Keep SQLite while the real operating shape remains single-user and one-replica. Evaluate PostgreSQL when real requirements include multiple users, multiple replicas/concurrent writers, managed recovery, or commercial server-side reliability.

Avoid dual-writing to a second database merely for the appearance of redundancy. Prefer one clear source of truth, verified backups, and a tested migration path.
