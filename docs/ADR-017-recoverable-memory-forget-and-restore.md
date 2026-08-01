# ADR-017 — Recoverable Memory Forget and Restore

**Status:** Proposed  
**Date:** August 1, 2026

## Context

MootOS can save memories, review them, and correct outdated information while preserving prior versions. Migration 2 already defines three lifecycle states:

```text
active
superseded
archived
```

A user-facing “forget” action must remove a memory from normal recall without destroying data or breaking correction history. Permanent deletion is too risky for the first forget workflow because a mistaken click would be irreversible.

PR #15 and migration 2 were production-verified before this branch began. The corrected active value survived a Railway rebuild and the superseded value stayed out of normal recall. The non-private record is in `MEMORY_CORRECTION_PRODUCTION_VERIFICATION_2026-08-01.md`.

## Decision

The first forget workflow is recoverable archival.

### Forget

1. Moot selects one active memory on the protected Memory page.
2. Moot confirms the exact memory in a dialog.
3. The backend starts `BEGIN IMMEDIATE`.
4. It reloads the row and requires it to remain the latest active version.
5. It changes `status` from `active` to `archived` and updates `updated_at`.
6. The change commits atomically or rolls back.

Archived memories are excluded from normal active lists and model context, so they cannot be recalled in ordinary chat.

### Restore

1. Moot opens the Archived view.
2. Moot selects one archived memory and confirms restoration.
3. The backend starts `BEGIN IMMEDIATE`.
4. It reloads the row and requires it to remain the latest archived version.
5. It changes `status` from `archived` to `active` and updates `updated_at`.
6. The change commits atomically or rolls back.

A restored memory returns to normal listing and recall.

### History and deletion

Correction links remain unchanged during archive and restore. A correction chain may therefore end in either an active or archived latest version.

Archived memories and correction-linked memories remain protected from the legacy hard-delete endpoint. The browser exposes no permanent-delete control.

## API

This branch adds:

```text
POST /memories/{memory_id}/archive
POST /memories/{memory_id}/restore
GET  /memories?status=active
GET  /memories?status=archived
```

`active` remains the default list status. Superseded rows remain available only through direct retrieval and the correction-history API.

## User interface

The protected Memory page adds:

- Active and Archived views
- **Forget** on active memories
- **Restore** on archived memories
- Explicit confirmation dialogs showing the selected content
- Loading, success, and error states
- Safe rendering through `textContent`

The UI sends only explicit `POST` requests for correction, archive, and restore. It sends no `DELETE`, `PATCH`, or `PUT` memory request.

## Consequences

### Positive

- Forgetting is reversible.
- Archived content stops entering model context immediately.
- Correction history remains intact.
- The existing migration 2 schema is reused; no migration 3 is needed.
- Competing requests serialize through SQLite.

### Tradeoffs

- Archived data still exists in SQLite.
- This is not secure erasure or privacy deletion.
- The user must use the Memory page; natural-language forget is intentionally unsupported.
- There is no bulk archive, retention policy, or automatic cleanup.

## Alternatives considered

### Permanent delete

Rejected for the first workflow because it is irreversible and can break correction history.

### Natural-language forget

Deferred because selecting an exact row and confirming it is safer and easier to audit.

### Separate archive table

Rejected because migration 2 already defines the archived lifecycle state and keeping versions in one table preserves history traversal.

## Verification requirements

Before merge, tests and review must prove:

- Archive removes a memory from active lists and model context.
- Archived listing returns only archived rows.
- Restore returns the exact row to active recall.
- Correction chains survive archive and restore.
- Missing and wrong-state requests fail safely.
- Competing archive or restore requests produce one winner.
- Forced failures roll back.
- Archived rows cannot be hard-deleted.
- Endpoints require authentication.
- Browser actions require an exact selected memory and confirmation.
- Stored content is rendered safely.
- No permanent-delete or natural-language forget behavior is added.
