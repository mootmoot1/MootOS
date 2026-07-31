# MootOS Current Checkpoint

**Last updated:** July 31, 2026  
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

This proves that the normal chat interface writes durable memory to SQLite and that the Railway volume preserves that memory through deployment rebuilds.

Automatic off-volume backups, retention, and tested disaster recovery are not implemented.

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

Memory currently supports deliberate save and cross-chat recall. Memory review, correction, archival, keyword retrieval, duplicate handling, and natural-language forget or update are incomplete.

## Current planning decision

The next memory-control sequence is:

1. Read-only memory review interface
2. UI-selected memory correction with preserved history
3. UI-selected recoverable archive or forget workflow
4. Basic keyword retrieval before embeddings
5. Focused conversation behavior refinement
6. Curated Moot bootstrap profile only after memory controls exist

Correction and forgetting should share one memory lifecycle model so the database is not redesigned repeatedly. The planned lifecycle states are conceptually:

```text
active
superseded
archived
```

The exact migration design must be reviewed before implementation.

## Current documentation branch

Branch:

```text
docs/pr12-production-verification
```

Purpose:

- Record PR #12 as merged and production-verified
- Remove stale draft and pending language
- Record the next agreed product sequence
- Add a manual SQLite backup and restore procedure before migration 2

The procedure is documented in [`MANUAL_BACKUP_AND_RESTORE.md`](MANUAL_BACKUP_AND_RESTORE.md).

Documentation does not equal a verified backup. Before migration 2 reaches production, MootOS still needs:

- A consistent SQLite snapshot
- A matching off-volume copy
- Recorded integrity and SHA-256 verification
- A non-production restore drill

No private database file, backup, or memory content belongs in GitHub.

## Next product branch

After this documentation PR is reviewed and merged:

```text
feature/memory-review-ui-v0.1
```

Planned first scope:

- Read-only memory list on mobile
- Memory content
- Global or project scope
- Memory type or source
- Creation date
- Project filtering
- No editing, deletion, correction, search, or redesign in the first branch

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

Review and merge the production-verification documentation branch. Then build the read-only memory review interface as the next focused product PR.