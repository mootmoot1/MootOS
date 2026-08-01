# MootOS Current Checkpoint

**Last updated:** August 1, 2026  
**Repository:** `mootmoot1/MootOS`  
**Default branch:** `main`  
**Current release:** Version 0.1 foundation  
**Production schema:** `2 — memory_lifecycle`

## Verified production state

MootOS is deployed privately on Railway as one FastAPI service and one replica. Production data is stored in SQLite at `/data/mootos.db` on the attached Railway volume.

Verified in production:

- Private login, chat, projects, conversations, and OpenAI-backed responses work.
- Conversations and memories survive Railway rebuilds.
- Explicit `remember` and `save` commands create database-backed long-term memories without calling the model.
- A protected Memory page lists active global and project memories and supports scope filters.
- Projects are focus lenses, not secrecy walls: main/no-project chat can use all active saved memories.
- A WAL-safe snapshot was downloaded off-volume, matched by SHA-256, and passed an isolated restore drill.
- Migration 2 deployed without losing the existing memories or conversations.
- UI-selected correction created a new active version while preserving the prior version as superseded history.
- A fresh chat recalled only the corrected active value.
- The corrected value survived another Railway rebuild.

Automatic encrypted backups, retention, point-in-time recovery, and scheduled restore testing are not implemented.

## Completed milestones

### PR #11 — Foundation hardening

Merged commit: `d4c0772e2948e33631a2e3a24a70433ad4ba94c2`

Centralized SQLite configuration, WAL mode, foreign keys, numbered migrations, schema compatibility checks, exact dependency pins, concurrency tests, and Railway auth fail-closed behavior.

### PR #12 — Explicit chat memory saves

Merged commit: `067ad6f00c9adba8723d7de5706eaea0ff13533a`

Added deterministic save commands, atomic chat-and-memory writes, cross-chat recall, rollback coverage, and production verification through a rebuild.

### PR #14 — Memory review UI

Merged commit: `78806da6c9d4ba33f956b65b17c3dbb549031f83`

Added the protected `/memory` page, active-memory cards, All/Global/project filters, mobile layout, safe `textContent` rendering, and stale-request protection. Production filters and recall were verified.

### Pre-migration backup and restore gate

Completed August 1, 2026.

- Schema-1 snapshot created with SQLite’s online backup API
- Private off-volume download
- Matching SHA-256
- `PRAGMA integrity_check = ok`
- Five projects, fifteen conversations, fifty-eight messages, and two memories
- Isolated MootOS startup against a separate restore copy
- Known conversation and memory reads

See [`BACKUP_RESTORE_VERIFICATION_2026-08-01.md`](BACKUP_RESTORE_VERIFICATION_2026-08-01.md).

### PR #15 — Memory correction with preserved history

Merged commit: `82938c7dd08339df8cdfc3ee2fd9d9474d168bef`

Implemented:

- Migration 2 lifecycle fields: `status`, `updated_at`, `replaces_memory_id`, and `superseded_by_id`
- Atomic append-and-supersede correction
- Active-only normal listing and model context
- Ordered correction-history API
- Protection against competing corrections and hard-deleting correction chains
- Confirmed mobile correction UI

Production verification:

- Railway deployed migration 2 successfully.
- Existing records remained available.
- A selected memory was corrected through the UI.
- Only the corrected active value was recalled in a new chat.
- The correction survived a Railway rebuild.

See [`MEMORY_CORRECTION_PRODUCTION_VERIFICATION_2026-08-01.md`](MEMORY_CORRECTION_PRODUCTION_VERIFICATION_2026-08-01.md).

## Current work — recoverable memory forget and restore

Branch:

```text
feature/memory-forget-v0.1
```

Purpose:

Let Moot deliberately remove one active memory from normal recall without permanently deleting it, then restore it later when needed.

Implemented locally on the branch:

- Reuses migration 2; no new schema migration
- `POST /memories/{id}/archive`
- `POST /memories/{id}/restore`
- `GET /memories?status=active|archived`
- Active and Archived views on the Memory page
- Explicit **Forget** and **Restore** confirmation dialogs
- Archived rows excluded from model context and normal recall
- Correction chains preserved through archive and restore
- Archived rows protected from hard deletion
- Serialized lifecycle writes with `BEGIN IMMEDIATE`
- Safe DOM rendering and no browser `DELETE`, `PATCH`, or `PUT`

Local verification:

- 83 automated tests passed.
- Python bytecode compilation passed.
- JavaScript syntax validation passed.

Still required:

- GitHub Actions on Python 3.9, 3.10, and 3.11
- Complete internal diff review
- External read-only review
- Plain-language review with Moot
- Moot’s explicit approval before merge
- Railway production verification after merge

## Out of scope for this branch

- Permanent-delete UI or secure erasure
- Natural-language `forget`
- Bulk archive or restore
- Automatic retention or cleanup
- Keyword or semantic retrieval
- Full browser correction-history viewer
- Multi-user permissions

## Locked sequence

1. Memory review — complete
2. Memory correction — complete and production-verified
3. Recoverable forget/archive — current
4. Keyword retrieval before embeddings
5. Conversation refinement
6. Curated Moot bootstrap profile

## Operating rules

- One focused branch and draft PR at a time
- Tests and synchronized documentation in the same PR
- One Railway replica while SQLite is live
- No secrets, private backups, or memory content in GitHub
- No claim of success without direct verification
- No merge or high-risk production action without Moot’s explicit approval
