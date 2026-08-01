# MootOS Current Checkpoint

**Last updated:** August 1, 2026  
**Repository:** `mootmoot1/MootOS`  
**Default branch:** `main`  
**Current release:** Version 0.1 foundation

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
- Explicit chat memory saves are working in production.
- A global fact saved in one chat was recalled in a completely new chat.
- The same fact remained available after another Railway rebuild.
- PR #14 read-only Memory Review deployed successfully.
- Production displayed both global and Cars-project memories.
- All memories, Global only, and Cars filters returned the expected records.
- A Cars memory was recalled in a fresh Cars chat and in the main no-project chat, matching the clarified product intent that projects are focus lenses rather than secrecy walls.
- A consistent SQLite snapshot was downloaded off-volume with a matching SHA-256 and passed an isolated restore drill.

This proves that the normal chat interface writes durable memory to SQLite and that the Railway volume preserves that memory through deployment rebuilds.

One manual off-volume backup and restore drill is verified. Automatic backups, retention, encryption, and point-in-time recovery are not implemented.

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
- Project memories remain isolated from unrelated projects
- Existing 10,000-character memory limit
- Cross-chat recall and rollback regression tests
- External read-only review followed by a second verification review

Automated verification:

- GitHub Actions passed on Python 3.9, 3.10, and 3.11.
- Dependency installation, blocking-error lint, and the complete test suite passed in every matrix job.

Production verification:

1. Railway rebuilt from the merged `main` branch.
2. The application returned online.
3. Login and chat worked.
4. Moot saved a unique fact through an explicit chat memory command.
5. MootOS returned its deterministic database-backed confirmation.
6. A brand-new chat recalled the saved fact.
7. Railway was rebuilt again.
8. Another new chat recalled the same fact after the rebuild.

PR #12 is complete and production-verified.

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
- Kept automatic off-volume backup and tested recovery honestly incomplete

## Completed milestone — PR #14 read-only memory review UI

Merged into `main` on July 31, 2026.

Squash merge commit:

```text
78806da6c9d4ba33f956b65b17c3dbb549031f83
```

Implemented:

- Protected `GET /memory` browser route
- Memories navigation from chat
- Read-only memory cards with scope, project, source, and creation date
- All-memory, global-only, and exact-project filters
- Safe rendering through `textContent`
- Stale-request generation guard
- Responsive mobile and desktop layouts
- Auth, route, asset, and read-only regression tests

Production verification:

- Railway deployed the merged commit successfully.
- The memory page loaded behind private authentication.
- Global and Cars-project memories displayed correctly.
- All memories, Global only, and Cars filters returned the expected records.
- No edit, archive, restore, or delete controls appeared.
- Chat remained functional.

## Completed pre-migration safety gate

The manual backup and restore checkpoint was completed on August 1, 2026 before migration 2 work began.

Verified:

- WAL-safe online SQLite snapshot from `/data/mootos.db`
- Off-volume private download
- Matching production and downloaded SHA-256
- `PRAGMA integrity_check = ok`
- Schema `1 — initial_schema`
- Five projects, fifteen conversations, fifty-eight messages, and two memories
- Isolated application startup against a separate restore copy
- Health HTTP `200`
- Known conversation and memory reads
- Original backup remained unchanged

The exact non-private verification record is in [`BACKUP_RESTORE_VERIFICATION_2026-08-01.md`](BACKUP_RESTORE_VERIFICATION_2026-08-01.md). Automatic encrypted backups and retention remain future work.

## Current work — UI-selected memory correction

Branch:

```text
feature/memory-correction-v0.1
```

Purpose:

Let Moot select one stored memory, replace it with corrected content, and preserve the old version as history instead of silently overwriting or deleting it.

Implemented on the branch:

- Migration 2 adds shared lifecycle fields for correction and later archival.
- Existing rows migrate safely to active status with `updated_at = created_at`.
- Correction creates a new active memory version and supersedes the selected old version atomically.
- The old content remains available through an ordered correction-history API.
- Normal model context includes only active memories.
- Correction is initiated from the memory review UI with an explicit confirmation step.
- Correction-linked rows are protected from legacy hard deletion.
- No natural-language update command.
- No archive, restore, permanent delete, keyword search, semantic search, or broader redesign.
- Tests and documentation ship in the same PR.

Local verification completed before the draft PR:

- 82 automated tests passed.
- Python compilation and JavaScript syntax checks passed.
- A separate copy of the verified production backup migrated from schema 1 to schema 2 without changing project, conversation, message, or existing-memory counts.
- Correction on the migrated copy produced one active replacement and one superseded prior version.
- SQLite integrity remained `ok`, and the original backup hash remained unchanged.

The branch remains draft and unmerged until GitHub Actions, complete diff review, external read-only review, plain-language review, production migration planning, and Moot's explicit approval are complete.

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

Memory supports deliberate save, cross-chat recall, and production-verified review. Correction is implemented on the current branch but remains unmerged and not production-verified. Archival, keyword retrieval, duplicate handling, and natural-language forget or update remain incomplete.


## Current planning decision

The memory-control sequence remains:

1. Read-only memory review interface
2. UI-selected memory correction with preserved history
3. UI-selected recoverable archive or forget workflow
4. Basic keyword retrieval before embeddings
5. Focused conversation behavior refinement
6. Curated Moot bootstrap profile only after memory controls exist

Correction and forgetting share one memory lifecycle model so the database is not redesigned repeatedly. The migration 2 lifecycle states are:

```text
active
superseded
archived
```

Migration 2 is implemented and documented in ADR-016. It remains proposed until code review, CI, external review, plain-language review, and explicit merge approval are complete.

The manual backup checkpoint documented in [`MANUAL_BACKUP_AND_RESTORE.md`](MANUAL_BACKUP_AND_RESTORE.md) is complete. No private database file, backup, or memory content belongs in GitHub.

Product intent is also clarified: project selection is a focus lens, not a secrecy boundary. Main/no-project chat may use all saved memory. Project chats should prioritize matching-project and global memory while later retrieval work may surface other relevant memories when useful.

## Preserved future ideas

### Model independence

MootOS owns memories, projects, permissions, and operating logic. AI providers remain replaceable engines, with local models as a future direction.

### Reviewable engineering learning

MootOS may record repeated engineering patterns and propose standards for approval. It must not silently rewrite permanent rules.

### Board of directors

A future advisory system may use specialist business, technical, creative, and risk perspectives followed by a synthesizer. It remains advisory and should start small.

## Operating rules

- One focused purpose per branch and PR
- No secrets or private backups in GitHub
- Tests for important behavior
- Documentation updated in the same PR
- Major architecture decisions use ADRs
- One Railway replica while SQLite is live
- Verified backup and restore drill before destructive or schema-changing production work
- Never claim a memory was saved unless the complete storage transaction committed
- Honest reporting of tests, deployments, and uncertainty
- Moot explicitly approves merges and high-risk actions

## Immediate decision

Complete the correction branch, open it as a draft PR, run CI and external review, explain the migration and rollback in plain language, and do not merge until Moot explicitly approves the exact final head.
