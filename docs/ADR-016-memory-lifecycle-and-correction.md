# ADR-016 — Versioned Memory Lifecycle and Preserved Correction

**Status:** Accepted and production-verified  
**Date:** August 1, 2026

## Context

MootOS can deliberately save long-term memories, recall them in later chats, and display them in a protected browser interface. The original memory table stored only content, project, type, and creation time.

Directly editing a row would make the newest information available, but it would erase the previous value and make it impossible to review how the memory changed. Permanently deleting the old row would create the same loss of history.

Correction and recoverable forgetting also need a shared lifecycle model. Adding unrelated correction and archive schemas in separate migrations would make the database harder to reason about and restore.

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

The correction operation:

1. Acquires a serialized SQLite write transaction with `BEGIN IMMEDIATE`.
2. Requires the selected memory version to exist and still be active.
3. Rejects blank or unchanged replacement content.
4. Inserts a new active row with the same project and memory type.
5. Links the new row to the old row through `replaces_memory_id`.
6. Marks the old row `superseded` and links it forward through `superseded_by_id`.
7. Commits both changes together or rolls both back.

Normal memory listings and model context use only active rows. A dedicated history endpoint returns the complete correction chain oldest first.

The legacy hard-delete API remains unavailable in the browser. It rejects deletion of any row that participates in correction history so the chain cannot be broken. Recoverable archive and restore reuse the same lifecycle status through the focused follow-up decision in ADR-017.

Correction is selected explicitly in the memory interface and confirmed before the write. Natural-language update commands are not included in this decision.

## Why this decision

The active row gives the model one current source of truth. The superseded rows preserve accountability and make mistakes recoverable without forcing a full database restore.

Using one lifecycle schema prevents correction and forgetting from creating competing definitions of current, old, and hidden memory.

An append-and-supersede operation is also safer to audit than silently mutating a row that may already have influenced conversations.

## Consequences

### Positive

- Corrected information becomes the only version supplied to normal context.
- Previous content remains inspectable.
- Correction is atomic.
- Existing memories survive migration 2.
- Archive and restore can reuse the same status field.
- Correction history cannot be broken through the browser interface or legacy delete endpoint.

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

Deferred. A row-version chain keeps current and historical representations in one schema and supports archive lifecycle work. A separate audit table can be reconsidered if richer actor or reason metadata becomes necessary.

### Add natural-language correction immediately

Rejected. Selecting a specific row and confirming the replacement is safer and easier to verify.

## Verification requirements

Automated coverage proved:

- Migration 2 preserves existing rows.
- Existing rows become active with `updated_at = created_at`.
- Correction creates one linked active replacement and one superseded prior version.
- A second correction extends the same ordered history chain.
- Superseded rows are excluded from active lists and model context.
- Missing, inactive, unchanged, blank, and oversized corrections fail safely.
- A forced failure rolls back the new row and leaves the original active.
- Competing correction requests produce one active replacement.
- Hard deletion cannot break correction history.
- The browser sends only the explicit correction POST and renders stored content through `textContent`.
- Correction and history endpoints require authentication.

## Verification completed

Branch verification included:

- 82 automated tests passed.
- JavaScript syntax and Python bytecode compilation passed.
- A separate copy of the verified production backup migrated from schema 1 to schema 2 with all five projects, fifteen conversations, fifty-eight messages, and two memories preserved.
- Both existing memories became active with populated `updated_at` values.
- A correction rehearsal created one superseded version and one active replacement while keeping `PRAGMA integrity_check = ok`.
- GitHub Actions passed on Python 3.9, 3.10, and 3.11.
- Internal and external read-only review found no blocker.

PR #15 was squash-merged as:

```text
82938c7dd08339df8cdfc3ee2fd9d9474d168bef
```

Production verification confirmed:

- Railway started successfully against schema 2.
- Existing records remained available.
- A selected memory was corrected through the protected interface.
- The prior value remained preserved as superseded history.
- A fresh chat recalled only the corrected active value.
- The corrected value survived another Railway rebuild.

See [`MEMORY_CORRECTION_PRODUCTION_VERIFICATION_2026-08-01.md`](MEMORY_CORRECTION_PRODUCTION_VERIFICATION_2026-08-01.md).
