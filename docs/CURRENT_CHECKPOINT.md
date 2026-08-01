# MootOS Current Checkpoint

**Last updated:** August 1, 2026  
**Repository:** `mootmoot1/MootOS`  
**Default branch:** `main`  
**Current release:** Version 0.1 foundation  
**Production schema:** `2 — memory_lifecycle`

## Verified production state

MootOS is deployed on Railway and accessible through its private phone-friendly interface.

Verified production facts:

- Railway deploys from `main`.
- FastAPI is online.
- Private password login works.
- OpenAI returns real responses through the backend.
- Conversations, messages, projects, and memories use SQLite at `/data/mootos.db`.
- Railway volume `mootos-volume` is attached at `/data`.
- Railway remains at one replica.
- Foundation hardening deployed successfully without losing older conversations.
- Explicit chat memory saves work in production.
- A global fact saved in one chat was recalled in a completely new chat.
- The same fact remained available after Railway rebuilds.
- The protected Memory page works in production.
- All, Global-only, and exact-project filters work.
- Migration 2 deployed without losing existing memories or conversations.
- UI-selected correction works in production.
- Only the corrected active value was recalled in a new chat.
- The corrected value survived another Railway rebuild.

Projects are focus lenses, not permanent memory walls. A no-project conversation can use all active saved memory. A selected project currently focuses context on global plus matching-project memory; broader relevant cross-project ranking belongs to the later retrieval branch.

Automatic encrypted backups, retention, scheduled restore testing, and point-in-time recovery are not implemented.

## Completed milestones

### PR #2 — Persistent SQLite memory

- Memory create, list, retrieve, filter, and delete APIs
- UUID IDs and UTC timestamps
- Persistent SQLite storage

### PR #3 — Minimal project system

- Five default projects
- Project creation and listing
- Case-insensitive duplicate protection
- Project filtering
- ADR-011

### PR #5 — Conversation engine and model-provider boundary

- Persistent conversations and messages
- Conversation and chat endpoints
- Recent history and relevant memories supplied to the model
- Replaceable provider protocol
- OpenAI Responses API provider
- Provider metadata
- ADR-012

### PR #7 — Mobile chat interface

- Responsive chat interface
- New Chat control
- Project selector
- Saved conversation history
- Reopening conversations
- Loading and error states
- Interface tests
- ADR-013

### PR #9 — Secure Railway phone deployment

- Railway configuration
- Public minimal health endpoint
- Password login and signed sessions
- Protected application and APIs
- Secure cookies on Railway
- Phone Home Screen manifest
- Railway volume path support
- Deployment and auth tests
- ADR-014

### PR #10 — Comprehensive documentation baseline

- Complete README
- Current implementation and API references
- Data and persistence guide
- Operations runbook
- Documentation policy
- Updated roadmap and Version 0.1 requirements

### PR #11 — Foundation hardening

Merged into `main` on July 31, 2026.

Squash merge commit:

```text
d4c0772e2948e33631a2e3a24a70433ad4ba94c2
```

Implemented:

- Central SQLite connection layer
- Foreign-key enforcement
- WAL mode
- `NORMAL` synchronous mode
- Five-second connection and busy timeouts
- Versioned migrations and `schema_migrations`
- Existing-schema compatibility verification
- Rejection of newer unknown schemas
- Railway auth fail-closed behavior
- Explicit public override
- Exact dependency pins
- Concurrent-write, migration, and auth safety tests
- ADR-015 and synchronized documentation

Production result:

- Railway deployed successfully.
- The application remained usable.
- Conversation history survived the deployment.

### PR #12 — Chat memory commands

Merged into `main` on July 31, 2026.

Squash merge commit:

```text
067ad6f00c9adba8723d7de5706eaea0ff13533a
```

Implemented:

- Deterministic parser for explicit `remember` and `save` commands
- Rejection of incomplete, placeholder, and punctuation-only content
- Atomic explicit-memory chat transaction in `backend/chat_memory.py`
- New conversation, user message, memory row, and confirmation commit together
- Complete rollback when the memory or confirmation write fails
- Save commands bypass OpenAI and do not spend model credits
- Chat-created memories use memory type `explicit_chat`
- Internal confirmations use provider `mootos` and model `memory-command-v1`
- Global memories are available in project chats
- No-project chat can load all saved memories
- Existing 10,000-character memory limit
- Cross-chat recall and rollback regression tests
- External read-only review followed by verification

Automated verification:

- GitHub Actions passed on Python 3.9, 3.10, and 3.11.
- Dependency installation, blocking-error lint, and the complete test suite passed in every matrix job.

Production verification:

1. Railway rebuilt from merged `main`.
2. The application returned online.
3. Login and chat worked.
4. Moot saved a unique fact through an explicit chat memory command.
5. MootOS returned its deterministic database-backed confirmation.
6. A brand-new chat recalled the saved fact.
7. Railway was rebuilt again.
8. Another new chat recalled the same fact after the rebuild.

### PR #13 — Production verification documentation

Merged into `main` on July 31, 2026.

Squash merge commit:

```text
8376fd9da4fdf685ac39dca453bd23e81c53849c
```

Implemented:

- Recorded PR #12 production verification
- Removed stale draft and pending language
- Locked the memory-control branch sequence
- Added a manual WAL-safe SQLite backup and restore procedure
- Clarified main, WAL, and SHM handling during restore

### PR #14 — Memory review interface

Merged into `main` on July 31, 2026.

Squash merge commit:

