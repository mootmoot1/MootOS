# MootOS Current Implementation

**Applies to:** Version 0.1 on `main` as of July 31, 2026  
**Purpose:** Describe what the current code actually does, separate from the long-term architecture vision.

## 1. Runtime shape

MootOS currently runs as one FastAPI application process.

Production uses one Railway service and one replica. Railway starts the application with Uvicorn. The same service:

- Serves the mobile web interface
- Handles login and session validation
- Exposes the JSON APIs
- Reads and writes SQLite
- Builds model context
- Calls the configured AI provider
- Returns responses to the browser

There are no separate microservices, background workers, task queues, cache servers, or vector databases in the current implementation.

## 2. Current modules

### `backend/main.py`

Responsibilities:

- Creates the FastAPI application
- Mounts the frontend static directory
- Initializes the database schema during application import
- Defines Pydantic request models
- Applies authentication middleware
- Serves the login page, chat interface, manifest, and health endpoint
- Exposes project, memory, conversation, and chat routes
- Builds model instructions from the base identity prompt and saved memories
- Orchestrates the full chat request

The file does not directly implement cookie signing, database CRUD details, or OpenAI request construction. Those responsibilities are delegated to other modules.

### `backend/auth.py`

Responsibilities:

- Determines whether password protection is enabled
- Verifies that password and session-secret configuration are supplied together
- Compares login submissions with the configured password using constant-time comparison
- Creates signed session tokens containing expiration, nonce, and token version
- Verifies signatures and expiration
- Reads the session cookie from incoming requests
- Sets and clears HTTP-only cookies
- Automatically uses secure cookies on Railway

Current authentication boundary:

- Single configured password
- Single application-wide session secret
- No user accounts or roles
- No password-reset workflow
- No login rate limiting
- No server-side session database

### `backend/memory.py`

Responsibilities:

- Resolves the SQLite database path
- Opens SQLite connections for project and memory operations
- Creates the initial database schema
- Seeds five default projects
- Creates and lists projects
- Creates, lists, retrieves, filters, and deletes memories

Database path priority:

1. `MOOTOS_DATABASE_PATH`
2. `RAILWAY_VOLUME_MOUNT_PATH/mootos.db`
3. Repository-local `data/mootos.db`

Default projects:

- MootOS
- Studio
- Social Media
- Cars
- Personal

Current schema initialization uses `CREATE TABLE IF NOT EXISTS`. There is not yet a versioned migration runner.

### `backend/conversation.py`

Responsibilities:

- Opens SQLite connections for conversation operations
- Creates conversations
- Lists conversations, optionally by project
- Loads one conversation and its messages
- Adds user and assistant messages
- Updates the conversation timestamp when a message is stored

Each storage operation opens a connection for that operation and closes it through a context manager.

Current conversation roles are limited to:

- `user`
- `assistant`

Assistant messages may also store:

- Provider name
- Model name

### `backend/model_router.py`

Responsibilities:

- Defines the normalized model response
- Defines the provider protocol
- Selects the configured provider
- Validates provider configuration
- Calls the provider and converts provider failures into application-specific errors

Current supported provider:

- OpenAI

Current OpenAI behavior:

- Uses the OpenAI Python SDK
- Uses the Responses API
- Sends model instructions separately from conversation messages
- Disables OpenAI-side response storage with `store=False`
- Returns normalized text, provider, and model metadata

The provider boundary is replaceable, but other providers are not implemented yet.

### `frontend/`

Responsibilities:

- Displays the chat interface
- Displays user and assistant message bubbles
- Lets the user select a project
- Starts new conversations
- Loads saved conversation history
- Sends messages to the FastAPI backend
- Displays loading and error states
- Provides login and logout controls
- Supplies installable web-app metadata

The frontend is plain HTML, CSS, and JavaScript. It does not use React, Node.js, a frontend build process, or an external UI framework.

## 3. Database schema

MootOS currently uses one SQLite file.

### `projects`

| Column | Meaning |
|---|---|
| `id` | UUID text primary key |
| `name` | Unique project name, case-insensitive |
| `description` | Optional project description |
| `created_at` | UTC timestamp stored as text |

### `memories`

| Column | Meaning |
|---|---|
| `id` | UUID text primary key |
| `content` | Memory text |
| `project` | Optional project name |
| `memory_type` | Optional caller-supplied category |
| `created_at` | UTC timestamp stored as text |

### `conversations`

| Column | Meaning |
|---|---|
| `id` | UUID text primary key |
| `title` | Conversation title |
| `project` | Optional project name |
| `created_at` | UTC timestamp stored as text |
| `updated_at` | UTC timestamp of the latest stored message |

### `messages`

| Column | Meaning |
|---|---|
| `id` | UUID text primary key |
| `conversation_id` | Owning conversation ID |
| `role` | `user` or `assistant` |
| `content` | Message text |
| `provider` | Optional model-provider name |
| `model` | Optional model name |
| `created_at` | UTC timestamp stored as text |

An index exists on `messages.conversation_id`.

