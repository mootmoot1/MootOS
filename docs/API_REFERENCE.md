# MootOS API Reference

**Applies to:** `feature/memory-forget-v0.1`  
**Authentication:** All routes are protected except the public/login routes listed below.

Successful JSON responses generally use:

```json
{"success": true, "data": {}}
```

Errors use FastAPI’s `detail` field.

## Public and browser routes

### `GET /health`

Returns:

```json
{"status": "healthy"}
```

### `GET /login`

Serves the private login page when authentication is enabled.

### `POST /auth/login`

Request:

```json
{"password": "..."}
```

Creates a signed session cookie after a valid password.

### `POST /auth/logout`

Clears the session and redirects to login.

### `GET /chat`

Serves the chat interface.

### `GET /memory`

Serves the protected memory review, correction, forget, and restore interface.

## Projects

### `GET /projects`

Lists all projects alphabetically.

### `POST /projects`

Request:

```json
{"name": "Cars", "description": "Vehicle notes"}
```

Duplicate names return `409`.

## Memories

A memory version includes:

```json
{
  "id": "uuid",
  "content": "Memory text",
  "project": null,
  "memory_type": "explicit_chat",
  "created_at": "UTC timestamp",
  "status": "active",
  "updated_at": "UTC timestamp",
  "replaces_memory_id": null,
  "superseded_by_id": null
}
```

Lifecycle values:

- `active` — normal listing and model context
- `superseded` — preserved prior correction version
- `archived` — recoverably forgotten and excluded from normal recall

### `POST /memories`

Creates one active memory.

```json
{
  "content": "My favorite tea is jasmine.",
  "project": "Personal",
  "memory_type": "note"
}
```

Unknown project returns `422`.

### `GET /memories`

Lists active memories newest first.

Optional parameters:

```text
status=active|archived
project=<exact project name>
```

Examples:

```text
GET /memories?status=active
GET /memories?status=archived
GET /memories?status=active&project=Cars
```

The default status is `active`. Superseded rows are intentionally unavailable through this list. Unsupported status returns `422`; unknown project returns `404`.

### `GET /memories/{memory_id}`

Returns one exact memory version, including inactive versions. Missing record returns `404`.

### `POST /memories/{memory_id}/corrections`

Creates a new active replacement and supersedes the selected active version atomically.

```json
{"content": "Corrected memory text"}
```

Returns `201`. Blank or oversized input returns `422`; missing returns `404`; unchanged or inactive target returns `409`.

### `GET /memories/{memory_id}/history`

Returns the complete correction chain oldest first. Missing record returns `404`.

### `POST /memories/{memory_id}/archive`

Recoverably forgets one latest active memory version.

The selected row becomes `archived`, disappears from active lists and model context, and remains available in the archived list and history.

Success returns `200`. Missing returns `404`; wrong-state or stale target returns `409`.

### `POST /memories/{memory_id}/restore`

Restores one latest archived memory version to `active`.

Success returns `200`. Missing returns `404`; wrong-state or stale target returns `409`.

### `DELETE /memories/{memory_id}`

Legacy administrative hard delete for one unlinked active standalone memory. It is not exposed in the browser.

Returns `409` for archived, superseded, or correction-linked rows. Missing returns `404`.

This is not the user-facing forget workflow.

## Conversations

### `POST /conversations`

```json
{"project": "Cars", "title": "Vehicle notes"}
```

Creates a persistent conversation. Unknown project returns `422`.

### `GET /conversations`

Lists conversations newest-updated first. Optional `project` filters to one exact project.

### `GET /conversations/{conversation_id}`

Returns one conversation and its messages. Missing returns `404`.

## Chat

### `POST /chat`

```json
{
  "message": "What do you remember about my car?",
  "conversation_id": null,
  "project": "Cars"
}
```

Normal messages:

1. Validate provider configuration.
2. Create or load the conversation.
3. Store the user message.
4. Load recent history and active relevant memories.
5. Call the model provider.
6. Store and return the assistant response.

Explicit save messages beginning with supported `remember` or `save` wording bypass the provider and commit the user message, memory row, and deterministic confirmation in one transaction.

A project mismatch on an existing conversation returns `409`. Missing conversation returns `404`. Provider configuration failure returns `503`; provider request failure returns `502`.

## Browser mutation boundary

The Memory page can send only these memory mutations:

```text
POST /memories/{id}/corrections
POST /memories/{id}/archive
POST /memories/{id}/restore
```

It sends no memory `DELETE`, `PATCH`, or `PUT` request. Stored content and project values are rendered through DOM `textContent`.

## Not implemented

- Natural-language update or forget
- Permanent-delete UI or secure erasure
- Bulk archive/restore
- Keyword or semantic retrieval
- Full browser history viewer
- Multi-user authorization roles