```text
78806da6c9d4ba33f956b65b17c3dbb549031f83
```

Implemented:

- Protected `GET /memory` browser route
- Memories controls in chat navigation
- Active memory cards loaded from the existing API
- Memory content, scope, project, type/source, and creation date
- All-memory, Global-only, and exact-project filters
- Refresh, loading, empty, and error states
- Mobile responsive layout
- Safe DOM rendering through `textContent`
- Stale-request generation guard
- No browser mutation request at that milestone

Production verification:

- Railway deployed successfully.
- Login and the Memory page worked.
- Both saved memories appeared.
- All, Cars, and Global filters worked.
- Chat and existing conversations remained usable.
- Cars memory was recalled from a Cars chat and from main/no-project chat, matching the intended focus-lens design.

### Pre-migration backup and restore gate

Completed August 1, 2026.

- Schema-1 snapshot created with SQLite's online backup API
- Private off-volume download
- Matching SHA-256
- `PRAGMA integrity_check = ok`
- Five projects, fifteen conversations, fifty-eight messages, and two memories
- Isolated MootOS startup against a separate restore copy
- Known conversation and memory reads
- Original backup remained unchanged

See [`BACKUP_RESTORE_VERIFICATION_2026-08-01.md`](BACKUP_RESTORE_VERIFICATION_2026-08-01.md).

### PR #15 — Memory correction with preserved history

Merged into `main` on August 1, 2026.

Squash merge commit:

```text
82938c7dd08339df8cdfc3ee2fd9d9474d168bef
```

Implemented:

- Migration 2 lifecycle fields: `status`, `updated_at`, `replaces_memory_id`, and `superseded_by_id`
- Existing memory rows preserved and adopted as active
- Atomic append-and-supersede correction
- Active-only normal listing and model context
- Ordered correction-history API
- Protection against competing corrections
- Protection against hard-deleting correction chains
- Confirmed mobile correction UI
- ADR-016 and synchronized documentation

Automated verification:

- GitHub Actions passed on Python 3.9, 3.10, and 3.11.
- Local tests, compilation, JavaScript parsing, production-backup migration rehearsal, and external review passed.

Production verification:

- Railway deployed migration 2 successfully.
- Existing records remained available.
- A selected memory was corrected through the UI.
- The replacement appeared as the active corrected version.
- The prior version remained preserved as superseded history.
- A fresh no-project chat recalled only the corrected active value.
- The corrected value survived another Railway rebuild.

See [`MEMORY_CORRECTION_PRODUCTION_VERIFICATION_2026-08-01.md`](MEMORY_CORRECTION_PRODUCTION_VERIFICATION_2026-08-01.md).

## Current work — recoverable memory forget and restore

Branch:

```text
feature/memory-forget-v0.1
```

Draft PR:

```text
#16 — feat: add recoverable memory forget and restore
```

Purpose:

Let Moot deliberately remove one exact active memory from normal recall without permanently deleting it, then restore that same row later.

Implemented on the branch:

- Reuses migration 2; no new schema migration
- `POST /memories/{id}/archive`
- `POST /memories/{id}/restore`
- `GET /memories?status=active|archived`
- Active and Archived views on the protected Memory page
- Exact selected-memory **Forget** confirmation
- Exact selected-memory **Restore** confirmation
- Archived rows excluded from model context and normal recall
- Correction chains preserved through archive and restore
- Archived rows protected from hard deletion
- Serialized lifecycle writes with `BEGIN IMMEDIATE`
- Conflict handling for stale or wrong-state requests
- Forced-failure rollback coverage
- Competing-request coverage
- Safe DOM rendering through `textContent`
- No browser memory `DELETE`, `PATCH`, or `PUT`
- ADR-017 and synchronized documentation

Local verification:

- 83 automated tests passed.
- Python bytecode compilation passed.
- JavaScript syntax validation passed.

GitHub verification:

- The first exact draft head passed GitHub Actions on Python 3.9, 3.10, and 3.11.
- Documentation was subsequently tightened to preserve useful detail, so the final exact head must pass CI again before review completion.

Still required before merge:

- GitHub Actions on the exact final head
- Complete final diff review
- External read-only review
- Plain-language review with Moot
- Moot's explicit approval for the exact PR

Still required after merge:

- Railway reaches online status
- Login remains functional
- Existing active memories remain visible
- Forget one selected test memory
- Confirm a new chat does not recall the archived value
- Confirm the exact row appears in Archived
- Restore the same row
- Confirm a new chat recalls it again
- Confirm the lifecycle result survives a Railway rebuild

## Current implementation boundaries

MootOS remains:

- Single user
- Text chat only
- One Railway service and replica
- One SQLite database
- One implemented external model provider
- No background queue
- No local model
- No runtime tools
- No multi-agent system
- No automatic off-volume backups

## Explicitly out of scope for PR #16

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

- One focused purpose per branch and PR
- No secrets or private backups in GitHub
- Tests for important behavior
- Documentation updated in the same PR
- Major architecture decisions use ADRs
- One Railway replica while SQLite is live
- Verified backup and restore drill before destructive or schema-changing production work
- Never claim a memory was saved unless the complete storage transaction committed
- Exact selection and confirmation before lifecycle mutations
- Honest reporting of tests, deployments, and uncertainty
- Moot explicitly approves merges and high-risk actions

## Immediate decision

Finish final exact-head CI and internal review for PR #16, then request external read-only review. Do not merge until Moot explicitly approves the reviewed exact head.
