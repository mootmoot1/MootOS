# MootOS Current Implementation

**Applies to:** Version 0.1 on `feature/memory-forget-v0.1`  
**Production base:** PR #15 merged and production-verified  
**Schema:** `2 — memory_lifecycle`  
**Purpose:** Describe what the code actually does, separate from future plans.

## 1. Runtime shape

MootOS runs as one FastAPI application process.

Production uses one Railway service and one replica. The same process:

- Serves the mobile chat and memory interfaces
- Handles login and session validation
- Exposes JSON APIs
- Runs schema migrations during startup
- Reads and writes SQLite
- Detects explicit memory-save commands
- Builds model instructions from active memories
- Calls the configured AI provider for normal conversation
- Handles correction, archive, and restore internally without a model call
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
- Serves the protected `/chat` and `/memory` interfaces
- Resolves normal conversations and stores normal chat messages
- Routes explicit memory-save commands to the atomic chat-memory operation
- Exposes memory correction, history, archive, and restore APIs
- Validates active or archived list status
- Builds model instructions from identity rules and active saved memories
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
- Verifies required tables, columns, status values, and foreign keys
- Rejects an incompatible or newer unknown schema
- Seeds the five default projects during the initial migration

Current migrations:

```text
1 — initial_schema
2 — memory_lifecycle
```

Migration 2 adds:

```text
status
updated_at
replaces_memory_id
superseded_by_id
```

Existing memories are preserved, set active, and receive `updated_at = created_at`. The forget branch reuses schema 2 and adds no migration 3.

### `backend/memory.py`

Responsibilities:

- Creates and lists projects
- Creates, lists, retrieves, filters, and protects memories
- Validates projects inside the same connection used for the operation
- Supplies active context memories to the chat system
- Corrects an active memory through append-and-supersede
- Traverses correction history
- Archives one exact latest active memory
- Restores one exact latest archived memory
- Prevents hard deletion from breaking history or recoverability

Memory lifecycle values:

- `active`
- `superseded`
- `archived`

Normal active-memory context rules:

- An unassigned memory is global.
- Global active memories are available in every project conversation.
- A project conversation currently loads active global memory plus active memory assigned to that project.
- A conversation without a project can load all active memories.
- Projects are intended as focus lenses, not permanent secrecy walls.
- Active context is ordered newest first.
- Archived and superseded rows never enter ordinary model context.

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

Not supported:

- Natural-language `Forget that ...`
- Natural-language `Update that ...`
- Vague phrases such as `keep that in mind`
- Automatic extraction of memories from normal conversation

### `backend/chat_memory.py`

Responsibilities:

- Handles the complete explicit-memory chat turn in one SQLite transaction
- Loads or creates the target conversation
- Validates project focus
- Stores the user command
- Stores the active `explicit_chat` memory row
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

The chat interface provides:

- Login and logout
- User and assistant message bubbles
- Text composer
- Project selection
- New conversation control
- Saved conversation history
- Loading and error states
- Installable web-app metadata
- A Memories control linking to `/memory`

The Memory interface provides:

- A protected page at `/memory`
- Active and Archived views
- All, Global-only, and exact-project scope filters
- Memory content
- Global or project scope
- Project name
- Memory type or source label
- Original or corrected version label
- Active or archived status
- Creation date
- **Correct** and **Forget** on active memory cards
- **Restore** on archived memory cards
- Explicit dialogs displaying the selected memory
- Refresh, loading, empty, success, and error states
- A direct return link to chat

The browser creates DOM nodes and assigns database values through `textContent`. It does not render saved memory content as HTML.

The browser can send only explicit `POST` mutations for correction, archive, and restore. It contains no memory `DELETE`, `PATCH`, or `PUT` request.

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
| `created_at` | Original version timestamp |
| `status` | `active`, `superseded`, or `archived` |
| `updated_at` | Latest lifecycle-change timestamp |
| `replaces_memory_id` | Prior version replaced by this row |
| `superseded_by_id` | Newer version that replaced this row |

The correction self-links are application-managed. SQLite cannot add those self-referential constraints to the existing table through a simple `ALTER TABLE` migration.

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
11. It verifies schema 2.
12. It commits and closes the connection.
13. The application becomes available.

## 5. Normal chat request flow

1. `POST /chat` receives `message` and optional `project` or `conversation_id`.
2. The memory-command parser checks the message.
3. When no save command is found, the model router verifies provider configuration.
4. MootOS validates or creates the conversation.
5. The user message is stored.
6. Up to 20 recent messages are loaded chronologically.
7. Up to 20 active relevant memories are added to model instructions.
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

1. Extracts the memory content.
2. Rejects incomplete, punctuation-only, or longer-than-10,000-character content.
3. Opens one SQLite transaction.
4. Validates or creates the conversation inside that transaction.
5. Stores the user's original command.
6. Writes the extracted content to `memories` as active.
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

## 7. Correction flow

Correction is not an in-place edit.

1. Moot selects one active memory and confirms corrected content.
2. The backend starts `BEGIN IMMEDIATE`.
3. It reloads the selected row inside the transaction.
4. It rejects a missing, inactive, blank, or unchanged correction.
5. It inserts a new active row preserving project and memory type.
6. It links the new row backward through `replaces_memory_id`.
7. It marks the old row superseded and links it forward through `superseded_by_id`.
8. Both changes commit or both roll back.

