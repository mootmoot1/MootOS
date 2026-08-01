# MootOS

MootOS is Moot's private, mobile-friendly personal AI foundation.

Version 0.1 provides a working chat interface, persistent conversations, explicit long-term-memory saves through normal chat, production-verified memory review and correction, and a current feature branch for recoverable forgetting and restoration. It also includes project-focused context, a replaceable model-provider boundary, private password access, and hardened persistent SQLite storage on Railway.

MootOS is built in small, reviewable steps. The goal is a reliable system that Moot controls and can expand without rebuilding the foundation.

## Current status

**Version:** `0.1.0`  
**Primary branch:** `main`  
**Current feature branch:** `feature/memory-forget-v0.1`  
**Deployment:** Railway, one service and one replica  
**Production database:** SQLite on a Railway volume mounted at `/data`  
**Current schema:** `2 — memory_lifecycle`  
**Current model provider:** OpenAI through a replaceable provider interface

See [`docs/CURRENT_CHECKPOINT.md`](docs/CURRENT_CHECKPOINT.md) for the latest verified project state.

## What works today

Production-verified on `main`:

- Private password login for the deployed application
- Railway startup that fails closed when private auth variables are missing
- Signed, HTTP-only browser sessions
- Mobile-friendly chat interface
- Starting and reopening persistent conversations
- Conversation history surviving Railway deployments
- Five default projects: MootOS, Studio, Social Media, Cars, and Personal
- Memory create, list, retrieve, filter, and legacy delete APIs
- Explicit chat commands beginning with `remember`, `save this`, or `save to memory`
- Database-backed confirmation only after a memory write succeeds
- Cross-chat recall from the `memories` table
- Global memories available across project chats
- Main/no-project chat can use all active saved memory
- Project chats currently use active global plus matching-project memory
- Protected memory review at `/memory`
- All-memory, global-only, and exact-project memory filters
- Memory content, scope, project, source, and creation date display
- UI-selected correction with preserved history
- Superseded values excluded from normal recall
- Corrected active value surviving another Railway rebuild
- Relevant active memory context supplied to the model
- Replaceable model-provider boundary
- OpenAI Responses API integration
- Provider and model metadata stored with assistant messages
- Installable phone Home Screen manifest
- Public minimal Railway health check
- Persistent production data through an attached Railway volume
- Centralized SQLite connection configuration
- Foreign-key enforcement, WAL mode, `NORMAL` synchronous mode, and busy timeout
- Numbered schema migrations and schema compatibility checks
- Exact direct-dependency pins
- Manual off-volume backup and isolated restore verification
- Automated tests for memory commands, cross-chat recall, database hardening, migrations, auth, conversations, interface behavior, and deployment configuration

Implemented on the current feature branch:

- Active and Archived memory views
- UI-selected **Forget** with exact confirmation
- UI-selected **Restore** with exact confirmation
- Archived-memory exclusion from normal lists and model context
- Correction-history preservation through archive and restore
- Archived-memory protection from permanent deletion

## Explicit long-term memory through chat

Use direct wording at the beginning of a message:

```text
Remember that my favorite tea is jasmine.
Save this to memory: I prefer plain explanations.
Save to long-term memory: Studio block sessions cost $50 per hour.
```

For a recognized command, MootOS:

1. Extracts the memory content.
2. Writes it to SQLite.
3. Stores it under the current conversation project, or globally when no project is selected.
4. Confirms the save only after the write succeeds.
5. Makes it available to later conversations according to active-memory retrieval rules.

The save operation is handled internally and does not call OpenAI or spend model credits.

Questions such as:

```text
Do you remember that studio session?
```

remain ordinary model requests and are not interpreted as writes.

## Review and control saved memories

Open the protected memory page:

```text
/memory
```

Or tap **Memories** from the chat interface.

The screen shows saved rows, including:

- Memory content
- Global or project scope
- Project name
- Memory type or source
- Original or corrected version label
- Lifecycle status
- Creation date

Available controls on the current branch:

- Active or Archived view
- All memories
- Global only
- One exact project
- **Correct** on active memories
- **Forget** on active memories
- **Restore** on archived memories

Correction creates a new active version and marks the selected version superseded in one transaction. The prior value remains available through the history API.

Forget is recoverable archival, not permanent deletion. The selected row becomes archived, leaves normal recall, and remains available for restoration. Restore returns that same row to active status.

## What is not built yet

The following remain planned:

