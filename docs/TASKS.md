# Task v0.1

## Goal

Give MootOS a durable place for intentions and commitments without storing them as long-term memory.

Task v0.1 is intentionally small. It creates the lifecycle and database shape that later reminders, triggers, approvals, and tools can build on.

## Current implementation

The branch includes:

- schema migration 004 for `tasks`
- `backend/tasks.py` storage/lifecycle helpers
- project scope canonicalization
- timezone-aware due-time validation and UTC normalization
- terminal-state protection
- migration and lifecycle tests
- ADR-026 documenting the Task/Run/Approval boundary

## Task lifecycle

```text
open
  -> completed
  -> cancelled
```

`completed` and `cancelled` are terminal in v0.1.

## Storage fields

| Field | Meaning |
| --- | --- |
| `id` | Stable UUID |
| `title` | Human-readable task intention, max 500 chars |
| `project` | Optional existing MootOS project |
| `status` | `open`, `completed`, or `cancelled` |
| `due_at` | Optional UTC ISO 8601 timestamp |
| `created_at` | UTC creation time |
| `updated_at` | UTC last lifecycle update |
| `completed_at` | UTC completion time when completed |
| `cancelled_at` | UTC cancellation time when cancelled |

## Due-time rule

Callers must supply a timezone-aware ISO 8601 datetime. MootOS converts it to UTC before persistence.

Accepted example:

```text
2026-08-08T09:00:00-04:00
```

Stored form:

```text
2026-08-08T13:00:00+00:00
```

A naive timestamp like `2026-08-08T09:00:00` is rejected rather than guessed.

## Project scope

A Task may be global or project-scoped. Project matching is case-insensitive, but storage uses the canonical existing project name. For example, `mootos` is stored as `MootOS`.

## Ordering

Task lists place scheduled tasks before unscheduled tasks, earliest due time first, then newest creation time.

## Security boundary

Task is intention, not authority.

A future task such as:

```text
Email Mike the final mix after he replies.
```

must not directly authorize an email send. Future write-capable execution should be:

```text
Task condition satisfied
    -> freeze exact operation parameters
    -> policy evaluation
    -> approval if required
    -> Run
```

Any changed recipient, attachment, body, branch, amount, or other side-effect parameter must require a new frozen operation/approval as appropriate.

## Production migration

After this feature is merged, startup migration advances the SQLite schema from version 3 to version 4 and creates the empty `tasks` table plus indexes. Existing memories, conversations, messages, Runs, profile data, and projects are not rewritten.

## Production verification plan

Before calling Task v0.1 complete:

1. `/ready` succeeds after schema version 4 migration.
2. Existing normal chat still works and produces model Runs.
3. Existing memories/profile retrieval remain intact.
4. Create one test Task through the eventual authenticated Task API.
5. Read it back and confirm canonical project scope and UTC due time.
6. Complete it and verify `completed_at` is populated.
7. Verify a second terminal transition is rejected.
8. Confirm task creation does not create or modify a Memory.

## Not in this slice

- reminder delivery
- recurring tasks
- background scheduler
- conditional triggers
- external tools
- approvals
- operation-spec hashing
- automatic task extraction from normal chat
- task UI
- priority/tags/subtasks
- autonomous planning

Those are follow-on capabilities, not reasons to make the first Task primitive complicated.
