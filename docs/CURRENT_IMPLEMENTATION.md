# MootOS Current Implementation

**Applies to:** Version 0.1 foundation hardening  
**Purpose:** Describe what the code actually does, separate from future plans.

## 1. Runtime shape

MootOS runs as one FastAPI application process.

Production uses one Railway service and one replica. The same process:

- Serves the mobile web interface
- Handles login and session validation
- Exposes JSON APIs
- Runs schema migrations during startup
- Reads and writes SQLite
- Builds model context
- Calls the configured AI provider
- Returns responses to the browser

There are no microservices, background workers, task queues, cache servers, vector databases, or multiple application replicas.

## 2. Current modules

### `backend/main.py`

Responsibilities:

- Creates the FastAPI application
- Mounts frontend static files
- Validates auth configuration during import
- Initializes the database through `memory.init_db()`, which delegates to the migration runner
- Defines request models and routes
- Applies authentication middleware
- Builds model instructions from identity rules and saved memories
- Orchestrates chat requests

### `backend/auth.py`

Responsibilities:

- Detects whether authentication is configured
- Requires password and session secret together
- Detects Railway through Railway environment metadata
- Refuses Railway startup when both private auth values are absent
- Permits public Railway startup only when `MOOTOS_ALLOW_PUBLIC=true`
- Compares passwords using constant-time comparison
- Creates and verifies signed session tokens
- Sets and clears HTTP-only cookies
- Uses secure cookies automatically on Railway

Current auth boundary:

- One configured password
- One application-wide session secret
- No user accounts or roles
- No password-reset workflow
- No login rate limiting
- No server-side session database

### `backend/db.py`

Responsibilities:

- Resolves the SQLite path
- Creates the database parent directory
- Opens all application SQLite connections
- Applies one consistent connection policy
- Provides a context manager that commits, rolls back, and closes connections

Database path priority:

1. `MOOTOS_DATABASE_PATH`
2. `RAILWAY_VOLUME_MOUNT_PATH/mootos.db`
3. Repository-local `data/mootos.db`

Every connection applies:

```text
foreign_keys = ON
journal_mode = WAL
synchronous = NORMAL
busy_timeout = 5000 milliseconds
connection timeout = 5 seconds
row_factory = sqlite3.Row
```

### `backend/migrations.py`

Responsibilities:

- Defines ordered numbered migrations
- Creates and reads `schema_migrations`
- Serializes migration work with `BEGIN IMMEDIATE`
- Applies unapplied migrations in order
- Records migration name, version, and application time
- Rejects a database schema newer than the current application understands
- Seeds the five default projects during the initial migration

Current migration:

```text
1 — initial_schema
```

The first hardened startup adopts an existing Version 0.1 database without dropping or replacing its data.

### `backend/memory.py`

Responsibilities:

- Delegates startup initialization to the migration runner
- Creates and lists projects
- Creates, lists, retrieves, filters, and deletes memories
- Uses the central database context manager for all operations
- Validates projects inside the same connection used for the memory operation

Default projects:

- MootOS
- Studio
- Social Media
- Cars
- Personal

### `backend/conversation.py`

Responsibilities:

- Creates and lists conversations
- Loads one conversation and its messages
- Adds user and assistant messages
- Updates conversation timestamps
- Uses the central database context manager
- Checks conversation existence in the same transaction used to add a message

Current message roles:

- `user`
- `assistant`

Assistant messages may store provider and model names.

### `backend/model_router.py`

Responsibilities:

- Defines the normalized model response
- Defines the provider protocol
- Selects and validates the configured provider
- Calls the provider
- Converts provider failures into application errors

Current provider:

- OpenAI

Current OpenAI behavior:

- Uses the OpenAI Python SDK
- Uses the Responses API
- Sends instructions separately from conversation messages
- Uses `store=False`
- Returns normalized text, provider, and model metadata

Other providers are not implemented yet.

### `frontend/`

The frontend is plain HTML, CSS, and JavaScript.

It provides:

- Login and logout
- User and assistant message bubbles
- Text composer
- Project selection
- New conversation control
- Saved conversation history
- Loading and error states
- Installable web-app metadata

It does not use React, Node.js, or a frontend build process.

## 3. Database schema

MootOS uses one SQLite file.

### `schema_migrations`

| Column | Meaning |
|---|---|
| `version` | Applied numeric schema version |
| `name` | Migration name |
| `applied_at` | UTC application timestamp |

### `projects`

| Column | Meaning |
|---|---|
| `id` | UUID text primary key |
| `name` | Unique project name, case-insensitive |
| `description` | Optional description |
| `created_at` | UTC timestamp text |

### `memories`

| Column | Meaning |
|---|---|
| `id` | UUID text primary key |
| `content` | Memory text |
| `project` | Optional project name |
| `memory_type` | Optional caller-supplied category |
| `created_at` | UTC timestamp text |