The schema declares a foreign key from messages to conversations. SQLite foreign-key enforcement is not yet explicitly enabled on every connection. That hardening belongs in a future code PR, not this documentation PR.

## 4. Chat request flow

### New conversation

1. `POST /chat` receives `message` and optional `project`.
2. The model router verifies that the selected provider is configured before a conversation is created.
3. MootOS creates a conversation.
4. The initial title is the first 80 trimmed characters of the user message.
5. The user message is saved.
6. Up to 20 recent messages are loaded in chronological order.
7. Model instructions are built.
8. The configured provider generates a response.
9. The assistant message is saved with provider and model metadata.
10. The API returns the conversation ID and both stored messages.

### Existing conversation

1. `POST /chat` receives `conversation_id`.
2. MootOS verifies that the conversation exists.
3. When a project is also supplied, MootOS verifies that it matches the conversation project.
4. The remaining flow is the same as a new conversation.

### Provider failure behavior

- Missing provider configuration returns HTTP `503`.
- Provider request failure returns HTTP `502`.
- A missing model configuration is checked before saving the new chat, preventing creation of an empty conversation in that case.
- When the provider fails after the user message is stored, the current implementation can leave the user message without a matching assistant response. Recovery behavior for that situation is not yet implemented.

## 5. Memory supplied to the model

The base instructions identify the assistant as MootOS Version 0.1 and establish basic behavior and honesty rules.

Memory behavior:

- When a conversation has a project, MootOS loads memories assigned to that project.
- When a conversation has no project, MootOS loads memories across all projects.
- Memories are ordered newest first.
- At most 20 recent memories are placed in the model instructions.
- Each memory line includes project, memory type, and content.

Current limitations:

- No keyword ranking
- No semantic ranking
- No embeddings
- No confidence score
- No source tracking beyond stored fields
- No automatic correction chain
- No natural-language remember/forget/update command handling
- No memory deduplication

## 6. Authentication flow

1. When both `MOOTOS_PASSWORD` and `MOOTOS_SESSION_SECRET` are absent, authentication is disabled.
2. When exactly one is present, application configuration validation raises an error.
3. When both are present, application and API routes require a valid signed cookie.
4. Browser requests for protected HTML are redirected to `/login`.
5. Protected API requests without authentication receive HTTP `401` JSON.
6. A correct login creates a signed cookie with a 30-day maximum age.
7. Logout deletes the cookie.

Public paths include login, logout, health, manifest, and static assets.

The production deployment is expected to configure both private variables. A future security-hardening PR should make a Railway deployment refuse to start if both are missing instead of interpreting that state as local development.

## 7. Production deployment

Railway configuration:

- Builder: Railpack
- Start command: Uvicorn serving `backend.main:app`
- Bind address: `0.0.0.0`
- Port: Railway-provided `PORT`
- Health check: `/health`
- Restart policy: restart on failure
- Replicas: one while SQLite is used
- Persistent volume mount: `/data`

When the volume is attached, Railway supplies `RAILWAY_VOLUME_MOUNT_PATH`. MootOS then stores the database at `/data/mootos.db`.

Persistence was manually verified by saving data and confirming it survived three consecutive deployments.

## 8. Current HTTP surface

Interface and auth:

- `GET /`
- `GET /login`
- `POST /auth/login`
- `POST /auth/logout`
- `GET /chat`
- `GET /manifest.webmanifest`
- `GET /health`

Memory and projects:

- `POST /memories`
- `GET /memories`
- `GET /memories/{memory_id}`
- `DELETE /memories/{memory_id}`
- `GET /projects`
- `POST /projects`

Conversations:

- `POST /conversations`
- `GET /conversations`
- `GET /conversations/{conversation_id}`
- `POST /chat`

See `API_REFERENCE.md` for details.

## 9. Test coverage

The repository includes automated tests covering:

- Memory creation, retrieval, listing, deletion, and persistence
- Project creation, validation, duplicate handling, and filtering
- Conversation creation and continuation
- Chat message persistence
- Model-provider mocking
- Project-memory injection into model instructions
- Missing model configuration
- Mobile interface assets and routes
- Authentication redirects, login, logout, and configuration validation
- Railway port and health-check configuration
- Railway volume path resolution
- Web-app manifest behavior

Known missing test areas include:

- Concurrent SQLite writes
- Explicit WAL and foreign-key enforcement
- Schema migrations
- Backup and restore
- Provider timeout recovery after a user message is saved
- Login rate limiting
- Browser end-to-end testing against the deployed Railway environment

## 10. Intentional boundaries

Version 0.1 is currently:

- Single user
- Single Railway replica
- One SQLite database
- One implemented AI provider
- Text chat only
- Synchronous provider calls
- No task queue
- No autonomous external actions
- No multi-agent system

These are deliberate limits, not hidden capabilities.

## 11. Source of truth rule

When documentation and code disagree:

1. The code and tests describe actual runtime behavior.
2. This document should be corrected in the same PR that changes behavior.
3. Future-looking documents must label planned features as planned.
4. No documentation should claim a feature works until it is implemented and verified.
