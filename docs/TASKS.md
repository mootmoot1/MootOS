# Task v0.1

**Status:** Implemented on `main`  
**Schema:** `4 — tasks`

## Goal

Give MootOS a durable place for intentions and commitments without storing them as long-term memory.

Task v0.1 is intentionally small. It provides a durable Task lifecycle and HTTP boundary that future reminders, triggers, approvals, and tools can build on without turning Task itself into execution authority.

## Current implementation

Current `main` includes:

- schema migration 004 for `tasks`
- `backend/tasks.py` storage/lifecycle helpers
- `backend/task_routes.py` authenticated HTTP API
- production composition through `backend.application:app`
- project-scope canonicalization
- timezone-aware due-time validation and UTC normalization
- terminal-state protection
- chat-driven explicit Task creation from PR #30
- migration, storage, route, parser, and chat integration tests
- ADR-026 documenting the Task/Run/future Approval boundary

## Task lifecycle

```text
open
  -> completed
  -> cancelled
```

`completed` and `cancelled` are terminal in v0.1.

## HTTP API

The Task routes use the existing MootOS authentication and private-response protections.

| Method | Path | Purpose |
| --- | --- | --- |
| `POST` | `/tasks` | Create an open Task |
| `GET` | `/tasks` | List Tasks, optionally by status/project |
| `GET` | `/tasks/{task_id}` | Read one Task |
| `POST` | `/tasks/{task_id}/complete` | Complete an open Task |
| `POST` | `/tasks/{task_id}/cancel` | Cancel an open Task |

List queries support `status`, `project`, and bounded `limit` values from 1–500.

## Storage fields

| Field | Meaning |
| --- | --- |
| `id` | Stable UUID |
| `title` | Human-readable intention, max 500 chars |
| `project` | Optional canonical existing MootOS project |
| `status` | `open`, `completed`, or `cancelled` |
| `due_at` | Optional UTC ISO 8601 timestamp |
| `created_at` | UTC creation time |
| `updated_at` | UTC last lifecycle update |
| `completed_at` | UTC completion time when completed |
| `cancelled_at` | UTC cancellation time when cancelled |

## Due-time rule

When `due_at` is supplied through the Task API, callers must provide a timezone-aware ISO 8601 datetime. MootOS converts it to UTC before persistence.

Accepted example:

```text
2026-08-08T09:00:00-04:00
```

Stored form:

```text
2026-08-08T13:00:00+00:00
```

A naive timestamp such as `2026-08-08T09:00:00` is rejected instead of guessed.

**Important:** `due_at` is stored metadata only. MootOS does not currently have a scheduler or reminder-delivery loop, so reaching `due_at` does not cause a notification or background action.

## Project scope

A Task may be global or project-scoped. Project matching is case-insensitive, but storage uses the canonical existing project name. For example, `mootos` is stored as `MootOS`.

Chat-created Tasks inherit the existing conversation project. A conflicting requested project is refused rather than silently moving the Task across project scope.

## Chat-driven Task creation

PR #30 added deterministic explicit Task creation through normal `/chat` behavior.

Examples that create Tasks:

```text
Create a task to call Mike
Add task: export stems
```

The explicit Task path:

1. recognizes only supported deterministic command forms
2. loads or creates the intended conversation
3. preserves/inherits conversation project scope
4. stores the user command
5. creates the open Task through shared Task validation/storage
6. stores a deterministic assistant confirmation
7. commits the complete turn atomically

The model provider is not called for a successfully handled explicit Task command.

Parser safety intentionally leaves ordinary task-related conversation alone. Examples such as:

```text
Create a task system
Create a task manager
Add task list to the sidebar
```

remain normal model chat rather than being silently turned into Tasks.

Reminder language such as:

```text
Remind me to call Mike tomorrow at 3
```

also remains ordinary chat because reminder scheduling/delivery is not implemented yet.

## Ordering

Task lists place scheduled Tasks before unscheduled Tasks, earliest due time first, then newest creation time.

## Security and execution boundary

**Task = intention, not authority.**

A future Task such as:

```text
Email Mike the final mix after he replies.
```

must not directly authorize an email send. Future write-capable execution should follow a boundary like:

```text
Task/trigger condition
    -> freeze exact operation parameters
    -> policy evaluation
    -> approval if required
    -> Run
```

Mutable Task fields must not become direct authority for external side effects.

## Migration status

Migration 004 is already part of `main`. A schema-4 database contains the `tasks` table plus its indexes. Existing memories, conversations, messages, Runs, bootstrap-profile memories, and projects are not rewritten by migration 004.

## Verification status

Task v0.1 and chat-driven Task creation are merged and covered by CI/review. Dated production-smoke records should be distinguished from merged implementation status; do not rewrite historical records to imply verification that was not actually performed.

Useful smoke checks after Task-related deployment changes include:

1. `/ready` succeeds on schema 4.
2. Normal model chat still works and records model Runs.
3. Existing memory/profile behavior remains intact.
4. Create/read one disposable Task.
5. Confirm project canonicalization and UTC due-time behavior when supplied.
6. Complete/cancel lifecycle transitions behave correctly.
7. A second terminal transition is rejected.
8. Task creation does not create a long-term Memory.
9. Explicit chat Task creation works without a provider call.
10. `Remind me ...` is not reported as a scheduled reminder.

## Not implemented yet

- reminder delivery
- background scheduler
- recurring Tasks/reminders
- conditional triggers
- notification delivery state
- external tools
- approvals
- operation-spec hashing/frozen-operation storage
- automatic Task extraction from arbitrary normal chat
- Task UI
- priority/tags/subtasks
- autonomous planning

Those are follow-on capabilities, not reasons to overload Task v0.1.