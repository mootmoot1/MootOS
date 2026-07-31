# MootOS

MootOS is Moot's private, mobile-friendly personal AI foundation.

Version 0.1 currently provides a working chat interface, persistent conversations, project-organized memories, a replaceable model-provider boundary, private password access, and Railway deployment with hardened persistent SQLite storage.

MootOS is built in small, reviewable steps. The immediate goal is a reliable system that Moot controls and can expand without rebuilding the foundation.

## Current status

**Version:** `0.1.0`  
**Primary branch:** `main`  
**Deployment:** Railway, one service and one replica  
**Production database:** SQLite on a Railway volume mounted at `/data`  
**Current schema version:** `1 — initial_schema`  
**Persistence verification:** Conversations and memories survived three consecutive Railway deployments on July 31, 2026  
**Current model provider:** OpenAI through a replaceable provider interface

See [`docs/CURRENT_CHECKPOINT.md`](docs/CURRENT_CHECKPOINT.md) for the latest verified project state.

## What works today

- Private password login for the deployed application
- Railway startup that fails closed when private auth variables are missing
- Signed, HTTP-only browser sessions with a 30-day expiration
- Mobile-friendly chat interface
- Starting and reopening persistent conversations
- Recent conversation history supplied to the model
- Five default projects: MootOS, Studio, Social Media, Cars, and Personal
- Project-specific memories
- Creating, listing, retrieving, filtering, and deleting memories through the API
- Relevant memory context supplied to the model
- Replaceable model-provider boundary
- OpenAI Responses API integration
- Provider and model metadata stored with assistant messages
- Installable web-app manifest for a phone Home Screen
- Public minimal health check for Railway
- Persistent production data through an attached Railway volume
- One centralized SQLite connection layer
- Foreign-key enforcement on every application database connection
- WAL mode, `NORMAL` synchronous mode, and a five-second busy timeout
- Numbered schema migrations recorded in `schema_migrations`
- Protection against running an older build on a newer unknown schema
- Exact direct-dependency pins
- Automated tests for database configuration, migrations, concurrent writes, memory, projects, conversations, authentication, interface behavior, and deployment configuration

## What is not built yet

The following items are planned but are not current capabilities:

- Natural-language memory commands such as “remember this,” “forget that,” and “update that”
- Memory review and correction interface
- Keyword or semantic memory search
- Automatic database backups
- Tested automated restore workflow
- Voice conversations
- Tool integrations such as calendar, email, or file access
- Local AI models
- Multiple cooperating AI specialists or a “board of directors” system
- Reviewable self-learning from engineering work
- Multi-user accounts
- Native mobile application

The roadmap is documented in [`ROADMAP.md`](ROADMAP.md).

## System overview

```text
Phone or desktop browser
        |
        v
FastAPI application (backend/main.py)
        |
        |-- Authentication and signed sessions (backend/auth.py)
        |-- Central SQLite configuration (backend/db.py)
        |-- Versioned schema migrations (backend/migrations.py)
        |-- Conversation storage (backend/conversation.py)
        |-- Project and memory storage (backend/memory.py)
        |-- Model selection and provider boundary (backend/model_router.py)
        |-- Static mobile web interface (frontend/)
        |
        v
SQLite database
        |
        |-- Local development: data/mootos.db
        `-- Railway production: /data/mootos.db

OpenAI Responses API
        ^
        |
