# MootOS Roadmap

**Last reviewed:** July 31, 2026

## Vision

MootOS will be developed in small, stable versions.

Each version should improve one major capability while protecting what already works. The roadmap describes direction, not guaranteed delivery dates.

## Current position

MootOS is in Version 0.1 foundation development.

Merged and production-verified:

- Private Railway deployment
- Phone-friendly chat interface
- Persistent conversations
- Project organization
- Persistent SQLite memories and memory APIs
- Relevant memory context in model prompts
- Replaceable model-provider boundary
- OpenAI provider
- Railway volume persistence
- Comprehensive documentation
- Central SQLite connection policy
- Foreign-key enforcement
- WAL mode and busy timeout
- Versioned schema migrations
- Railway auth fail-closed behavior
- Exact dependency pins
- Explicit `remember` and `save` commands through normal chat
- Atomic write-before-confirm memory storage
- Cross-chat recall from SQLite
- Global and project memory scope
- Long-term memory persistence through a Railway rebuild

PR #12 is merged and production-verified. MootOS saved a unique fact through the normal chat interface, recalled it in a brand-new conversation, survived another Railway rebuild, and recalled it again afterward.

## Immediate sequence

Before product work:

1. Record PR #12 production verification in the repository.
2. Document a safe manual backup and restore procedure.
3. Complete a consistent off-volume backup and non-production restore drill before migration 2 reaches production.

Next five product branches:

1. `feature/memory-review-ui-v0.1`
2. `feature/memory-correction-v0.1`
3. `feature/memory-forget-v0.1`
4. `feature/memory-keyword-retrieval-v0.1`
5. `feature/conversation-refinement-v0.1`

Then:

6. `feature/moot-bootstrap-profile-v0.1`

This order follows the control loop:

```text
see → correct → archive → find → converse better → import curated profile
```

Visibility comes before mutation. Correction comes before forgetting. Keyword retrieval comes after memory review and lifecycle controls. Permanent profile import comes only after the user can inspect, correct, archive, and retrieve memories.

---

# Version 0.1 — Reliable Personal Foundation

## Goal

Create a private personal AI that can hold useful ongoing conversations, deliberately remember important information, organize it into projects, and survive normal deployments without losing data.

## Completed foundation

- Mobile-friendly web interface
- Persistent conversation history
- New and reopened conversations
- Project selector and five default projects
- Memory CRUD APIs
- Project and global memory context
- Replaceable model-provider boundary
- OpenAI Responses API provider
- Private password login and signed sessions
- Railway deployment and Home Screen manifest
- Persistent SQLite volume
- Centralized hardened SQLite connections
- Versioned migrations and schema checks
- Automated tests and ADR-based workflow
- Comprehensive documentation baseline
- Explicit chat memory commands
- Atomic memory write and confirmation transaction
- Cross-chat memory recall
- Production persistence through a rebuild

## Verified chat-memory checkpoint

PR #12 delivered and verified:

- Deterministic command parsing for `remember`, `save this`, and `save to memory`
- Rejection of incomplete and punctuation-only content
- SQLite transaction containing the conversation, user message, memory row, and confirmation
- Full rollback after memory or confirmation failure
- No model-provider call for explicit saves
- `explicit_chat` memory type
- Global memories available across projects
- Project memories isolated from unrelated projects
- Internal action metadata using `mootos` and `memory-command-v1`
- Parser, validation, isolation, rollback, and cross-chat recall tests
- GitHub Actions on Python 3.9, 3.10, and 3.11
- Successful Railway deployment
- Save in one chat and recall in a brand-new chat
- Recall again after another Railway rebuild

## Remaining Version 0.1 work

### Memory visibility

First product branch:

```text
feature/memory-review-ui-v0.1
```

Scope:

- Read-only mobile memory list
- Memory content
- Global or project scope
- Memory type or source
- Creation date
- Project filtering

Out of scope for the first branch:

- Editing
- Deleting
- Archiving
- Keyword search
- Pagination redesign
- Full settings redesign

