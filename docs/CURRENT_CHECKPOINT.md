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
- Conversations and memories survived three consecutive deployments before foundation hardening.
- After PR #11 deployed, Moot verified that conversation history still survived the update and reboot cycle.
- The hardened SQLite and migration startup completed successfully in production.

Automatic off-volume backups and tested disaster recovery are not implemented.

## Important behavior discovered after PR #11

Moot tested long-term memory through the normal chat interface.

Observed behavior:

1. Moot told the assistant to save a fact.
2. The assistant said it saved the fact.
3. The fact appeared available in the same conversation because it remained in message history.
4. A brand-new conversation did not know the fact.
5. The memory API and database existed, but ordinary chat was not connected to memory creation.

Conclusion:

The persistence system was working. The missing feature was a deterministic chat-to-memory write path. The model could claim it saved something without any SQLite memory row being created.

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

## Current work — PR #12 chat memory commands

Branch:

```text
feature/chat-memory-commands-v0.1
```

Purpose:

Connect explicit natural-language save commands to the existing persistent `memories` table.

Implemented on the draft branch:

- Deterministic parser in `backend/memory_commands.py`
- Supported command forms beginning with `remember`, `save this`, or `save to memory`
- Ordinary questions such as `Do you remember ...?` remain normal model requests
- Database write occurs before confirmation
- Save commands bypass OpenAI and do not spend model credits
- Saved chat memories use memory type `explicit_chat`
- Internal confirmation messages record provider `mootos` and model `memory-command-v1`
- Unassigned memories are global and available in project chats
- Project memories remain isolated from unrelated projects
- Existing 10,000-character memory limit is enforced
- End-to-end test saves in one chat and recalls in a brand-new conversation
- Parser, project-scope, model-routing, and validation tests

Not included:

- Natural-language forget
- Natural-language update or correction
- Memory review UI
- Duplicate detection
- Keyword or semantic search
- Automatic profile import
- Schema changes
- Frontend redesign

## Verification status for PR #12

Completed in code and tests on the branch:

- Explicit save commands write to SQLite before confirmation.
- A save command does not call the model provider.
- The saved memory is supplied to a separate new conversation.
- Global memories are available across projects.
- Project memories do not leak into unrelated projects.
- Incomplete commands and ordinary questions are not misclassified.
- Oversized memories are rejected before a conversation is created.

Still required before merge:

- GitHub Actions on Python 3.9, 3.10, and 3.11
- Final diff review
- Plain-language review with Moot
- Explicit merge approval

Still required after merge:

- Railway startup confirmation
- Login verification
- Save a unique fact through normal chat
- Start a brand-new chat and recall the fact
- Verify the row through the memory API or interface when available
- Redeploy once and confirm the saved memory remains

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
- No automatic backups

After PR #12, explicit save commands exist, but forget, update, correction, review, and search remain incomplete.

## Next product milestones

After PR #12 is reviewed, merged, and verified:

1. Add safe memory review and correction controls.
2. Add explicit forget and update workflows with confirmation.
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
- Major architecture decisions use ADRs
- One Railway replica while SQLite is live
- Backups before destructive storage changes
- Never claim a memory was saved unless the database write succeeded
- Honest reporting of tests, deployments, and uncertainty
- Moot explicitly approves merges and high-risk actions

## Immediate decision

Finish PR #12 documentation and automated review. Do not merge until checks pass and Moot explicitly approves it.