- Natural-language `forget` commands
- Natural-language memory update and correction commands
- Permanent-delete or secure-erasure UI
- Bulk archive and restore
- Duplicate and conflict detection
- Keyword or semantic memory search
- Automatic profile import
- Automatic encrypted database backups and scheduled restore testing
- Voice conversations
- Runtime tool integrations such as calendar, email, or file access
- Local AI models
- Multiple cooperating AI specialists or a board-of-directors system
- Reviewable self-learning from engineering work
- Multi-user accounts
- Native mobile application

See [`ROADMAP.md`](ROADMAP.md).

## System overview

```text
Phone or desktop browser
        |
        v
FastAPI application (backend/main.py)
        |
        |-- Authentication and sessions (backend/auth.py)
        |-- Central SQLite configuration (backend/db.py)
        |-- Versioned migrations (backend/migrations.py)
        |-- Conversation storage (backend/conversation.py)
        |-- Project and memory lifecycle storage (backend/memory.py)
        |-- Explicit memory-command parser (backend/memory_commands.py)
        |-- Model provider boundary (backend/model_router.py)
        |-- Static chat and memory interfaces (frontend/)
        |
        v
SQLite database
        |
        |-- Local: data/mootos.db
        `-- Railway: /data/mootos.db

OpenAI Responses API
        ^
        |
Normal conversation only
```

## Chat request behavior

### Normal message

1. The browser sends `POST /chat`.
2. FastAPI verifies the session.
3. MootOS checks that the message is not an explicit save command.
4. The provider configuration is validated.
5. The conversation and user message are stored.
6. Recent history and active relevant memories are loaded.
7. The provider generates a response.
8. The assistant response is stored and returned.

### Explicit memory save

1. MootOS recognizes the command deterministically.
2. The conversation and user command are stored.
3. The extracted memory is written to SQLite with type `explicit_chat` and status `active`.
4. A deterministic confirmation is stored and returned.
5. The external model provider is not called.

The browser never receives the OpenAI API key.

## Memory lifecycle

- `active` — included in normal lists and model context
- `superseded` — preserved older version replaced by correction
- `archived` — recoverably forgotten and excluded from normal recall

Correction is append-and-supersede. Archive and restore change the status of the latest version without changing correction links.

The browser does not expose permanent delete. The legacy administrative delete API refuses to delete archived, superseded, or correction-linked rows.

## Memory scope

- A memory saved without a project is global and can appear in any project chat.
- Conversations without a project can load all active memories.
- A project chat currently loads active global memory plus active memory for that project.
- Projects are intended as focus lenses, not permanent secrecy walls; cross-project relevance ranking is planned for the retrieval branch.
- At most 20 newest active relevant memories are supplied to the model.

The review page can display active or archived rows, but archived and superseded rows are never supplied to ordinary model context.

This remains simple newest-first retrieval. Keyword ranking, embeddings, and deduplication are not implemented.

## Repository layout

```text
MootOS/
|-- backend/
|   |-- main.py                FastAPI routes and chat orchestration
|   |-- auth.py                Password and signed-session behavior
|   |-- db.py                  SQLite path and connection policy
|   |-- migrations.py          Ordered schema migrations
|   |-- conversation.py        Conversation and message persistence
|   |-- memory.py              Project and memory lifecycle persistence
|   |-- memory_commands.py     Explicit save-command parsing
|   `-- model_router.py        Replaceable provider protocol
|-- frontend/                  Mobile chat and memory interfaces
|-- tests/                     Automated behavior and safety tests
|-- docs/                      Current truth, runbooks, ADRs, and references
|-- railway.toml               Railway start and health configuration
|-- requirements.txt           Pinned production dependencies
|-- requirements-dev.txt       Pinned test and lint dependencies
|-- ARCHITECTURE.md            Long-term architecture vision
|-- ROADMAP.md                 Version plan
|-- V0.1_REQUIREMENTS.md       Version 0.1 criteria
|-- DECISIONS.md               Original high-level decisions
`-- CONTRIBUTING.md            Development and approval rules
```

## Local development

### Requirements

- Python 3.9 or newer
- Virtual environment recommended
- OpenAI API key required only for real normal-chat responses

### Install

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements-dev.txt
```

Windows PowerShell:

```powershell
.venv\Scripts\Activate.ps1
```

### Configure

```bash
cp .env.example .env
```

Never commit `.env` or real secrets.

### Run

```bash
python -m uvicorn backend.main:app --reload
```

Open:

```text
http://127.0.0.1:8000/chat
http://127.0.0.1:8000/memory
```

### Test

```bash
python -m pytest
```

Tests use fake model providers and do not need to spend API credits.

## Environment variables