### Controlled memory lifecycle

Correction and forgetting should share one lifecycle model rather than introducing separate incompatible schema changes.

Planned conceptual states:

```text
active
superseded
archived
```

The exact migration design must be reviewed before implementation.

Correction should:

- Be selected from the review interface
- Preserve the old value as history
- Create or mark one current active value
- Exclude superseded values from model context
- Commit atomically
- Be verified in a brand-new conversation

Forgetting should:

- Be selected from the review interface
- Show the exact memory affected
- Require confirmation
- Archive rather than immediately hard-delete
- Exclude archived values from all model context and default lists
- Optionally support restoration

Natural-language `update that` and `forget that` commands remain later thin branches because ambiguous matching is riskier than UI-selected actions.

### Basic keyword retrieval

After review, correction, and archival:

- Tokenize the current request
- Use understandable keyword or `LIKE` matching
- Rank active memories by term matches and recency
- Respect global and project scope
- Merge keyword matches with recent memories
- Cap the final context set
- Add search to the memory review interface when practical

Do not add embeddings, a vector database, or FTS5 until the simple approach proves inadequate.

### Conversation refinement

- Better handling of notes and status statements
- Less generic default behavior
- Fewer reflexive questions
- Capability honesty
- Clearer uncertainty
- More consistent MootOS identity
- Realistic conversation regression cases

Normal notes must not silently become permanent memories.

### Curated Moot bootstrap profile

The profile belongs only after memory review, correction, archival, and retrieval controls exist.

It should contain:

- Selected high-confidence facts
- Useful preferences
- Important ongoing context
- Clear project scope
- User-reviewable entries

It must not be a raw dump of prior conversations.

### Interface and control refinement

- Basic settings
- Readable activity logging
- More distinct MootOS visual identity
- Improved navigation without unnecessary frontend complexity

### Backup and recovery

Current direction:

- Manual consistent SQLite backup procedure
- Off-volume private copy
- SHA-256 and integrity verification
- Non-production restore drill before migration 2 reaches production
- Later automated encrypted backups
- Retention rules
- Tested production recovery flow

See [`docs/MANUAL_BACKUP_AND_RESTORE.md`](docs/MANUAL_BACKUP_AND_RESTORE.md).

## Version 0.1 completion rule

Version 0.1 is complete when Moot can deliberately save, find, review, correct, and remove important memories through the normal interface while continuing to use the system through deployments without losing data or depending on undocumented steps.

---

# Version 0.2 — Project Intelligence

## Goal

Turn projects from simple labels into useful workspaces.

Possible features:

- Project dashboards
- Goals and tasks
- Deadlines and notes
- Decisions and status
- Conversation summaries
- Related files and repositories
- People connected to a project
- Cross-project links

Project workspaces should aggregate existing conversations and memories instead of duplicating them.

---

# Version 0.3 — Memory Intelligence

## Goal

Improve what MootOS remembers, why it remembers it, and how it finds the right information.

Possible features:

- Semantic search after keyword search is proven
- Memory confidence and source tracking
- Richer correction history
- Related memories
- Timeline view
- Automatic conversation summaries
- Expiring temporary memories
- Sensitive-memory controls
- Memory import and export

A curated Moot bootstrap profile belongs after review and correction controls exist. It should contain high-confidence useful facts, not a raw dump of every prior conversation.

---

# Version 0.4 — Controlled Tool System

## Goal

Allow MootOS to interact with outside systems through explicit permissions.

Possible read-first integrations:

- GitHub
- Files and documents
- Calendar
- Contacts
- Web research

Possible later write actions:

- Drafting and sending approved messages
- Creating approved calendar events
- Preparing code changes
- Publishing approved content

Every tool must document what it reads, what leaves the system, what it changes, what requires approval, what gets logged, and how failure and rollback work.

---

# Version 0.5 — Coding and Engineering Intelligence

## Goal

Allow MootOS to help build itself while keeping Moot in control.

Possible features:

- Repository understanding
- Feature planning
- Code generation and bug fixing
- Test generation
- Pull request preparation
- Documentation updates
- Security and performance review roles
- Engineering decision history

MootOS may propose repeated engineering patterns as standards, but it must not silently rewrite permanent rules.

---

# Version 0.6 — Content and Studio Foundations

## Goal

Prove one revenue-producing workflow based on Moot's real work without distracting from the core system.

Possible content features:

- Organize video ideas and media references
- Generate approved content angles and repurposing plans
- Track drafts and publishing status
- Learn approved brand and tone guidelines
- Connect content to business goals

Possible studio foundations:

- Studio knowledge base
- Client and session information
- Booking workflow research
- Staff notifications
- Frequently asked question assistant
- Operational dashboard

The first commercial feature should solve a real problem in Moot's own studio before being sold to other studios.

---

# Version 0.7 — Voice

## Goal

Add natural spoken interaction using the same memory, permission, and project systems.

Possible features:

- Speech-to-text and text-to-speech
- Interruption handling
- Voice settings and memory controls
- Mobile microphone support
- Clear indication when audio is processed or stored

---

# Version 0.8 — Vision and Media Understanding

## Goal

Understand images, screenshots, documents, and selected media.

Possible features:

- Image and screenshot analysis
- Document extraction
- Video transcript and scene analysis
- Visual memory controls
- Content review

Private media must not be sent to outside providers without clear approval and documentation.

---

# Version 0.9 — Automation and Notifications

## Goal

Reduce repetitive work through controlled, observable automation.

Possible features:

- Scheduled tasks and follow-ups
- Conditional checks
- Recurring reports
- Notifications
- Approval-based workflows
- Background job system

Automation should be added only after permissions, logging, and failure handling exist.

---

# Version 1.0 — Personal AI Operating System

## Goal

Deliver a stable, expandable system that Moot uses as a real operating layer across projects and devices.

Expected platform capabilities:

- Natural conversation
- Controlled long-term memory
- Project intelligence
- Tool ecosystem
- Coding assistance
- Voice and vision
- Secure permissions
- Reliable backups
- Replaceable model providers
- Local AI support where practical
- Understandable logs and documentation

Version 1.0 is a stable platform, not the end of development.

---

# Long-term model independence

MootOS should own its memories, projects, permissions, logs, configuration, operating rules, tool history, and engineering knowledge.

AI providers remain replaceable engines. Future routing may consider privacy, cost, speed, task type, internet availability, local hardware, and user preference.

Local AI is strategic, but it should not block useful development before suitable hardware is available.

---

# Future advisory system — Board of Directors

A future feature may use specialist business, technical, creative, operations, and risk perspectives followed by a synthesizer.

It should show recommendations, disagreements, assumptions, risks, missing information, and one final recommendation while leaving authority with Moot.

The first version should be small, not a swarm that repeats itself and wastes API credits.

---

# Database scaling direction

SQLite remains live while MootOS is single-user and runs one replica.

Before commercial multi-user deployment, evaluate PostgreSQL for multiple users, multiple replicas, concurrent writers, managed recovery, stronger server-side controls, and commercial reliability requirements.

Do not dual-write every record to unrelated databases merely for the appearance of redundancy. Prefer one source of truth, verified backups, and a tested migration path.

---

# Product and revenue direction

The strongest product direction is:

1. Use MootOS in Moot's real life and work.
2. Identify a repeated, expensive problem.
3. Build the smallest reliable workflow that solves it.
4. Prove it internally.
5. Document the result.
6. Package it only after it works.

Possible commercial paths include a studio operating assistant, content-production support, implementation services, or a focused software product.

---

# Roadmap rules

- Planned features must not be documented as implemented.
- One focused branch and PR at a time.
- Tests and documentation are part of completion.
- Never claim a memory was saved before the complete database transaction succeeds.
- Reliability before scale.
- Verified backup and restore drill before destructive storage migration.
- Permissions before automation.
- Real internal use before commercial promises.
- Moot approves major changes and remains the final authority.
