# MootOS Current Checkpoint

**Last updated:** July 31, 2026  
**Repository:** `mootmoot1/MootOS`  
**Default branch:** `main`  
**Current release:** Version 0.1 foundation

## Verified operating state

MootOS is deployed on Railway and accessible through its private phone-friendly web interface.

Verified production facts:

- Railway deploys from `main`.
- The FastAPI service is online.
- Password login protects the application when production auth variables are configured.
- The browser receives a signed HTTP-only session cookie after login.
- The mobile chat interface works from the Railway domain.
- The OpenAI provider returns real responses through the backend.
- Conversations and messages are stored in SQLite.
- Project memories are stored in SQLite and supplied to the model.
- The Railway volume `mootos-volume` is attached at `/data`.
- The production database resolves to `/data/mootos.db`.
- Saved conversations and memories survived three consecutive Railway deployments on July 31, 2026.
- The service remains limited to one Railway replica while SQLite is in use.

The volume test proves persistence across normal deployments. Automatic off-volume backups and tested disaster recovery are not implemented yet.

## GitHub working agreement

ChatGPT is connected to the repository through the GitHub connector.

Verified repository capabilities include:

- Read repository files
- Read pull requests and issues
- Create branches
- Create and update files
- Prepare commits
- Open pull requests
- Review GitHub Actions results

Operating rule:

- AI coding agents may prepare work.
- Moot receives a plain-language explanation.
- Major changes are not merged without Moot's explicit approval.

## Completed milestones

### PR #2 — Persistent SQLite memory

Implemented:

- Persistent memory storage
- Create, list, retrieve, filter, and delete memory endpoints
- UUID memory IDs
- UTC timestamps
- Validation and missing-record behavior

### PR #3 — Minimal project system

Implemented:

- Five default projects: MootOS, Studio, Social Media, Cars, and Personal
- Project creation and listing
- Project validation
- Case-insensitive duplicate protection
- Project-filtered memories
- ADR-011

### PR #5 — Conversation engine and model-provider boundary

Implemented:

- Persistent conversations and messages
- Conversation and chat endpoints
- Recent conversation history supplied to the model
- Relevant memories supplied to the model
- Replaceable provider protocol
- OpenAI Responses API provider
- Provider and model metadata stored with assistant responses
- Fake provider tests that avoid spending API credits
- ADR-012

### PR #7 — Mobile-friendly chat interface

Implemented and manually verified:

- Message bubbles
- Text composer
- New Chat control
- Project selector
- Saved conversation history
- Reopening old conversations
- Loading and readable error states
- Responsive phone and desktop layout
- Automatic conversation-ID handling
- Project-memory recall through the normal interface
- Automated interface tests
- ADR-013

### PR #9 — Secure Railway phone deployment

Implemented and verified:

- Railway config-as-code
- Uvicorn bound to Railway's `PORT`
- Public `/health` check
- Password login
- Signed 30-day HTTP-only sessions
- Secure cookies on Railway
- Protected application and API routes
- Logout controls
- Installable web-app manifest
- Railway volume path support
- Deployment and authentication tests
- Phone deployment checklist
- ADR-014

Production setup completed:

- Repository connected to Railway
- Required variables configured
- Public Railway domain generated
- Volume attached at `/data`
- Login and chat verified
- Persistence verified across three deployments

## Current documentation work

Branch:

```text
docs/comprehensive-documentation-v0.1
```

Purpose:

- Replace the minimal README with a complete project guide
- Separate current implementation from future vision
- Document the API
- Document database and persistence rules
- Add an operations runbook
- Add a documentation-maintenance policy
- Update deployment, roadmap, architecture, and contribution guidance

This branch is documentation-only. It must not change application runtime behavior.

## Current implementation boundaries

MootOS Version 0.1 is currently:

- Single user
- Text chat only
- One Railway service
- One Railway replica
- One SQLite database
- One implemented model provider
- No background task queue
- No local model
- No tool integrations
- No multi-agent system
- No natural-language memory commands
- No automated database backups
- No schema migration runner

These limits are documented so planned features are not confused with existing behavior.

## Next engineering milestone

After the documentation PR is reviewed and merged, prepare a focused foundation-hardening PR.

Recommended scope:

- Centralize SQLite connection configuration
- Enable foreign-key enforcement
- Enable WAL mode
- Add a deliberate busy timeout
- Add a lightweight versioned migration runner
- Add concurrency and migration tests
- Make production authentication fail closed when required variables are missing
- Pin tested production dependency versions

Do not mix natural-language memory features into the hardening PR.

## Following product milestone

After foundation hardening:

- Add natural-language memory commands:
  - “Remember this”
  - “Forget that”
  - “Update that”
- Add memory review and correction controls
- Improve retrieval with simple keyword search before considering embeddings
- Improve chat behavior so short statements are treated as notes or updates rather than automatically expanded into plans
- Refine the interface without copying another product's identity

## Preserved future ideas

The following ideas remain part of the long-term plan but are not immediate build targets:

### Model independence

MootOS should own its memories, projects, permissions, and operating logic while treating AI providers as replaceable engines. Future providers may include additional cloud models and local models.

### Reviewable engineering learning

MootOS may record what changed, why it changed, which patterns repeatedly worked, and propose new engineering standards for Moot's approval. It should not silently rewrite its own permanent rules.

### Board of directors

A future advisory system may use multiple specialist AI roles, such as business, technical, creative, and risk reviewers, followed by a synthesizer that presents one recommendation, disagreements, risks, and assumptions.

This system should begin small, remain reviewable, and avoid wasting API credits on agents that merely agree with each other.

## Operating rules

- One focused purpose per branch and PR
- No secrets committed to GitHub
- Documentation updated with behavior changes
- Tests required for important behavior changes
- Major architecture changes require an ADR
- Keep Railway at one replica while SQLite is the live database
- Back up data before storage migration
- Never claim an action, test, deployment, or backup succeeded without verification
- Moot remains the final authority over merges and high-risk actions

## Immediate decision

Finish and review the comprehensive documentation PR first.

Then harden the foundation before expanding memory behavior or adding major features.
