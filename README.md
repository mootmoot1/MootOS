# MootOS

MootOS is Moot's private, mobile-friendly personal AI foundation.

Version 0.1 currently provides a working chat interface, persistent conversations, project-organized memories, a replaceable model-provider boundary, private password access, and Railway deployment with persistent SQLite storage.

MootOS is intentionally being built in small, reviewable steps. The immediate goal is not to imitate every feature of a commercial AI platform. The goal is to establish a reliable system that Moot controls and can expand over time.

## Current status

**Version:** `0.1.0`  
**Primary branch:** `main`  
**Deployment:** Railway, one service and one replica  
**Production database:** SQLite on a Railway volume mounted at `/data`  
**Persistence verification:** Conversations and memories survived three consecutive Railway deployments on July 31, 2026  
**Current model provider:** OpenAI through a replaceable provider interface

See [`docs/CURRENT_CHECKPOINT.md`](docs/CURRENT_CHECKPOINT.md) for the latest verified project state.

## What works today

- Private password login for the deployed application
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
- Public health check for Railway
- Persistent production data through an attached Railway volume
- Automated tests for memory, projects, conversations, authentication, interface behavior, and deployment configuration

## What is not built yet

The following items are planned, but they should not be mistaken for current capabilities:

- Natural-language memory commands such as “remember this,” “forget that,” and “update that”
- Memory review and correction interface
- Keyword or semantic memory search
- Database migration runner
- Automated database backups
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

For a precise description of what every current module does, read [`docs/CURRENT_IMPLEMENTATION.md`](docs/CURRENT_IMPLEMENTATION.md).

## How a chat request works

1. The browser sends a message to `POST /chat`.
2. FastAPI verifies the private session when authentication is enabled.
3. MootOS validates or creates the conversation.
4. The user message is stored in SQLite.
5. Recent messages are loaded from the conversation.
6. Relevant saved memories are loaded and added to the model instructions.
7. The configured model provider generates a response.
8. The assistant response and provider metadata are stored in SQLite.
9. The response is returned to the browser.

The browser never receives the OpenAI API key. The backend makes provider requests.

## Repository layout

```text
MootOS/
|-- backend/
|   |-- main.py            FastAPI routes, request models, and chat orchestration
|   |-- auth.py            Password checks and signed session cookies
|   |-- conversation.py    Conversation and message persistence
|   |-- memory.py          Database path, schema initialization, projects, and memories
|   `-- model_router.py    Replaceable model-provider protocol and OpenAI provider
|-- frontend/
|   |-- index.html         Main chat interface
|   |-- login.html         Private deployment login page
|   |-- app.js             Browser-side chat behavior
|   |-- styles.css         Mobile and desktop styling
|   `-- manifest.webmanifest
|-- tests/                 Automated backend, interface, auth, and deployment tests
|-- docs/                  Checkpoints, runbooks, ADRs, and detailed references
|-- railway.toml           Railway build and start configuration
|-- requirements.txt       Production Python dependencies
|-- requirements-dev.txt   Development and test dependencies
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
python -m pip install -r requirements.txt
python -m pip install -r requirements-dev.txt
```

On Windows PowerShell, activate the environment with:

```powershell
.venv\Scripts\Activate.ps1
```

### Configure

Copy the safe example environment file:

```bash
cp .env.example .env
```

Set the values needed for your environment. Never commit `.env` or real secrets.

### Run

```bash
python -m uvicorn backend.main:app --reload
```

Open:

```text
http://127.0.0.1:8000/chat
```

Authentication may remain disabled during local development when both `MOOTOS_PASSWORD` and `MOOTOS_SESSION_SECRET` are absent.

### Test

```bash
python -m pytest
```

The automated tests use fake model providers where appropriate, so tests do not need to spend API credits.

## Environment variables

| Variable | Required | Purpose |
|---|---:|---|
| `AI_PROVIDER` | No | Selects the model provider. Current supported value: `openai`. Defaults to `openai`. |
| `OPENAI_API_KEY` | For real OpenAI chat | Secret key used only by the backend. |
| `OPENAI_MODEL` | No | OpenAI model name. Defaults to `gpt-5-mini`. |
| `MOOTOS_PASSWORD` | Required for private production access | Password accepted by the login endpoint. Must be configured together with `MOOTOS_SESSION_SECRET`. |
| `MOOTOS_SESSION_SECRET` | Required for private production access | Secret used to sign browser session tokens. Must be long, random, and different from the login password. |
| `MOOTOS_SECURE_COOKIES` | No | Explicitly enables or disables secure cookies. Railway enables them automatically. |
| `MOOTOS_DATABASE_PATH` | No | Explicit SQLite file path. Overrides automatic path selection. |
| `RAILWAY_VOLUME_MOUNT_PATH` | Supplied by Railway when a volume is attached | MootOS stores the database at `<mount>/mootos.db`. |
| `RAILWAY_ENVIRONMENT` | Supplied by Railway | Used to detect production behavior such as secure cookies. |
| `RAILWAY_PUBLIC_DOMAIN` | Supplied by Railway | Also indicates a Railway deployment for secure-cookie behavior. |
| `PORT` | Supplied by Railway | Port used by Uvicorn in production. |

