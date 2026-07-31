# MootOS Current Implementation

**Applies to:** Version 0.1 with foundation hardening and production-verified explicit chat memory  
**Purpose:** Describe what the code actually does, separate from future plans.

## 1. Runtime shape

MootOS runs as one FastAPI application process.

Production uses one Railway service and one replica. The same process:

- Serves the mobile web interface
- Handles login and session validation
- Exposes JSON APIs
- Runs schema migrations during startup
- Reads and writes SQLite
- Detects explicit memory-save commands
- Builds model context
- Calls the configured AI provider for normal conversation
- Returns responses to the browser

There are no microservices, background workers, task queues, cache servers, vector databases, or multiple application replicas.

## 2. Current modules

### `backend/main.py`

Responsibilities:

- Creates the FastAPI application
- Mounts frontend static files
- Validates auth configuration during import
- Initializes the database through the migration runner
- Defines request models and routes
- Applies authentication middleware
- Resolves normal conversations and stores normal chat messages
- Routes explicit memory-save commands to the atomic chat-memory storage operation
- Builds model instructions from identity rules and saved memories
- Sends ordinary chat requests to the configured model provider

### `backend/auth.py`

Responsibilities:

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
- Opens every application SQLite connection
- Applies one consistent connection policy
- Provides commit, rollback, close, and row handling

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
- Verifies required tables, columns, and foreign keys
- Rejects an incompatible or newer unknown schema
- Seeds the five default projects during the initial migration

Current migration:

```text
1 — initial_schema
```

### `backend/memory.py`

Responsibilities:

- Creates and lists projects
- Creates, lists, retrieves, filters, and deletes memories
- Validates projects within the same connection used for the operation
- Supplies context memories to the chat system

Memory context rules:

- An unassigned memory is global.
- Global memories are available in every conversation.
- A project-assigned memory is available only in conversations for that project.
- A conversation without a project can load all memories.
- Memories are ordered newest first.

Default projects:

- MootOS
- Studio
- Social Media
- Cars
- Personal

### `backend/memory_commands.py`

Responsibilities:

- Detects clear imperative save commands at the beginning of a message
- Extracts the content that should become long-term memory
- Rejects incomplete phrases and punctuation-only content
- Avoids treating ordinary questions as save commands

Supported command families include:

```text
Remember that ...
Remember ...
Save this ...
Save this to memory: ...
Save to long-term memory: ...
```

The parser is deterministic. It does not ask the model to decide whether a write occurred.

Not supported yet:

- `Forget that ...`
- `Update that ...`
- Vague phrases such as `keep that in mind`
- Automatic extraction of memories from normal conversation

### `backend/chat_memory.py`

Responsibilities:

- Handles the complete explicit-memory chat turn in one SQLite transaction
- Loads or creates the target conversation
- Validates project scope
- Stores the user command
- Stores the `explicit_chat` memory row
- Stores the deterministic assistant confirmation
- Rolls back the complete turn when any insert fails

For a new chat, a failed memory or confirmation write leaves no conversation, message, or memory row. For an existing chat, a failed write leaves the prior conversation unchanged.

### `backend/conversation.py`

Responsibilities:

- Creates and lists conversations
- Loads one conversation and its messages
- Adds user and assistant messages
- Updates conversation timestamps
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

Current external provider:

- OpenAI

Current OpenAI behavior:

- Uses the OpenAI Python SDK
- Uses the Responses API
- Sends instructions separately from conversation messages
- Uses `store=False`
- Returns normalized text, provider, and model metadata

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

The frontend does not contain special memory-command controls. Explicit commands are typed into the normal chat composer.

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
| `project` | Optional project name; `NULL` means global |
| `memory_type` | Optional category; chat saves use `explicit_chat` |
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
| `provider` | Optional provider or internal handler name |
| `model` | Optional model or internal handler version |
| `created_at` | UTC timestamp text |

The messages table has an enforced foreign key to conversations.

## 4. Startup flow

1. Python imports `backend.main`.
2. Auth configuration is validated.
3. Railway without auth values fails unless explicit public access is configured.
4. FastAPI is created.
5. Database initialization delegates to the migration runner.
6. The runner opens a hardened SQLite connection.
7. It acquires `BEGIN IMMEDIATE`.
8. It creates or reads `schema_migrations`.
9. It rejects incompatible or newer unknown schemas.
10. It applies each missing migration in order.
11. It commits and closes the connection.
12. The application becomes available.

## 5. Normal chat request flow

