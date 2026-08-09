# MootOS API Reference

**Version:** 0.1 (plus V0.2A Tool System additions below, branch `claude/motos-v0.2a-tool-foundation-u46ew4`, not yet merged to `main`)  
**Applies to:** `main` after PR #30, plus the unmerged V0.2A branch  
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

### `GET /task`
Task viewer/creation UI. Named singular to avoid colliding with the `/tasks` JSON API, matching the existing `/memory` vs `/memories` convention.

### `GET /activity`
Read-only recent-activity UI: recent model Runs, recent Tasks, and recent active memories. Not a scheduler and does not trigger anything.

### `GET /settings`
Read-only current-configuration UI: active model provider, model, and supported schema version. Does not expose secrets and does not allow changing configuration; provider/model are changed through Railway environment variables and a redeploy.

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

**V0.2A (branch only, not yet merged):** when no deterministic command
matches, MootOS also offers the model a small internal Tool System
(`docs/TOOL_SYSTEM.md`). A read-only tool (`projects.list`, `memory.search`,
`tasks.list`) may execute automatically as part of producing the response;
its Run is recorded but nothing about it is returned differently in the
`/chat` response shape below.

If the model instead requests the one write-capable tool
(`tasks.create`), `/chat` returns normally (`200`) but with two additional
fields:

```json
{
  "success": true,
  "data": {
    "conversation_id": "...",
    "project": null,
    "user_message": { "...": "..." },
    "assistant_message": {
      "content": "MootOS prepared \"tasks.create\" and needs your approval before it runs (title: Call Mike). Approve or reject it to continue."
    },
    "provider": "openai",
    "model": "gpt-5-mini",
    "approval_required": true,
    "operation": {
      "id": "...",
      "tool_name": "tasks.create",
      "tool_version": "1",
      "status": "pending",
      "arguments": { "title": "Call Mike" },
      "conversation_id": "...",
      "project": null,
      "created_at": "...",
      "expires_at": "...",
      "decided_at": null,
      "result_run_id": null,
      "result_reference": null,
      "error_class": null
    }
  }
}
```

Nothing has executed at this point. The assistant message is a
deterministic summary, never a claim that the tool already ran. See
`POST /tool-operations/{id}/approve` below to actually run it.

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

Runs are recorded as an internal execution/audit table by normal model-provider attempts. Prompt/response bodies are not duplicated into Run rows.

### `GET /activity/runs`
Read-only listing of recent Run rows (newest first), for the Activity page. Optional `conversation_id` filter and bounded `limit` (1–200, default 50). Never returns prompt/response content.

### `GET /activity/tasks`
Read-only listing of the most recently *created* Tasks (newest first, any status), bounded `limit` (1–200, default 15). Deliberately a separate query from `GET /tasks`, which orders due Tasks before unscheduled ones for the Task viewer — that ordering is not creation recency, so Activity uses its own query rather than relying on it. Does not change `GET /tasks` for its existing callers.

### `GET /activity/memories`
Read-only listing of the most recently saved *active* memories (newest first), bounded `limit` (1–200, default 15), server-side limited. Does not change `GET /memories` for its existing callers, which remains unlimited.

## Tool operations (V0.2A, branch only — not yet merged to `main`)

Reviews and decides model-selected write-tool requests that `/chat`
returned with `approval_required: true`. See `docs/TOOL_SYSTEM.md` §9-10
for the state machine and duplicate/expiry safety.

### `GET /tool-operations`
List pending operations, newest first. Optional `conversation_id` filter and bounded `limit` (1–200, default 50).

### `GET /tool-operations/{operation_id}`
Returns one operation and its current state, including the frozen `arguments`.

### `POST /tool-operations/{operation_id}/approve`
Executes the exact frozen tool call. Returns the operation with `status` set to `succeeded` or `failed` (a failed *execution* is still a `200` — the approval request itself was processed correctly; `error_class` explains the sanitized failure reason). A repeated approve on an already-decided operation returns `409` and does not execute again.

### `POST /tool-operations/{operation_id}/reject`
Marks the operation `rejected`. Executes nothing. A repeated reject, or a reject after approval, returns `409`.

An operation past its `expires_at` fails closed on either endpoint: it is transitioned to `expired` and the request returns `409`.

## Settings

### `GET /settings/status`
Read-only current configuration: `provider`, `model`, `schema_version`, `app_version`. Never returns API keys or other secrets.

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

There is currently no scheduler/reminder API, recurring schedule API, notification-delivery API, or background-job control API. Do not infer these capabilities from the presence of Task `due_at`.

The V0.2A Tool operations API above is an *internal* approval API for the
four registered tools in `docs/TOOL_SYSTEM.md` — it is not a general
external-tool execution API. There is still no calendar, email, GitHub,
filesystem, or shell-command API, and no path for a model or a client to
register a new tool at runtime.