Model provider boundary
```

For the exact current runtime behavior, read [`docs/CURRENT_IMPLEMENTATION.md`](docs/CURRENT_IMPLEMENTATION.md).

## How a chat request works

1. The browser sends a message to `POST /chat`.
2. FastAPI verifies the private session when authentication is enabled.
3. MootOS validates or creates the conversation.
4. The user message is stored through the central SQLite layer.
5. Recent messages are loaded from the conversation.
6. Relevant saved memories are added to model instructions.
7. The configured model provider generates a response.
8. The assistant response and provider metadata are stored.
9. The response is returned to the browser.

The browser never receives the OpenAI API key. The backend makes provider requests.

## Repository layout

```text
MootOS/
|-- backend/
|   |-- main.py            FastAPI routes and chat orchestration
|   |-- auth.py            Password checks and signed session cookies
|   |-- db.py              Database path and SQLite connection policy
|   |-- migrations.py      Ordered schema migrations and version tracking
|   |-- conversation.py    Conversation and message persistence
|   |-- memory.py          Project and memory persistence
|   `-- model_router.py    Replaceable provider protocol and OpenAI provider
|-- frontend/              Mobile web interface
|-- tests/                 Automated behavior and hardening tests
|-- docs/                  Checkpoints, runbooks, ADRs, and references
|-- railway.toml           Railway build and start configuration
|-- requirements.txt       Pinned production dependencies
|-- requirements-dev.txt   Pinned test dependencies
|-- ARCHITECTURE.md        Long-term architecture vision
|-- ROADMAP.md             Version plan and future capabilities
|-- V0.1_REQUIREMENTS.md   Version 0.1 success criteria
|-- DECISIONS.md           Original high-level design decisions
`-- CONTRIBUTING.md        Development and approval rules
```

## Local development

### Requirements

- Python 3.9 or newer
- A virtual environment is recommended
- An OpenAI API key is required only for real model responses

### Install

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements-dev.txt
```

On Windows PowerShell:

```powershell
.venv\Scripts\Activate.ps1
```

### Configure

```bash
cp .env.example .env
```

Set only the values needed for the environment. Never commit `.env` or real secrets.

### Run

```bash
python -m uvicorn backend.main:app --reload
```

Open:

```text
http://127.0.0.1:8000/chat
```

Local authentication may remain disabled when Railway metadata is absent and both `MOOTOS_PASSWORD` and `MOOTOS_SESSION_SECRET` are absent.

### Test

```bash
python -m pytest
```

Tests use fake model providers where appropriate and do not need to spend API credits.

## Environment variables

| Variable | Required | Purpose |
|---|---:|---|
| `AI_PROVIDER` | No | Current supported value: `openai`. |
| `OPENAI_API_KEY` | For real OpenAI chat | Secret key used only by the backend. |
| `OPENAI_MODEL` | No | Model name. Defaults to `gpt-5-mini`. |
| `MOOTOS_PASSWORD` | Required for private Railway access | Login password. Must be configured with `MOOTOS_SESSION_SECRET`. |
| `MOOTOS_SESSION_SECRET` | Required for private Railway access | Long random secret used to sign browser sessions. |
| `MOOTOS_ALLOW_PUBLIC` | No | High-risk override. `true` explicitly allows Railway startup without private auth. Do not set for normal MootOS production. |
| `MOOTOS_SECURE_COOKIES` | No | Explicit secure-cookie override. Railway enables secure cookies automatically. |
| `MOOTOS_DATABASE_PATH` | No | Exact SQLite file path. Overrides automatic path selection. |
| `RAILWAY_VOLUME_MOUNT_PATH` | Supplied by Railway | MootOS stores the database at `<mount>/mootos.db`. |
| `RAILWAY_ENVIRONMENT` | Supplied by Railway | Identifies Railway and activates fail-closed production behavior. |
| `RAILWAY_PUBLIC_DOMAIN` | Supplied by Railway | Also identifies Railway for production behavior. |
| `PORT` | Supplied by Railway | Port used by Uvicorn. |

## Data and persistence

Database path priority:

1. `MOOTOS_DATABASE_PATH`
2. `<RAILWAY_VOLUME_MOUNT_PATH>/mootos.db`
3. `data/mootos.db`

Production uses:

```text
/data/mootos.db
```

Every application connection enables foreign keys, WAL, `NORMAL` synchronous mode, and a five-second busy timeout. Schema versions are recorded in `schema_migrations`.

