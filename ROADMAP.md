# MootOS Roadmap

**Last reviewed:** July 31, 2026

## Vision

MootOS will be developed in small, stable versions.

Each version should improve one major capability while protecting what already works. The roadmap describes direction, not guaranteed delivery dates.

## Current position

MootOS is in Version 0.1 foundation development.

Already merged and working:

- Private Railway deployment
- Phone-friendly chat interface
- Persistent conversations
- Project organization
- Basic persistent memories
- Relevant memory context in model prompts
- Replaceable model-provider boundary
- OpenAI provider
- Railway volume persistence verified across three deployments
- Comprehensive repository and operations documentation

Implemented on the current hardening branch, pending review and production verification:

- Central SQLite connection policy
- Foreign-key enforcement
- WAL mode and five-second busy timeout
- Versioned schema migrations
- Existing database adoption
- Concurrent-write and migration tests
- Railway auth fail-closed behavior
- Exact direct dependency pins

Immediate priorities after hardening is merged and verified:

1. Natural-language memory commands
2. Memory review, correction, and keyword retrieval
3. Better chat behavior for notes and status statements
4. Curated Moot bootstrap profile import
5. A more distinct interface without unnecessary complexity

---

# Version 0.1 — Reliable Personal Foundation

## Goal

Create a private personal AI that can hold useful ongoing conversations, deliberately remember important information, organize it into projects, and survive normal deployments without losing data.

## Completed foundation

- Mobile-friendly web interface
- Persistent conversation history
- New and reopened conversations
- Project selector
- Five default projects
- Basic memory CRUD APIs
- Project memory supplied to the model
- Replaceable model-provider boundary
- OpenAI Responses API provider
- Private password login
- Signed HTTP-only sessions
- Railway deployment
- Installable phone web-app manifest
- Persistent SQLite volume
- Automated tests and ADR-based development workflow
- Comprehensive documentation baseline

## Foundation hardening checkpoint

The current hardening branch adds:

- One database connection layer
- Consistent commit, rollback, and close behavior
- Foreign-key enforcement
- WAL mode
- `NORMAL` synchronous mode
- Five-second connection and busy timeouts
- Numbered migration history
- Refusal to use a newer unknown schema
- Railway startup that is private by default
- Exact direct dependency pins

This checkpoint is not considered complete until GitHub Actions pass, the PR is reviewed and approved, Railway starts successfully, and pre-existing data is manually verified.

Automatic backups and restore testing remain separate work.

## Remaining Version 0.1 work

### Natural memory management

- “Remember this”
- “Forget that”
- “Update that”
- Memory review interface
- Memory correction workflow
- Basic keyword search
- Duplicate and conflict handling

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

Version 0.1 is complete when Moot can deliberately control memory through the normal interface and use the system daily without undocumented setup, avoidable data-loss risk, or misleading capability claims.

---

# Version 0.2 — Project Intelligence

## Goal

Turn projects from simple labels into useful workspaces.

Possible features:

- Project dashboards
- Goals and tasks
- Deadlines and notes
- Decisions and project status
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

- Semantic memory search after keyword search is proven
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

## Reviewable engineering learning

MootOS may observe repeated patterns and propose standards, for example:

> “We always add a migration test when changing the schema. Should this become a permanent project rule?”

It should not silently rewrite its own engineering rules. Proposed learning must remain visible, explainable, and subject to Moot's approval.

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

A future MootOS feature may use specialist AI roles to evaluate important decisions.

Possible roles:

- Business and revenue director
- Technical director
- Creative director
- Risk and security director
- Operations director
- Final synthesizer or chairman

A board response should show each recommendation, important disagreement, risks, assumptions, missing information, one synthesized recommendation, and the decision that still belongs to Moot.

The first version should be small—likely three specialists and one synthesizer—not a swarm that repeats itself and wastes API credits. It remains advisory, not autonomous authority.

---

# Database scaling direction

SQLite remains the live database while MootOS is single-user and runs one replica.

Before commercial multi-user deployment, evaluate PostgreSQL for multiple users, multiple application replicas, concurrent writers, managed recovery, stronger server-side controls, and commercial reliability requirements.

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
- Reliability before scale.
- Backups before destructive storage migration.
- Permissions before automation.
- Real internal use before commercial promises.
- Moot approves major changes and remains the final authority.