### `conversations`

| Column | Meaning |
|---|---|
| `id` | UUID text primary key |
| `title` | Conversation title |
| `project` | Optional project name |
| `created_at` | UTC timestamp text |
| `updated_at` | Latest stored-message timestamp |

### `messages`

| Column | Meaning |
|---|---|
| `id` | UUID text primary key |
| `conversation_id` | Owning conversation ID |
| `role` | `user` or `assistant` |
| `content` | Message text |
| `provider` | Optional provider name |
| `model` | Optional model name |
| `created_at` | UTC timestamp text |

An index exists on `messages.conversation_id`.

The messages table declares a foreign key to conversations, and the central connection layer now enforces it.

## 4. Startup flow

1. Python imports `backend.main`.
2. Auth configuration is validated.
3. Railway without auth values fails unless explicit public access is configured.
4. FastAPI is created.
5. Database initialization delegates to the migration runner.
6. The migration runner opens a hardened SQLite connection.
7. It acquires `BEGIN IMMEDIATE`.
8. It creates `schema_migrations` when needed.
9. It reads the current schema version.
10. It refuses a newer unknown version.
11. It applies each missing migration in order.
12. It commits and closes the connection.
13. The application becomes available.

## 5. Chat request flow

### New conversation

1. `POST /chat` receives `message` and optional `project`.
2. The model router verifies provider configuration.
3. MootOS creates a conversation.
4. The first 80 trimmed characters become the initial title.
5. The user message is saved.
6. Up to 20 recent messages are loaded chronologically.
7. Model instructions are built.
8. The provider generates a response.
9. The assistant response is saved with provider metadata.
10. The API returns the stored messages and conversation ID.

### Provider failure

- Missing provider configuration returns HTTP `503`.
- Provider request failure returns HTTP `502`.
- Missing configuration is checked before a new conversation is created.
- A provider failure after the user message is stored can still leave an unmatched user message. Recovery for that case is not implemented.

## 6. Memory supplied to the model

- Project conversations load memories assigned to that project.
- Unassigned conversations load memories across projects.
- Memories are ordered newest first.
- At most 20 are placed in model instructions.
- Each line includes project, memory type, and content.

Current limitations:

- No keyword or semantic ranking
- No embeddings
- No confidence score
- No detailed source tracking
- No correction chain
- No natural-language remember, forget, or update commands
- No deduplication

## 7. Authentication flow

### Local development

When Railway metadata is absent and both auth variables are absent, auth is disabled.

### Private deployment

When both auth variables are present:

1. Protected browser routes redirect to `/login`.
2. Protected APIs return HTTP `401` without a valid cookie.
3. Correct login creates a signed 30-day cookie.
4. Logout deletes the cookie.

### Railway fail-closed behavior

When Railway metadata is present:

- Both private auth values are required by default.
- Missing both values causes startup failure.
- Public startup requires `MOOTOS_ALLOW_PUBLIC=true`.

Public paths remain login, logout, health, manifest, and static assets.

## 8. Production deployment

- Builder: Railpack
- Server: Uvicorn
- Bind address: `0.0.0.0`
- Port: Railway `PORT`
- Health check: `/health`
- Restart on failure
- One replica
- Volume mount: `/data`
- Database: `/data/mootos.db`

Persistence was manually verified across three deployments before hardening. The hardened deployment requires another smoke test after merge.

## 9. Test coverage

Tests cover:

- Required SQLite PRAGMAs
- Clean migration startup
- Adoption of an existing database without data loss
- Idempotent migrations
- Rejection of newer unknown schema versions
- Foreign-key enforcement
- Concurrent writes
- Memory CRUD and persistence
- Project validation and filtering
- Conversation creation and continuation
- Chat persistence and fake provider behavior
- Auth redirects, login, logout, partial configuration, Railway fail-closed behavior, and public override
- Railway path and configuration
- Mobile interface assets

Known missing areas:

- Automated backup and restore
- Real production migration rehearsal against a copied Railway database
- Provider timeout recovery after saving a user message
- Login rate limiting
- Browser end-to-end tests against Railway

## 10. Intentional boundaries

Version 0.1 remains:

- Single user
- Single Railway replica
- One SQLite database
- One implemented model provider
- Text chat only
- Synchronous provider calls
- No background queue
- No autonomous external actions
- No multi-agent system

WAL and busy timeout improve one-process SQLite behavior. They do not authorize multiple replicas.

## 11. Source of truth

When code and documentation disagree:

1. Code and tests describe runtime behavior.
2. Documentation must be corrected in the same PR that changes behavior.
3. Planned features must remain labeled as planned.
4. A capability is not complete until it is implemented and verified.
