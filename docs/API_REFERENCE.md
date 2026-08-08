# MootOS API Reference

**Version:** 0.1  
**Applies to:** `main` after PR #30  
**Production app:** `backend.application:app`

All private application/API routes are protected by the signed-session boundary when production auth is configured. `/health`, `/ready`, login/logout, manifest, and static assets have intentional public behavior.

## Health and authentication

### `GET /health`
Minimal liveness response.

### `GET /ready`
Checks that the configured existing database is usable and exactly matches the schema version supported by the running build.

### `POST /auth/login`
Body:

```json
{"password":"..."}
```

Creates the signed browser session after successful authentication. Repeated failures can trigger a temporary process-global cooldown.

### `POST /auth/logout`
Clears the browser session.

## Browser interfaces

### `GET /chat`
Mobile chat UI.

### `GET /memory`
Memory review/search/correct/archive/restore UI.

### `GET /profile`
Curated bootstrap-profile preview/import UI.

## Chat

### `POST /chat`

Body:

```json
{
  "message": "Hello",
  "conversation_id": null,
  "project": null
}
```

Normal messages use the configured model provider. Narrow deterministic commands can instead use internal storage paths without a model call.

Current deterministic write families include:

```text
Remember that ...
Save this to memory: ...
Actually, ... Remember that instead.
Create a task to ...
Add task: ...
```

Task command interception is deliberately strict. `Remind me ...` is not a scheduler command because no reminder-delivery system exists yet.

Normal successful model-backed chat stores the complete user/assistant pair atomically after provider success. Explicit memory and Task writes use their own atomic storage transactions.

## Conversations

### `POST /conversations`

```json
{
  "project": "Studio",
  "title": "Optional title"
}
```

### `GET /conversations`
Optional exact project filter.

### `GET /conversations/{conversation_id}`
Returns one conversation and stored messages.

## Projects

### `GET /projects`
Lists projects.

### `POST /projects`

```json
{
  "name": "New Project",
  "description": "Optional description"
}
```

Project names are unique case-insensitively.

## Memories

### `POST /memories`

```json
{
  "content": "fact",
  "project": null,
  "memory_type": "optional-source"
}
```

### `GET /memories`

Optional query parameters:

```text
status=active|archived
project=<exact existing project>
```

Superseded versions are intentionally excluded from normal listings.

### `POST /memories/search`
Read-only protected search with private terms in the request body:

```json
{
  "query": "search terms",
  "status": "active",
  "project": "Cars"
}
```

### `GET /memories/{memory_id}`
Returns one exact memory version.

### `GET /memories/{memory_id}/history`
Returns a complete correction chain oldest first.

### `POST /memories/{memory_id}/corrections`

```json
{"content":"replacement content"}
```

Creates a new active version and supersedes the selected active version atomically.

### `POST /memories/{memory_id}/archive`
Recoverably removes the selected active memory from normal recall.

### `POST /memories/{memory_id}/restore`
Returns a selected archived latest version to active recall.

### `DELETE /memories/{memory_id}`
Legacy administrative hard-delete path. It refuses lifecycle/history-protected rows and is disabled on Railway by default unless the explicit high-risk override is enabled.

## Bootstrap profile

### `POST /profile/preview`
Validates/classifies a private Version 1 manifest without mutating storage.

Shape:

```json
{
  "version": 1,
  "entries": [
    {"content":"...","project":"Personal"}
  ]
}
```

### `POST /profile/import`
Revalidates and atomically imports ready entries as `bootstrap_profile` memories. Duplicate/conflicting lifecycle states are handled according to the profile-import rules.

## Tasks

### `POST /tasks`
Creates one open Task.

```json
{
  "title": "call Mike",
  "project": "Studio",
  "due_at": "2026-08-09T15:00:00-04:00"
}
```

`due_at` is optional. When present it must be timezone-aware and is normalized to UTC in storage.

### `GET /tasks`
Optional query parameters:

```text
status=open|completed|cancelled
project=<exact existing project>
limit=1..500
```

Due Tasks are ordered before unscheduled Tasks; due timestamps sort ascending.

### `GET /tasks/{task_id}`
Returns one Task.

### `POST /tasks/{task_id}/complete`
Moves one open Task to completed.

### `POST /tasks/{task_id}/cancel`
Moves one open Task to cancelled.

Completed/cancelled Tasks are terminal in Task v0.1.

## Runs

Runs currently exist as an internal execution/audit table rather than a public CRUD surface. Normal model-provider attempts create/finalize Run records containing execution metadata and optional links to saved conversation messages. Prompt/response bodies are not duplicated into Run rows.

## Current schema-related status codes

Common patterns:

- `200` successful read/action
- `201` successful create/import/correction where defined
- `401` authentication required
- `404` missing object/project depending on route
- `409` lifecycle/project conflict
- `422` invalid request/domain validation
- `429` login cooldown
- `502` model provider failure
- `503` provider/storage/readiness unavailable

Exact response details are controlled by route code and may intentionally be sanitized at security/storage/provider boundaries.

## Not an API yet

There is currently no scheduler/reminder API, recurring schedule API, notification-delivery API, external-tool execution API, approval API, or background-job control API. Do not infer these capabilities from the presence of Task `due_at`.
