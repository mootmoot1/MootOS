# MootOS Current Checkpoint

**Last updated:** July 31, 2026  
**Repository:** `mootmoot1/MootOS`  
**Default branch:** `main`  
**Current release:** Version 0.1 foundation

## Verified production state

MootOS is deployed on Railway and accessible through its private phone-friendly interface.

Verified facts before foundation hardening:

- Railway deploys from `main`.
- FastAPI is online.
- Private password login works.
- OpenAI returns real responses through the backend.
- Conversations, messages, projects, and memories are stored in SQLite.
- Project memories are supplied to the model.
- Railway volume `mootos-volume` is attached at `/data`.
- Production database is `/data/mootos.db`.
- Conversations and memories survived three consecutive deployments on July 31, 2026.
- Railway remains at one replica.

The volume proves normal redeployment persistence. Automatic off-volume backups and tested disaster recovery are not implemented.

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
- Documentation-only runtime impact

## Current work — PR #11 foundation hardening

Branch:

```text
feature/foundation-hardening-v0.1
```

Purpose:

Make the existing single-user SQLite and Railway foundation more predictable and safer without adding product features.

Implemented on the branch:

- Central database path and connection layer in `backend/db.py`
- Consistent connection commit, rollback, and close behavior
- Foreign-key enforcement on every connection
- WAL mode
- `NORMAL` synchronous mode
- Five-second busy and connection timeouts
- Versioned migrations in `backend/migrations.py`
- `schema_migrations` history table
- Existing Version 0.1 database adoption as migration 1
- Required table, column, and message foreign-key verification before migration success
- Refusal to run an older build against a newer unknown schema
- Memory and conversation storage routed through the central layer
- Railway auth fail-closed behavior
- Explicit `MOOTOS_ALLOW_PUBLIC=true` override for intentionally public Railway deployment
- Exact direct dependency pins, including CI lint tooling
- Tests for PRAGMAs, migrations, existing-data preservation, incompatible schemas, foreign keys, newer-schema rejection, concurrent writes, and Railway auth safety
- ADR-015 and complete documentation updates

Not included:

- Natural-language memory commands
- Memory UI changes
- Backup automation
- PostgreSQL
- Multiple replicas
- Model-provider changes
- Interface redesign

## Verification status

Completed:

- Investigated two rejected GitHub write calls; neither changed the repository.
- Reviewed all changed filenames and the critical database, migration, authentication, dependency, CI, and documentation files.
- Added missing `.env.example` documentation for `MOOTOS_ALLOW_PUBLIC`.
- Added the hardening guide and ADR to the documentation index.
- Pinned Flake8 and removed the unpinned CI installation.
- Added schema compatibility verification before migration success.
- Added a regression test proving incompatible legacy schemas roll back without migration history.
- GitHub Actions passed on Python 3.9, 3.10, and 3.11.
- Dependency installation, blocking-error lint, and the full test suite passed in every matrix job.

Still required before merge:

- Plain-language review with Moot
- Explicit merge approval
- Final release-status documentation update and ADR acceptance

Still required after merge:

- Railway startup confirmation
- Login verification
- Pre-hardening conversation and memory verification
- New write verification
- One redeployment persistence check

## Current implementation boundaries

MootOS remains:

- Single user
- Text chat only
- One Railway service and replica
- One SQLite database
- One implemented model provider
- No background queue
- No local model
- No runtime tools
- No multi-agent system
- No natural-language memory commands
- No automatic backups

## Next product milestone

After foundation hardening is reviewed, merged, and verified in Railway:

1. Add explicit natural-language memory commands:
   - “Remember this”
   - “Forget that”
   - “Update that”
2. Add memory review and correction controls.
3. Add simple keyword retrieval before embeddings.
4. Improve behavior for short notes and status statements.
5. Prepare a curated Moot bootstrap profile only after correction controls are safe.

## Preserved future ideas

### Model independence

MootOS owns memories, projects, permissions, and operating logic. AI providers remain replaceable engines, with local models as a future direction.

### Reviewable engineering learning

MootOS may record repeated engineering patterns and propose standards for approval. It must not silently rewrite permanent rules.

### Board of directors

A future advisory system may use specialist business, technical, creative, and risk perspectives followed by a synthesizer. It remains advisory and should start small.

## Operating rules

- One focused purpose per branch and PR
- No secrets in GitHub
- Tests for important behavior
- Documentation updated in the same PR
- Major decisions use ADRs
- One Railway replica while SQLite is live
- Backups before destructive storage changes
- Honest reporting of tests, deployments, and uncertainty
- Moot explicitly approves merges and high-risk actions

## Immediate decision

Review PR #11 in plain language. Do not merge until Moot explicitly approves it.
