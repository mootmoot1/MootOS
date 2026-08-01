# ADR-016 — Versioned Memory Lifecycle and Preserved Correction

**Status:** Proposed  
**Date:** August 1, 2026

## Context

MootOS can deliberately save long-term memories, recall them in later chats, and display them in a protected browser interface. The original memory table stores only content, project, type, and creation time.

Directly editing a row would make the newest information available, but it would erase the previous value and make it impossible to review how the memory changed. Permanently deleting the old row would create the same loss of history.

Correction and future recoverable forgetting also need a shared lifecycle model. Adding unrelated correction and archive schemas in separate migrations would make the database harder to reason about and restore.

Before this decision, a WAL-safe production snapshot was moved off the Railway volume, verified by SHA-256, and opened successfully through an isolated restore drill. The non-private verification record is in `BACKUP_RESTORE_VERIFICATION_2026-08-01.md`.

## Decision

Migration 2 adds these fields to every memory row:

- `status`: `active`, `superseded`, or `archived`
- `updated_at`: last lifecycle change timestamp
- `replaces_memory_id`: prior version replaced by this row
- `superseded_by_id`: newer version that replaced this row

Existing rows migrate to:

```text
status = active
updated_at = created_at
replaces_memory_id = null
superseded_by_id = null
```

A correction is not an in-place edit.

The correction operation will:

1. Acquire a serialized SQLite write transaction with `BEGIN IMMEDIATE`.
2. Require the selected memory version to exist and still be active.
3. Reject blank or unchanged replacement content.
4. Insert a new active row with the same project and memory type.
5. Link the new row to the old row through `replaces_memory_id`.
6. Mark the old row `superseded` and link it forward through `superseded_by_id`.
7. Commit both changes together or roll both back.

Normal memory listings and model context use only active rows. A dedicated history endpoint can return the complete correction chain oldest first.

The legacy hard-delete API remains unavailable in the browser. It will reject deletion of any row that participates in correction history so the chain cannot be broken. A later focused branch will add recoverable archive and optional restore behavior.

Correction is selected explicitly in the memory interface and confirmed before the write. Natural-language update commands are not included in this decision.

## Why this decision

The active row gives the model one current source of truth. The superseded rows preserve accountability and make mistakes recoverable without forcing a full database restore.

Using one lifecycle schema now prevents correction and forgetting from creating competing definitions of current, old, and hidden memory.

An append-and-supersede operation is also safer to audit than silently mutating a row that may already have influenced conversations.

## Consequences

### Positive

- Corrected information becomes the only version supplied to normal context.
- Previous content remains inspectable.
- Correction is atomic.
- Existing memories survive migration 2.
- Later archive and restore work can reuse the same status field.
- Correction history cannot be broken through the existing browser interface or legacy delete endpoint.

### Tradeoffs

- Corrections create additional rows.
- The schema contains application-managed self-links rather than SQLite foreign keys because SQLite cannot add those constraints to the existing table through a simple `ALTER TABLE` migration.
- History integrity depends on transaction logic and tests.
- Production rollback after migration 2 must use code compatible with schema 2 or a verified pre-migration database restore.

## Alternatives considered

### Update the original row in place

Rejected because it destroys the old value and makes correction history impossible.

### Store old values only in application logs

Rejected because logs are not the durable source of truth for memory and may not be retained with the database.

### Add a separate correction-history table

Deferred. A row-version chain keeps current and historical representations in one schema and can also support archive lifecycle work. A separate audit table can be reconsidered if richer actor or reason metadata becomes necessary.

### Add natural-language correction immediately

Rejected for this branch. Selecting a specific row and confirming the replacement is safer and easier to verify.

## Verification

Automated coverage must prove:

- Migration 2 preserves existing rows.
- Existing rows become active with `updated_at = created_at`.
- Correction creates one linked active replacement and one superseded prior version.
- A second correction extends the same ordered history chain.
- Superseded rows are excluded from active lists and model context.
- Missing, inactive, unchanged, blank, and oversized corrections fail safely.
- A forced failure rolls back the new row and leaves the original active.
- Hard deletion cannot break correction history.
- The browser sends only the explicit correction POST and still renders stored content through `textContent`.

Local verification completed on the branch:

- 82 automated tests passed.
- JavaScript syntax and Python bytecode compilation passed.
- A separate copy of the verified production backup migrated from schema 1 to schema 2 with all five projects, fifteen conversations, fifty-eight messages, and two memories preserved.
- Both existing memories became active with populated `updated_at` values.
- A correction rehearsal on that copy created one superseded version and one active replacement while keeping `PRAGMA integrity_check = ok`.
- The original verified backup remained unchanged.

GitHub Actions and production verification remain required after push, review, merge, and deployment.
