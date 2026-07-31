# MootOS Roadmap

**Last reviewed:** July 31, 2026

## Vision

MootOS will be developed in small, stable versions.

Each version should improve one major capability while protecting what already works. The roadmap describes direction, not guaranteed delivery dates.

## Current position

MootOS is in Version 0.1 foundation development.

Merged and working:

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

Current draft milestone:

- Explicit `remember` and `save this` commands that write long-term memory through chat
- Write-before-confirm behavior
- Cross-chat recall from SQLite
- Global and project memory scope
- End-to-end tests proving recall in a brand-new conversation

Immediate priorities after the chat-memory PR is merged and verified:

1. Memory review and correction controls
2. Safe `forget` and `update` commands
3. Basic keyword retrieval
4. Better behavior for notes and status statements
5. Curated Moot bootstrap profile import
6. More distinct interface design

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

## Current chat-memory checkpoint

The current draft PR adds:

- Deterministic command parsing for `remember`, `save this`, and `save to memory`
- SQLite writes before confirmation
- No model-provider call for explicit saves
- `explicit_chat` memory type
- Global memories available across projects
- Project memories isolated from unrelated projects
- Internal action metadata using `mootos` and `memory-command-v1`
- Parser, validation, isolation, and cross-chat recall tests

This checkpoint is complete only after:

- GitHub Actions passes
- The PR is reviewed and approved
- Railway deploys successfully
- A fact is saved through normal chat
- A brand-new chat recalls the fact
- The memory survives another redeploy

## Remaining Version 0.1 work

### Controlled memory management

- Memory review interface
- Memory edit or replacement workflow
- `Forget that ...` command with confirmation
- `Update that ...` command with correction history
- Duplicate and conflict handling
- Basic keyword search
- Clear handling of sensitive memories

### Conversation refinement

- Better handling of notes and status statements
- Less generic default behavior
- Capability honesty
- Clearer uncertainty
- More consistent MootOS identity

### Interface and control refinement

- Memory controls
- Basic settings
- Readable activity logging
- More distinct MootOS visual identity
- Improved navigation without unnecessary frontend complexity

### Backup and recovery

- Consistent SQLite backups
- Encrypted off-volume copies
- Retention rules
- Restore testing
- Clear recovery approval flow

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
- Correction history
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
- Never claim a memory was saved before the database write succeeds.
- Reliability before scale.
- Backups before destructive storage migration.
- Permissions before automation.
- Real internal use before commercial promises.
- Moot approves major changes and remains the final authority.
