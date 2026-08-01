# ADR-016 — Versioned Memory Lifecycle and Preserved Correction

**Status:** Accepted and production-verified  
**Date:** August 1, 2026

## Context

MootOS needed a way to correct outdated memories without silently overwriting or deleting prior values. Correction and future recoverable forgetting also needed one shared lifecycle model.

Before migration 2, a WAL-safe production snapshot was downloaded off-volume, verified by SHA-256, and opened through an isolated restore drill.

## Decision

Migration 2 adds to every memory row:

- `status`: `active`, `superseded`, or `archived`
- `updated_at`
- `replaces_memory_id`
- `superseded_by_id`

Existing rows migrate to active with `updated_at = created_at` and null links.

Correction is append-and-supersede:

1. Acquire `BEGIN IMMEDIATE`.
2. Require the selected row to exist and remain active.
3. Reject blank or unchanged replacement content.
4. Insert one new active row preserving project and memory type.
5. Link the new row backward to the selected row.
6. Mark the selected row superseded and link it forward.
7. Commit both changes or roll back.

Normal lists and model context include only active rows. A dedicated history endpoint returns the complete correction chain oldest first. Correction-linked rows cannot be hard-deleted.

The browser requires selecting a specific memory and confirming the correction. Natural-language update is not included.

## Why

- One active row gives the model a current source of truth.
- Superseded rows preserve accountability and recovery options.
- One lifecycle schema supports both correction and later archive/restore.
- Append-and-supersede is easier to audit than an in-place edit.

## Consequences

- Corrections create additional rows.
- History integrity is application-managed because SQLite cannot add self-referential foreign keys through a simple `ALTER TABLE` migration.
- Old schema-1-only code cannot safely run against schema 2.
- Rollback requires schema-2-compatible code or an approved restore.

## Verification

Automated coverage proved migration preservation, idempotency, correction atomicity, rollback, competing-request serialization, active-only context, ordered history, authentication, safe rendering, and hard-delete protection.

PR #15 was merged as commit `82938c7dd08339df8cdfc3ee2fd9d9474d168bef` and deployed to Railway. Existing memories remained available, a selected memory was corrected through the UI, only the corrected active value was recalled in a fresh chat, and it survived another Railway rebuild.

See [`MEMORY_CORRECTION_PRODUCTION_VERIFICATION_2026-08-01.md`](MEMORY_CORRECTION_PRODUCTION_VERIFICATION_2026-08-01.md).