Normal lists and model context use only the active replacement. `GET /memories/{id}/history` returns the complete chain oldest first and detects cycles or broken links.

## 8. Recoverable forget flow

1. Moot selects one active memory and presses **Forget**.
2. The dialog displays the exact selected content and explains recoverability.
3. After confirmation, the browser posts to `/memories/{id}/archive`.
4. The backend starts `BEGIN IMMEDIATE`.
5. It reloads the row and requires it to remain the latest active version.
6. It changes status to archived and updates `updated_at`.
7. The transaction commits or rolls back.
8. The browser reloads the active list.

Archived rows immediately leave active lists and model context. The row is not deleted, and correction links remain unchanged.

## 9. Restore flow

1. Moot switches the Memory page to Archived.
2. Moot selects one archived row and presses **Restore**.
3. The dialog displays the exact selected content.
4. After confirmation, the browser posts to `/memories/{id}/restore`.
5. The backend starts `BEGIN IMMEDIATE`.
6. It reloads the row and requires it to remain the latest archived version.
7. It changes status to active and updates `updated_at`.
8. The transaction commits or rolls back.
9. The browser reloads the archived list.

The same row returns to normal active listings and model context.

## 10. Listing behavior

`GET /memories` defaults to active rows.

Supported status values:

```text
active
archived
```

Superseded rows are intentionally available only through direct retrieval and correction history.

For an exact project filter, the API returns only rows assigned to that project. The browser's Global-only filter loads the selected lifecycle list and displays rows whose project is `NULL`.

## 11. Hard-delete boundary

The legacy `DELETE /memories/{id}` endpoint is not exposed in the browser.

It can delete only a standalone unlinked active row. It rejects:

- Archived rows
- Superseded rows
- Rows with `replaces_memory_id`
- Rows with `superseded_by_id`

This prevents permanent deletion from breaking correction history or recoverability.

## 12. Authentication flow

### Local development

When Railway metadata is absent and both auth variables are absent, auth is disabled.

### Private deployment

When both auth variables are present:

1. Protected browser routes, including `/chat` and `/memory`, redirect to `/login`.
2. Protected APIs return HTTP `401` without a valid cookie.
3. Correct login creates a signed 30-day cookie.
4. Logout deletes the cookie.

### Railway fail-closed behavior

When Railway metadata is present:

- Both private auth values are required by default.
- Missing both values causes startup failure.
- Public startup requires `MOOTOS_ALLOW_PUBLIC=true`.

## 13. Production deployment

- Builder: Railpack
- Server: Uvicorn
- Bind address: `0.0.0.0`
- Port: Railway `PORT`
- Health check: `/health`
- Restart on failure
- One replica
- Volume mount: `/data`
- Database: `/data/mootos.db`

Production verification completed for correction on August 1, 2026:

- Migration 2 deployed.
- Existing data remained available.
- A selected active memory was corrected.
- A new conversation recalled only the corrected active value.
- Another Railway rebuild completed.
- A new conversation recalled the corrected value again.

Forget and restore remain branch-only until PR #16 is reviewed, merged, deployed, and manually tested.

## 14. Test coverage

Tests cover:

- SQLite PRAGMAs and migrations
- Existing-data preservation and incompatible-schema rejection
- Foreign keys and concurrent writes
- Memory CRUD and persistence
- Project validation and filtering
- Conversation creation and continuation
- Explicit memory-command parsing and boundary variants
- Atomic explicit-save rollback
- Save in one chat and recall in a brand-new chat
- Active-only model context
- Migration 2 existing-row preservation
- Atomic append-and-supersede correction
- Correction history and multi-step chains
- Competing corrections and forced rollback
- Hard-delete protection for correction chains
- Archive exclusion from active listings and model context
- Archived listing with project filtering
- Restore returning the same row to active
- Correction history preservation through archive and restore
- Missing and wrong-state archive/restore conflicts
- Forced archive and restore rollback
- Competing archive and restore requests
- Hard-delete protection for archived rows
- Endpoint authentication
- Protected memory routing
- Browser request shapes and safe rendering
- Absence of browser memory `DELETE`, `PATCH`, and `PUT`

Local branch result:

- 83 tests passed.
- Python bytecode compilation passed.
- JavaScript syntax validation passed.

Known missing areas:

- Natural-language forget and update
- Permanent-delete or secure-erasure UI
- Keyword or semantic retrieval
- Duplicate detection
- Full browser correction-history viewer
- Automated backup and restore scheduling
- Provider timeout recovery after saving a user message
- Login rate limiting
- Browser end-to-end tests against Railway

## 15. Intentional boundaries

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

Correction, archive, and restore are deliberately UI-selected and confirmed. The browser does not offer permanent deletion, and archived data still exists in SQLite.

## 16. Source of truth

When code and documentation disagree:

1. Code and tests describe runtime behavior.
2. Documentation must be corrected in the same PR that changes behavior.
3. Planned features must remain labeled as planned.
4. A memory is not considered saved until the complete explicit-memory transaction commits.
5. A memory is not considered forgotten until the archive transaction commits.
