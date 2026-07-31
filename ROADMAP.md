# MootOS Roadmap

**Last reviewed:** July 31, 2026

## Vision

MootOS will be developed in small, stable versions.

Each version should improve one major capability while protecting everything that already works. The goal is steady progress, not collecting features faster than they can be understood, tested, documented, and controlled.

The roadmap describes direction, not guaranteed delivery dates.

## Current position

MootOS is in Version 0.1 foundation development.

Already working:

- Private Railway deployment
- Phone-friendly chat interface
- Persistent conversations
- Project organization
- Basic persistent memories
- Relevant memory context in model prompts
- Replaceable model-provider boundary
- OpenAI provider
- Persistent Railway volume verified across three deployments

Immediate priorities:

1. Comprehensive documentation
2. Database and production foundation hardening
3. Natural-language memory commands
4. Memory review, correction, and keyword retrieval
5. Better chat behavior and a more distinct interface

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

## Remaining Version 0.1 work

### Foundation hardening

- Central SQLite connection configuration
- Foreign-key enforcement
- WAL mode and busy timeout
- Versioned schema migrations
- Concurrency and migration tests
- Production auth fail-closed behavior
- Pinned production dependency versions
- Backup and restore design

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

### Interface refinement

- Memory controls
- Basic settings
- More distinct MootOS visual identity
- Improved navigation without unnecessary frontend complexity

## Version 0.1 completion rule

Version 0.1 is complete when Moot can deliberately control memory through the normal interface and use the system daily without undocumented setup, data-loss risk, or misleading capability claims.

---

# Version 0.2 — Project Intelligence

## Goal

Turn projects from simple labels into useful workspaces.

Possible features:

- Project dashboards
- Goals
- Tasks
- Deadlines
- Notes
- Decisions
- Project status
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

- Semantic memory search
- Memory confidence
- Memory source tracking
- Correction history
- Related memories
- Timeline view
- Automatic conversation summaries
- Expiring temporary memories
- Sensitive-memory controls
- Memory import and export

Simple keyword search should be proven before adding embeddings or a vector database.

---

# Version 0.4 — Controlled Tool System

## Goal

Allow MootOS to interact with outside systems through explicit permissions.

Possible read-first integrations:

- GitHub
- Files
- Calendar
- Contacts
- Web research
- Documents

Possible later write actions:

- Drafting and sending approved messages
- Creating approved calendar events
- Preparing code changes
- Publishing approved content

Every tool must document:

- What it reads
- What it sends outside the system
- What it changes
- What requires approval
- What gets logged
- How failure and rollback work

---

# Version 0.5 — Coding and Engineering Intelligence

## Goal

Allow MootOS to help build itself while keeping Moot in control.

Possible features:

- Repository understanding
- Feature planning
- Code generation
- Bug fixing
- Test generation
- Pull request preparation
- Documentation updates
- Security and performance review roles
- Engineering decision history

## Reviewable engineering learning

MootOS may observe repeated engineering patterns and propose standards such as:

> “We always add a migration test when changing the schema. Should this become a permanent project rule?”

The system should not silently rewrite its own engineering rules. Proposed learning must remain visible, explainable, and subject to Moot's approval.

---

# Version 0.6 — Content and Studio Foundations

## Goal

Prove one revenue-producing workflow based on Moot's real work without distracting from studio time or existing content creation.

Possible content features:

- Upload and organize video ideas or media references
- Generate content angles and repurposing plans
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

Add natural spoken interaction.

Possible features:

- Speech-to-text
- Text-to-speech
- Voice settings
- Interruption handling
- Voice memory controls
- Mobile microphone support
- Clear indication when audio is being processed or stored

Voice should use the same memory, permission, and project systems rather than becoming a separate assistant.

---

# Version 0.8 — Vision and Media Understanding

## Goal

Allow MootOS to understand images, screenshots, documents, and selected media.

Possible features:

- Image understanding
- Screenshot analysis
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

- Scheduled tasks
- Follow-ups
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

Version 1.0 represents a stable platform, not the end of development.

---

# Long-term model independence

MootOS should own:

- Memories
- Projects
- Permissions
- Logs
- Configuration
- Operating rules
- Tool history
- Engineering knowledge

AI providers should remain replaceable engines.

Future routing may consider:

- Privacy
- Cost
- Speed
- Task type
- Internet availability
- Local hardware
- User preference

Local AI is a strategic direction, but it should not block useful development before suitable hardware is available.

---

# Future advisory system — Board of Directors

A future MootOS feature may use multiple specialist AI roles to evaluate important decisions.

Possible roles:

- Business and revenue director
- Technical director
- Creative director
- Risk and security director
- Operations director
- Final synthesizer or chairman

A board response should show:

- Each specialist's recommendation
- Important disagreement
- Risks and assumptions
- Missing information
- One synthesized recommendation
- The decision that still belongs to Moot

The first version should be small, likely three specialists and one synthesizer. It should not create a swarm of agents that repeat each other and waste API credits.

This feature is advisory, not autonomous authority.

---

# Database scaling direction

SQLite remains the current live database while MootOS is single-user and runs one replica.

Before commercial multi-user deployment, evaluate PostgreSQL for:

- Multiple users
- Multiple application replicas
- Concurrent writers
- Managed backups
- Stronger server-side controls
- Commercial reliability requirements

Do not dual-write every record to unrelated databases merely for appearance of redundancy. Prefer one source of truth, verified backups, and a tested migration path.

---

# Product and revenue direction

The long-term business goal is not “add AI to everything.”

The strongest product direction is:

1. Use MootOS in Moot's real life and work.
2. Identify a repeated, expensive problem.
3. Build the smallest reliable workflow that solves it.
4. Prove it in the studio or content workflow.
5. Document the result.
6. Package it for similar customers only after it works internally.

Possible commercial paths include a studio operating assistant, content-production support, implementation services, or a focused software product. The right path should emerge from demonstrated use rather than forcing monetization before the core system is reliable.

---

# Roadmap rules

- Planned features must not be documented as implemented.
- One focused branch and PR at a time.
- Reliability before scale.
- Backups before major storage migration.
- Permissions before automation.
- Real internal use before commercial promises.
- Moot approves major changes and remains the final authority.