1. `POST /chat` receives `message` and optional `project` or `conversation_id`.
2. The memory-command parser checks the message.
3. When no save command is found, the model router verifies provider configuration.
4. MootOS validates or creates the conversation.
5. The user message is stored.
6. Up to 20 recent messages are loaded chronologically.
7. Relevant global and project memories are added to model instructions.
8. The provider generates a response.
9. The assistant response is saved with provider metadata.
10. The API returns both stored messages and the conversation ID.

Provider failure behavior:

- Missing provider configuration returns HTTP `503` before a new normal conversation is created.
- Provider request failure returns HTTP `502`.
- A provider failure after the user message is stored can leave an unmatched user message.

## 6. Explicit memory-save flow

For a recognized command such as:

```text
Remember that my favorite tea is jasmine.
```

MootOS performs this flow:

1. Extracts `my favorite tea is jasmine.` from the command.
2. Rejects incomplete, punctuation-only, or longer-than-10,000-character content.
3. Opens one SQLite transaction.
4. Validates or creates the conversation inside that transaction.
5. Stores the user's original command.
6. Writes the extracted content to `memories`.
7. Uses the conversation project when one exists; otherwise stores a global memory.
8. Sets `memory_type` to `explicit_chat`.
9. Stores a deterministic assistant confirmation.
10. Commits all records together and returns success.

If conversation creation, the user message, the memory row, or the confirmation fails, the transaction rolls back. No partial explicit-memory chat turn remains.

The explicit save path does not call OpenAI.

Its assistant message records:

```text
provider = mootos
model = memory-command-v1
```

This metadata distinguishes an internal verified action from a model-generated response.

## 7. Cross-chat recall

A memory is not recalled from the old conversation. It is loaded from the `memories` table into the new conversation's model instructions.

Examples:

- A global memory saved in an unassigned chat is available in a later MootOS, Studio, Cars, or Personal chat.
- A memory saved in the Cars project is available in later Cars chats.
- A Cars memory is not supplied to a Studio chat.

At most 20 newest relevant memories are supplied.

Current retrieval limitations:

- No keyword ranking
- No semantic ranking
- No embeddings
- No confidence score
- No correction chain
- No duplicate detection
- No source metadata beyond project, type, and timestamp

## 8. Authentication flow

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

## 9. Production deployment

- Builder: Railpack
- Server: Uvicorn
- Bind address: `0.0.0.0`
- Port: Railway `PORT`
- Health check: `/health`
- Restart on failure
- One replica
- Volume mount: `/data`
- Database: `/data/mootos.db`

Production verification completed on July 31, 2026:

- PR #12 deployed from merged `main`.
- Login and normal chat remained functional.
- An explicit memory command created a durable global memory.
- A brand-new conversation recalled that memory.
- Another Railway rebuild completed.
- A new conversation recalled the same memory after the rebuild.

## 10. Test coverage

Tests cover:

- SQLite PRAGMAs and migrations
- Existing-data preservation and incompatible-schema rejection
- Foreign keys and concurrent writes
- Memory CRUD and persistence
- Project validation and filtering
- Conversation creation and continuation
- Explicit memory-command parsing and boundary variants
- Rejection of incomplete and punctuation-only memory content
- Atomic rollback after forced memory or confirmation write failures
- Save in one chat and recall in a brand-new chat
- Global memory availability and project isolation
- Project-filtered listing behavior
- Model routing for ordinary memory questions
- Memory size validation for new and existing conversations
- Auth, Railway configuration, and mobile interface assets

Known missing areas:

- Natural-language forget and update workflows
- Duplicate and conflict handling
- Memory review UI
- Automated backup and restore
- Provider timeout recovery after saving a user message
- Login rate limiting
- Browser end-to-end tests against Railway

A manual backup and restore procedure is documented in [`MANUAL_BACKUP_AND_RESTORE.md`](MANUAL_BACKUP_AND_RESTORE.md), but an off-volume backup and restore drill have not yet been recorded as complete.

## 11. Intentional boundaries

Version 0.1 remains:

- Single user
- Single Railway replica
- One SQLite database
- One implemented external model provider
- Text chat only
- Synchronous provider calls
- No background queue
- No autonomous external actions
- No multi-agent system

Explicit chat saves are deliberately narrow. MootOS does not silently convert ordinary conversation into permanent memory.

## 12. Source of truth

When code and documentation disagree:

1. Code and tests describe runtime behavior.
2. Documentation must be corrected in the same PR that changes behavior.
3. Planned features must remain labeled as planned.
4. A memory is not considered saved until the complete explicit-memory transaction commits.