| Variable | Required | Purpose |
|---|---:|---|
| `AI_PROVIDER` | No | Current supported value: `openai`. |
| `OPENAI_API_KEY` | For real normal chat | Secret key used only by the backend. |
| `OPENAI_MODEL` | No | Model name. Defaults to `gpt-5-mini`. |
| `MOOTOS_PASSWORD` | Required for private Railway access | Login password. |
| `MOOTOS_SESSION_SECRET` | Required for private Railway access | Long random session-signing secret. |
| `MOOTOS_ALLOW_PUBLIC` | No | High-risk explicit Railway public-access override. |
| `MOOTOS_SECURE_COOKIES` | No | Secure-cookie override. Railway enables them automatically. |
| `MOOTOS_DATABASE_PATH` | No | Exact SQLite path override. |
| `RAILWAY_VOLUME_MOUNT_PATH` | Supplied by Railway | Volume location used for `mootos.db`. |
| `RAILWAY_ENVIRONMENT` | Supplied by Railway | Activates production safety behavior. |
| `RAILWAY_PUBLIC_DOMAIN` | Supplied by Railway | Also identifies Railway. |
| `PORT` | Supplied by Railway | Uvicorn port. |

## Data and persistence

Database path priority:

1. `MOOTOS_DATABASE_PATH`
2. `<RAILWAY_VOLUME_MOUNT_PATH>/mootos.db`
3. `data/mootos.db`

Production uses:

```text
/data/mootos.db
```

Keep Railway at **one replica** while SQLite is live. WAL improves local concurrency but does not make multiple replicas safe.

Read:

- [`docs/DATA_AND_PERSISTENCE.md`](docs/DATA_AND_PERSISTENCE.md)
- [`docs/FOUNDATION_HARDENING.md`](docs/FOUNDATION_HARDENING.md)
- [`docs/CURRENT_IMPLEMENTATION.md`](docs/CURRENT_IMPLEMENTATION.md)

## Railway deployment

Start command:

```text
python -m uvicorn backend.main:app --host 0.0.0.0 --port $PORT
```

Health check:

```text
/health
```

Guides:

- [`docs/PHONE_DEPLOYMENT.md`](docs/PHONE_DEPLOYMENT.md)
- [`docs/OPERATIONS_RUNBOOK.md`](docs/OPERATIONS_RUNBOOK.md)

## API summary

Public routes:

- `GET /health`
- `GET /login`
- `POST /auth/login`
- `POST /auth/logout`
- Static files and manifest

Protected application routes include:

- `GET /chat`
- `POST /chat`
- `GET /memory`
- Project, memory, and conversation APIs
- Memory correction, history, archive, and restore APIs

See [`docs/API_REFERENCE.md`](docs/API_REFERENCE.md).

## Security and control boundaries

Current protections:

- Railway auth fails closed by default
- Signed HTTP-only sessions
- Secure cookies on Railway
- Environment-based secrets
- Protected chat, memory interface, and APIs
- Verified write-before-confirm memory behavior
- Exact selected-memory confirmation for correction, forget, and restore
- No browser permanent-delete request
- Explicit approval before merges

Current limitations:

- Single user
- No login rate limiting
- No MootOS-managed database encryption at rest
- Public minimal `/health`
- One manual off-volume backup/restore drill; no automatic backup or retention
- No natural-language destructive memory actions

## Development workflow

1. Start from current `main`.
2. Create one focused branch.
3. Add tests for behavior changes.
4. Update documentation in the same PR.
5. Open a draft PR.
6. Wait for GitHub Actions.
7. Review in plain language.
8. Complete external read-only review when useful.
9. Moot explicitly approves the exact merge.
10. Railway deploys merged `main`.
11. Verify the feature and old data in production.

Documentation is part of the definition of done.

## Documentation map

Start with [`docs/README.md`](docs/README.md).

Key documents:

- [`docs/CURRENT_CHECKPOINT.md`](docs/CURRENT_CHECKPOINT.md)
- [`docs/CURRENT_IMPLEMENTATION.md`](docs/CURRENT_IMPLEMENTATION.md)
- [`docs/API_REFERENCE.md`](docs/API_REFERENCE.md)
- [`docs/DATA_AND_PERSISTENCE.md`](docs/DATA_AND_PERSISTENCE.md)
- [`docs/OPERATIONS_RUNBOOK.md`](docs/OPERATIONS_RUNBOOK.md)
- [`ROADMAP.md`](ROADMAP.md)
- [`V0.1_REQUIREMENTS.md`](V0.1_REQUIREMENTS.md)
- [`CONTRIBUTING.md`](CONTRIBUTING.md)

## Core rule

MootOS should become more capable without becoming less understandable, less secure, or less controllable.
