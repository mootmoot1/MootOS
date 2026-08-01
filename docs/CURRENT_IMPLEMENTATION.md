# MootOS Current Implementation

**Applies to:** Version 0.1 on `feature/memory-forget-v0.1`  
**Production base:** PR #15 merged and production-verified  
**Schema:** `2 — memory_lifecycle`

## Runtime shape

MootOS is one FastAPI process serving the browser interface, authenticated APIs, conversation loop, model-provider boundary, and SQLite persistence. Railway runs one service and one replica with `/data/mootos.db` on a persistent volume.

There are no background workers, queues, caches, vector databases, local models, or multiple replicas.

## Authentication

Private deployment uses one configured password and a signed HTTP-only session cookie. Railway startup fails closed when the required auth values are absent unless the explicit public override is enabled.

The Memory page and all memory lifecycle APIs are protected by the same middleware as chat.

## Database

Every application connection uses the centralized database layer with:

```text
foreign_keys = ON
journal_mode = WAL
synchronous = NORMAL
busy_timeout = 5000 milliseconds
connection timeout = 5 seconds
```

Database path priority:

1. `MOOTOS_DATABASE_PATH`
2. `<RAILWAY_VOLUME_MOUNT_PATH>/mootos.db`
3. `data/mootos.db`

Current migrations:

```text
1 — initial_schema
2 — memory_lifecycle
```

Migration 2 added these memory fields without replacing existing rows:

- `status`: `active`, `superseded`, or `archived`
- `updated_at`
- `replaces_memory_id`
- `superseded_by_id`

Existing rows became active with `updated_at = created_at`.

## Memory creation

Direct API creation and explicit chat saves create active memory rows. Chat saves use type `explicit_chat` and commit the conversation, user message, memory row, and deterministic confirmation together. The explicit save path does not call OpenAI.

## Memory listing and context

`GET /memories` defaults to active rows. The branch also accepts:

```text
GET /memories?status=active
GET /memories?status=archived
```

Superseded rows are not available through normal lists. They remain accessible through direct retrieval and correction history.

Only active rows enter model context:

- No-project chat can load all active memory.
- A project chat currently loads active global memory plus active memory from that project.
- Later retrieval work may rank relevant cross-project memories because projects are focus lenses, not secrecy walls.

## Correction

Correction is append-and-supersede:

1. Start `BEGIN IMMEDIATE`.
2. Reload and require the selected row to be active.
3. Reject blank or unchanged content.
4. Insert a new active row preserving project and type.
5. Link it backward through `replaces_memory_id`.
6. Mark the prior row superseded and link it forward.
7. Commit both changes or roll back.

The history API walks the complete chain oldest first and detects broken or cyclic links. Correction-linked rows cannot be hard-deleted.

## Recoverable forget and restore

This branch adds lifecycle operations without a new migration.

### Archive / forget

`POST /memories/{memory_id}/archive`:

- Starts `BEGIN IMMEDIATE`
- Requires the exact row to exist
- Requires it to be the latest active version
- Changes status to `archived`
- Updates `updated_at`
- Commits atomically

Archived memories disappear from active lists and model context immediately.

### Restore

`POST /memories/{memory_id}/restore`:

- Starts `BEGIN IMMEDIATE`
- Requires the exact row to exist
- Requires it to be the latest archived version
- Changes status to `active`
- Updates `updated_at`
- Commits atomically

Restored memories return to active lists and model context.

Archive and restore do not alter correction links. A correction chain can end with either an active or archived latest version.

## Browser Memory page

The protected `/memory` page provides:

- Active and Archived views
- All, Global only, and exact-project scope filters
- Memory content, scope, project, source, version, status, and date
- **Correct** and **Forget** controls on active rows
- **Restore** on archived rows
- Explicit dialogs showing the selected memory before mutation
- Disabled controls while requests are running
- Loading, empty, success, and error states
- Stale-request generation protection
- Clear notice that forgetting is recoverable

Database-provided text is inserted through `textContent`. The browser uses explicit `POST` requests for correction, archive, and restore and contains no memory `DELETE`, `PATCH`, or `PUT` request.

## Legacy hard delete

`DELETE /memories/{memory_id}` remains an administrative API and is not exposed in the browser. It can delete only an unlinked active standalone row. It refuses to delete:

- Superseded rows
- Archived rows
- Any row linked into correction history

This endpoint is not the user-facing forget workflow.

## Conversation behavior

Normal chat stores user and assistant messages, loads recent history, supplies up to twenty active relevant memories, calls the configured provider, and stores provider/model metadata.

Provider-side response storage is disabled; MootOS owns its conversation and memory records.

## Verification coverage

The branch test suite covers:

- Existing migrations and schema verification
- Explicit save atomicity
- Correction chains, rollback, concurrency, and active-only context
- Archive exclusion from lists and model context
- Archived listing and restore
- Archive/restore preservation of correction history
- Missing and wrong-state conflicts
- Forced archive and restore rollback
- Competing lifecycle requests
- Hard-delete protection
- Authentication
- Confirmed UI controls and safe rendering
- Absence of browser permanent-delete methods

Local result: 83 tests passed, Python compilation passed, and JavaScript syntax validation passed.

## Intentional boundaries

Not implemented on this branch:

- Natural-language forget or update
- Permanent-delete UI or secure erasure
- Bulk lifecycle actions
- Keyword or semantic retrieval
- Duplicate detection
- Full history viewer
- Automated backup scheduling or retention
- Runtime tools or multi-agent behavior