Keep Railway at **one replica** while SQLite is the live database. WAL improves local concurrency but does not turn one SQLite file into a multi-replica database.

Read:

- [`docs/DATA_AND_PERSISTENCE.md`](docs/DATA_AND_PERSISTENCE.md)
- [`docs/FOUNDATION_HARDENING.md`](docs/FOUNDATION_HARDENING.md)
- [`docs/ADR-015-foundation-hardening.md`](docs/ADR-015-foundation-hardening.md)

## Railway deployment

Railway runs:

```text
python -m uvicorn backend.main:app --host 0.0.0.0 --port $PORT
```

Health check:

```text
/health
```

Railway refuses to start without both private auth values unless `MOOTOS_ALLOW_PUBLIC=true` is deliberately set.

Deployment and recovery guides:

- [`docs/PHONE_DEPLOYMENT.md`](docs/PHONE_DEPLOYMENT.md)
- [`docs/OPERATIONS_RUNBOOK.md`](docs/OPERATIONS_RUNBOOK.md)

## API summary

Public routes:

- `GET /health`
- `GET /login`
- `POST /auth/login`
- `POST /auth/logout`
- Static files and the web-app manifest

Authenticated application routes when private access is enabled:

- `GET /chat`
- `POST /chat`
- `GET /projects`
- `POST /projects`
- `GET /memories`
- `POST /memories`
- `GET /memories/{memory_id}`
- `DELETE /memories/{memory_id}`
- `GET /conversations`
- `POST /conversations`
- `GET /conversations/{conversation_id}`

See [`docs/API_REFERENCE.md`](docs/API_REFERENCE.md).

## Security boundary

MootOS Version 0.1 is a private, single-user application.

Current protections include:

- Railway auth that fails closed by default
- Password-gated application access
- Signed browser session tokens
- HTTP-only cookies
- Secure cookies on Railway
- SameSite `lax` cookies
- Environment-based secrets
- Protected application and API routes
- Explicit approval before merges

Current limitations include:

- No multi-user account isolation
- No login rate limiting
- No MootOS-managed database encryption at rest
- Public minimal `/health` endpoint
- No automatic off-volume backup or tested restore automation

## Development workflow

1. Start from the latest `main`.
2. Create one focused branch.
3. Change only the intended system.
4. Add tests for behavior changes.
5. Update relevant documentation in the same PR.
6. Open a draft pull request.
7. Explain the change in plain language.
8. Wait for GitHub Actions.
9. Moot reviews and explicitly approves the merge.
10. Railway deploys merged `main` automatically.

Documentation is part of the definition of done. A feature is not ready to merge while the repository still describes the previous behavior.

## Documentation map

Start with [`docs/README.md`](docs/README.md).

Key documents:

- [`docs/CURRENT_CHECKPOINT.md`](docs/CURRENT_CHECKPOINT.md)
- [`docs/CURRENT_IMPLEMENTATION.md`](docs/CURRENT_IMPLEMENTATION.md)
- [`docs/API_REFERENCE.md`](docs/API_REFERENCE.md)
- [`docs/DATA_AND_PERSISTENCE.md`](docs/DATA_AND_PERSISTENCE.md)
- [`docs/FOUNDATION_HARDENING.md`](docs/FOUNDATION_HARDENING.md)
- [`docs/OPERATIONS_RUNBOOK.md`](docs/OPERATIONS_RUNBOOK.md)
- [`docs/PHONE_DEPLOYMENT.md`](docs/PHONE_DEPLOYMENT.md)
- [`ARCHITECTURE.md`](ARCHITECTURE.md)
- [`ROADMAP.md`](ROADMAP.md)
- [`V0.1_REQUIREMENTS.md`](V0.1_REQUIREMENTS.md)
- [`DECISIONS.md`](DECISIONS.md) and `docs/ADR-*`
- [`CONTRIBUTING.md`](CONTRIBUTING.md)

## Core rule

MootOS should become more capable without becoming less understandable, less secure, or less controllable.
