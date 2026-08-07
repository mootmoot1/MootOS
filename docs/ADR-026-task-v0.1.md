# ADR-026 — Task v0.1

## Status

Draft implementation decision for Task v0.1.

## Context

MootOS already has durable conversation, long-term memory/claims, project scope, semantic retrieval, and structured Run logging. The next capability needs to represent something Moot intends to get done without misusing long-term memory as a to-do list.

A Task is different from a Claim/Memory and different from a Run:

- Claim/Memory: something MootOS may believe or remember.
- Task: an intention or commitment that remains open until finished or cancelled.
- Run: one actual execution attempt by a model or future tool.

The architecture must also remain compatible with the future high-risk action chain:

```text
Task / user request
    -> frozen operation specification
    -> policy evaluation
    -> approval when required
    -> Run
    -> result
```

A Task is not authorization to perform an external side effect.

## Decision

Task v0.1 introduces a dedicated `tasks` table and storage lifecycle.

### Fields

- `id` — stable UUID
- `title` — concise human-readable intention, 1–500 characters
- `project` — optional canonical project scope
- `status` — `open`, `completed`, or `cancelled`
- `due_at` — optional timezone-aware timestamp normalized to UTC
- `created_at`
- `updated_at`
- `completed_at`
- `cancelled_at`

### Lifecycle

```text
open -> completed
open -> cancelled
```

Completed and cancelled are terminal in v0.1. Reopen/restore is deliberately not implemented yet; adding it later should be an explicit lifecycle decision rather than an accidental update.

### Time rule

Task due times must include a timezone. MootOS normalizes them to UTC before storage. This avoids ambiguous reminders when the user, server, or deployment timezone changes.

### Project rule

Tasks may be global (`project = NULL`) or scoped to an existing project. Project names are canonicalized using the existing case-insensitive project store, matching memory behavior.

### Execution/security boundary

A Task describes intent only. Future external actions must not execute by reading mutable Task fields directly.

When MootOS gains write-capable tools, the executor must use a frozen operation specification evaluated by policy and bound to approval when required. Task status and Task payload are not substitutes for that security boundary.

## Out of scope for Task v0.1

- external tool execution
- Gmail/GitHub/calendar actions
- approvals
- frozen operation-spec hashing
- background scheduler/worker
- webhook/Observation matching
- recurrence
- subtasks/dependencies
- priorities/tags
- Entity links
- automatic task extraction from normal chat
- autonomous planning / "Handle it"

These should compose on top of the Task primitive instead of being bundled into its first schema.

## Consequences

### Positive

- reminders and commitments no longer need to pollute long-term memory
- task state is independently queryable and lifecycle-safe
- project-scoped work fits the existing MootOS model
- future automation can attach triggers and operations without redefining what a Task is
- SQLite remains simple and inspectable

### Tradeoffs

- v0.1 cannot actually fire reminders yet
- terminal tasks cannot be reopened yet
- no generic event/trigger engine is introduced before external ingress exists
- project references remain canonical text, consistent with current conversations/memories, rather than introducing a cross-system entity migration

## Follow-on direction

After Task storage/API is production-verified, the next task-related slices can add a minimal authenticated task interface and time-based reminder scheduling. External side effects should wait for the Tool/Policy/Approval/frozen-operation path.
