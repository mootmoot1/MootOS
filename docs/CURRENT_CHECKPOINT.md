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
- UI-selected recoverable forgetting works in production.
- An archived memory disappeared from ordinary recall and appeared in Archived.
- Restoring the exact row returned it to ordinary recall.
- Corrected and restored active values survived later Railway rebuilds.

Projects are focus lenses, not permanent memory walls. A no-project conversation can use all active saved memory. The current retrieval branch ranks matching-project memory first, global memory next, and relevant other-project memory afterward while preventing unrelated other-project fallback.

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

Production verification:

- Railway deployed migration 2 successfully.
- Existing records remained available.
- A selected memory was corrected through the UI.
- The replacement appeared as the active corrected version.
- The prior version remained preserved as superseded history.
- A fresh no-project chat recalled only the corrected active value.
- The corrected value survived another Railway rebuild.

See [`MEMORY_CORRECTION_PRODUCTION_VERIFICATION_2026-08-01.md`](MEMORY_CORRECTION_PRODUCTION_VERIFICATION_2026-08-01.md).

### PR #16 — Recoverable memory forget and restore

Merged into `main` on August 1, 2026.

Squash merge commit:

```text
efd970336ed03535c2704bba2c8dc5655aa63b10
```

Implemented:

- Reused migration 2; no new schema migration
- `POST /memories/{id}/archive`
- `POST /memories/{id}/restore`
- `GET /memories?status=active|archived`
- Active and Archived views on the protected Memory page
- Exact selected-memory Forget and Restore confirmation
- Archived rows excluded from model context and normal recall
- Correction chains preserved through archive and restore
- Archived rows protected from hard deletion
- Serialized lifecycle writes with `BEGIN IMMEDIATE`
- Conflict, rollback, and competing-request coverage
- No browser memory `DELETE`, `PATCH`, or `PUT`
- ADR-017 and synchronized documentation

Production verification:

- Railway deployed successfully without a schema change.
- Existing active memories remained visible.
- One selected memory moved to Archived.
- A fresh no-project chat no longer recalled the archived value.
- The exact row appeared in Archived with Restore available.
- Restoring the row returned it to active recall.
- A fresh chat recalled the restored value again.
- The restored state survived another Railway rebuild.

See [`MEMORY_FORGET_RESTORE_PRODUCTION_VERIFICATION_2026-08-01.md`](MEMORY_FORGET_RESTORE_PRODUCTION_VERIFICATION_2026-08-01.md).

## Current work — understandable keyword memory retrieval

Branch:

```text
feature/memory-keyword-retrieval-v0.1
```

Draft PR:

```text
#17 — feat: add understandable keyword memory retrieval
```

Purpose:

Find useful active memories using deterministic keywords while treating projects as focus lenses rather than hard walls, and add protected keyword search to the Memory page.

Implemented on the branch:

- New `backend/memory_retrieval.py`
- Pure-Python case, punctuation, stop-word, and limited plural normalization
- Matches memory content, project name, and memory type/source
- Matching-project matches first
- Global matches second
- Relevant other-project matches third
- Project fallback limited to matching-project and global active memory
- No-project matches and fallback across all active memory
- Maximum 20 context memories
- Absolute exclusion of archived and superseded rows from model context
- Optional `q` parameter on `GET /memories`, maximum 500 characters
- Active and Archived browser search
- Search and Clear controls with mobile layout
- Search-aware loading, summary, empty, and error states
- Stored values and search labels rendered through `textContent`
- No schema migration, embeddings, vector database, FTS5, or extra model-provider call
- ADR-018 and synchronized API, roadmap, requirements, and README documentation

Verification so far:

- Python and JavaScript syntax checks passed locally.
- Retrieval smoke tests confirmed project → global → relevant other-project ordering.
- The first GitHub Actions run collected 103 tests.
- 102 tests passed.
- One regression failed because the updated safety-note heading removed the exact established phrase `Forget is recoverable`.
- The wording was restored without removing the new search explanation.

Still required before merge:

- GitHub Actions on the exact final head
- Complete final diff review
- External read-only review
- Plain-language review with Moot
- Moot's explicit approval for the exact PR

Still required after merge:

- Railway reaches online status
- Login remains functional
- Existing active and archived memories remain intact
- Memory-page search finds content, project-name, and corrected active values
- Archived search finds archived values without exposing them in Active
- A project chat recalls a clearly relevant memory from another project
- An unrelated other-project memory is not used as fallback
- No-project chat still recalls relevant active memory
- Retrieval and search behavior survive a Railway rebuild

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

## Explicitly out of scope for PR #17

- Embeddings or vector search
- SQLite FTS5 or migration 3
- Synonym or typo correction
- Model-based memory selection
- Automatic memory extraction
- Natural-language correction or forget
- Duplicate detection
- Pagination redesign
- Full browser history viewer

## Locked sequence

1. Memory review — complete
2. Memory correction — complete and production-verified
3. Recoverable forget/archive — complete and production-verified
4. Keyword retrieval before embeddings — current
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

Finish exact-head CI and internal review for PR #17, then request external read-only review. Do not merge until Moot explicitly approves the reviewed exact head.