## Data and persistence

MootOS currently uses one SQLite database for projects, memories, conversations, and messages.

Database path priority:

1. `MOOTOS_DATABASE_PATH`, when explicitly set
2. `<RAILWAY_VOLUME_MOUNT_PATH>/mootos.db`, when Railway supplies a mounted volume
3. `data/mootos.db` inside the repository during local development

The production volume must remain mounted at:

```text
/data
```

The production database is therefore:

```text
/data/mootos.db
```

Keep Railway at **one replica** while SQLite is the database. Read [`docs/DATA_AND_PERSISTENCE.md`](docs/DATA_AND_PERSISTENCE.md) before changing storage, replicas, or backup behavior.

## Railway deployment

Railway runs:

```text
python -m uvicorn backend.main:app --host 0.0.0.0 --port $PORT
```

The deployment health check is:

```text
/health
```

The complete setup and verification guide is in [`docs/PHONE_DEPLOYMENT.md`](docs/PHONE_DEPLOYMENT.md). Operational recovery steps are in [`docs/OPERATIONS_RUNBOOK.md`](docs/OPERATIONS_RUNBOOK.md).

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

Detailed request fields, responses, and error behavior are documented in [`docs/API_REFERENCE.md`](docs/API_REFERENCE.md).

## Security boundary

MootOS Version 0.1 is a private, single-user application.

Current protections include:

- Password-gated production access
- Signed browser session tokens
- HTTP-only cookies
- Secure cookies on Railway
- SameSite `lax` cookies
- Secrets stored in environment variables instead of browser JavaScript
- Authentication middleware protecting application and API routes
- Explicit human approval before merges

Current limitations include:

- The application is not designed for multiple independent users
- The configured login password is supplied through a Railway environment variable
- There is not yet login rate limiting
- There is not yet database encryption at rest implemented by MootOS
- `/health` is intentionally public and contains only a minimal status response

## Development workflow

1. Start from the latest `main` branch.
2. Create one focused feature, fix, test, security, or documentation branch.
3. Make only changes belonging to that branch's purpose.
4. Add or update tests for behavior changes.
5. Update documentation in the same PR when behavior changes.
6. Open a draft pull request.
7. Explain the change in plain language.
8. Wait for GitHub Actions.
9. Moot reviews and explicitly approves the merge.
10. Railway deploys the merged `main` branch automatically.

Coding agents may prepare branches and pull requests. They must not merge major changes without Moot's explicit approval.

## Documentation map

Start with [`docs/README.md`](docs/README.md).

Important documents:

- [`docs/CURRENT_CHECKPOINT.md`](docs/CURRENT_CHECKPOINT.md) — latest verified state
- [`docs/CURRENT_IMPLEMENTATION.md`](docs/CURRENT_IMPLEMENTATION.md) — exact system behavior today
- [`docs/API_REFERENCE.md`](docs/API_REFERENCE.md) — current HTTP routes
- [`docs/DATA_AND_PERSISTENCE.md`](docs/DATA_AND_PERSISTENCE.md) — database and storage rules
- [`docs/OPERATIONS_RUNBOOK.md`](docs/OPERATIONS_RUNBOOK.md) — deploy, verify, recover, and roll back
- [`docs/PHONE_DEPLOYMENT.md`](docs/PHONE_DEPLOYMENT.md) — Railway and phone setup
- [`ARCHITECTURE.md`](ARCHITECTURE.md) — long-term architecture vision
- [`ROADMAP.md`](ROADMAP.md) — planned versions and future ideas
- [`V0.1_REQUIREMENTS.md`](V0.1_REQUIREMENTS.md) — release criteria
- [`DECISIONS.md`](DECISIONS.md) and `docs/ADR-*` — architectural reasoning
- [`CONTRIBUTING.md`](CONTRIBUTING.md) — development controls

## Core rule

MootOS should become more capable without becoming less understandable, less secure, or less controllable.
