# MootOS Current Implementation

**Applies to:** `main`, including the merged V0.2A Tool Foundation  
**Last synchronized:** August 9, 2026  
**Schema:** `5 — tool_system`  
**Purpose:** Describe what the running code does now. Historical ADRs and verification records remain valid for their original checkpoints but are not substitutes for this file.

## 1. Runtime shape

MootOS runs as one FastAPI application process. Production uses `backend.application:app` on one Railway service and one replica.

The process:

- serves chat, memory, profile, static assets, login, health, and readiness
- authenticates the private browser session
- runs ordered SQLite migrations at startup
- reads/writes the persistent SQLite database
- handles deterministic memory and Task commands through one ordered `/chat` command dispatcher
- prepares model-backed chat without writing first
- calls the configured model provider
- atomically commits successful normal chat turns
- records model Runs

There is no background worker, task queue, Redis, vector database, scheduler, reminder delivery loop, external-tool executor, or multi-replica coordination system.

## 2. Application composition

### `backend/main.py`

Owns the core FastAPI app, auth/security middleware, health/readiness, memory/project/conversation APIs, the authoritative `/chat` route, ordered deterministic memory/Task command dispatch, model instruction construction, provider calls, and Run integration.

### `backend/application.py`

Is the Railway composition entrypoint. It imports the core app, adds focused feature routers such as profile, Task, activity, and settings APIs, and serves the profile, Task, activity, and settings interface pages. It does not intercept `/chat`; deterministic command routing stays inside the validated/authenticated core chat route.

### `backend/activity_routes.py` and `backend/settings_routes.py`

Add two small, authenticated, read-only route groups. `GET /activity/runs` wraps the existing `backend.runs.list_runs` for the Activity page (recent model-run execution metadata, never prompt/response content). `GET /activity/tasks` wraps a dedicated `backend.tasks.list_recent_tasks` helper that orders strictly by creation time — the existing `GET /tasks` orders due tasks before unscheduled ones (correct for the Task viewer, wrong for an "Activity/recent" label), so Activity uses its own query rather than relying on `/tasks`'s ordering or changing it for its existing consumer. `GET /activity/memories` wraps a dedicated `backend.memory.list_recent_active_memories` helper with a server-side `LIMIT`, so Activity never loads the full active-memory table just to show a handful of items; `GET /memories` itself is unchanged and stays unlimited for the Memory review page. `GET /settings/status` exposes the currently configured model provider, model, and supported schema version (never secrets) for the Settings page. None of this adds durable storage, a settings table, or a mutable configuration path; provider/model configuration remains environment-variable-only.

`/profile`, `/task`, `/activity`, and `/settings` are included in `backend/main.py`'s `HTML_PATHS`, so an unauthenticated browser GET to any of them redirects to `/login` the same way `/chat` and `/memory` already do, rather than depending on the request's `Accept` header.

### `backend/chat_commands.py`

Owns the small ordered dispatcher that decides whether a validated chat message is an explicit deterministic memory command, Task command, or ordinary model-backed chat. Parsers remain pure and domain-specific; the dispatcher only defines their priority and gives future deterministic command families one consistent entry point.

### Frontend

Plain HTML/CSS/JavaScript. The browser talks only to MootOS APIs; provider keys never go to browser JavaScript. Stored private values are rendered using safe text assignment rather than HTML interpretation.

## 3. Storage and schema

SQLite remains the source of truth for durable application state.

Current migrations:

1. `initial_schema`
2. `memory_lifecycle`
3. `model_runs`
4. `tasks`

Current tables:

- `schema_migrations`
- `projects`
- `memories`
- `conversations`
- `messages`
- `runs`
- `tasks`

`backend/migrations.py` owns schema order and compatibility verification.

`backend/db.py` owns connection policy. Connections use foreign keys, WAL mode, `synchronous=NORMAL`, row objects, and busy/connection timeouts. Railway storage fails closed when the expected persistent volume is not available unless an explicit high-risk override is configured.

## 4. Authentication and HTTP boundary

MootOS is single-user and password protected in production.

Current protections include:

- password plus signed-session-secret configuration
- fail-closed Railway auth configuration
- minimum session-secret length
- HTTP-only signed session cookie
- secure cookie on Railway
- process-global failed-login cooldown
- `Cache-Control: no-store` on private/dynamic responses
- `X-Content-Type-Options: nosniff`
- `X-Frame-Options: DENY`
- `Referrer-Policy: same-origin`
- Railway hard-delete disabled by default

`/health`, `/ready`, the login endpoints, manifest, and static assets have intentional public behavior. The application remains single-user; there are no accounts, roles, OAuth identities, or distributed sessions.

## 5. Normal model-backed chat

For ordinary chat:

1. the validated `/chat` request is checked by the ordered deterministic command dispatcher
2. if no deterministic command matches, model configuration is validated
3. the conversation and recent history are prepared without a database write
4. active long-term memories are ranked for context
5. conversation/capability guidance and model-input budgets are applied
6. a model Run is started
7. the provider is called outside a SQLite write transaction
8. on provider success, a short atomic transaction saves the optional new conversation, user message, assistant message, and conversation timestamp
9. the Run is finalized with success metadata and linked message IDs
10. provider/storage failures return sanitized errors and do not commit a half chat turn

Existing conversations are protected by an in-process per-conversation lock. This is intentionally sufficient only for the current one-process/one-replica deployment.

## 6. Model provider and input boundary

The current external provider is OpenAI through `backend/model_router.py`, using the Responses API with provider-side storage disabled.

The provider boundary is replaceable. Code-owned model input includes:

- fixed MootOS identity/capability rules
- conversation guidance
- recent conversation messages
- ranked active memory context

The input budget is deterministic and preserves the current request and fixed instructions while dropping older/less-important optional context first. Diagnostics are count-based and avoid logging private prompt content.

The model is explicitly told not to claim external actions or capabilities the running system does not actually have.

## 7. Long-term memory

### Storage

Memories include content, optional project, memory type/source, lifecycle timestamps, and correction links.

Lifecycle states:

- `active`
- `superseded`
- `archived`

Only active memories enter normal recall.

### Explicit saves

Commands such as `Remember that ...` and `Save this to memory: ...` are parsed deterministically. The complete user-message + memory + confirmation turn is committed in one SQLite transaction and does not call the model provider.

### Intelligent explicit correction

PR #29 added deterministic correction phrases such as:

```text
Actually, my test phrase is green turbo 88. Remember that instead.
```

The parser identifies the correction command. MootOS searches active memory in the allowed scope, requires exactly one strong target, refuses zero/ambiguous matches, and uses the shared memory correction lifecycle.

Correction creates a new active row, marks the prior version superseded, preserves both history links, and keeps the replacement in the original memory scope. Project conversations can correct a unique global memory because global memory is also visible in their context; unrelated other-project memory is excluded from correction targeting.

### Review/archive/restore

The protected memory UI supports search, correction, recoverable archive/forget, and restore. Hard deletion is intentionally constrained and is disabled on Railway by default.

## 8. Memory retrieval

`backend/memory_retrieval.py` performs local deterministic retrieval. It uses literal keywords plus a small reviewed concept/alias layer; literal terms retain stronger weight than alias-only matches.

It does not use embeddings, a vector database, an external retrieval service, or an extra model call.

Project conversations treat projects as focus lenses rather than permanent walls. Active matching-project/global memory is prioritized, relevant other-project memory may match, and unrelated other-project fallback is prevented.

## 9. Curated bootstrap profile

The profile feature provides a protected preview/import workflow for reviewed Version 1 manifests.

It validates a bounded set of entries, canonicalizes projects, detects exact-scope duplicates, separates ready/already-active/blocked entries, and imports the complete accepted batch atomically as `bootstrap_profile` memories.

Real private profile facts are not committed to the repository and the submitted manifest is not sent to the model provider.

## 10. Runs

Migration 3 added `runs` as the execution/audit spine.

A Run records execution metadata such as type, status, provider/model, timestamps, sanitized failure class, optional token/cost metadata, data-exposure classification, and links to conversation/user/assistant message IDs.

Runs intentionally do not duplicate prompt or response content.

Current `run_type` values support `model` and future `tool`; current application integration is primarily model-provider execution. Runs are not Tasks and do not grant execution authority.

## 11. Tasks

Migration 4 added durable Tasks.

Current Task fields:

- `id`
- `title`
- optional `project`
- `status`
- optional `due_at`
- `created_at`
- `updated_at`
- `completed_at`
- `cancelled_at`

Task states are `open`, `completed`, and `cancelled`. Due times, when supplied through the Task API, must be timezone-aware and are normalized to UTC.

Task is intention, not execution authority. The lifecycle prevents a terminal Task from being completed/cancelled again.

## 12. Chat-driven Task creation

PR #30 added deterministic Task creation through normal chat for narrow explicit commands such as:

```text
Create a task to call Mike
Add task: export stems
```

The command parser is deliberately strict to avoid stealing ordinary messages such as `Create a task manager` or `Add task list to the sidebar`.

For a recognized command, the authoritative `/chat` route dispatches to the existing atomic Task-chat writer after normal authentication and `ChatRequest` validation. MootOS resolves/creates the conversation, stores the user message, creates the Task through the shared Task storage logic, stores a deterministic assistant confirmation, and commits the turn atomically. A Task created inside a project conversation inherits that canonical project.

`Remind me ...` is deliberately **not** intercepted because scheduler/reminder delivery does not exist yet.

## 13. Current failure boundaries

- Migrations fail closed on incompatible/newer schemas.
- Railway persistent-storage configuration fails closed.
- Provider failures do not commit a normal chat turn.
- Explicit memory writes/corrections and chat Task creation use atomic database transactions.
- Model Run failures store sanitized exception class rather than raw private error strings.
- Network response loss can remain ambiguous to the browser; automatic blind resend is intentionally avoided.

## 14. What is not implemented

Current code does not provide:

- scheduler/reminder delivery
- recurrence or conditional triggers
- background jobs
- email/calendar/messaging/tool integrations
- approval UI or frozen-operation records
- autonomous tool execution
- multiple Railway replicas
- multi-user accounts/roles
- vector search/embeddings
- automatic long-term-memory extraction from ordinary conversation
- voice or vision

## 15. Next proposed design problem

Scheduler / Reminder v0.1 is the next proposed capability. The design should remain small but must explicitly solve durable due state, timezone semantics, restart recovery, duplicate-fire prevention/idempotency, delivery status, offline catch-up, cancellation/update behavior, and testable time. It must not blur Task (intention), Run (execution record), and future approval/external-action boundaries.

**This section describes the plan as of PR #31.** V0.2A (§16) changed the
actual sequence: a Tool Foundation was built next instead, per ADR-027.
Scheduler/Reminder v0.1 remains the proposed capability after it.

## 16. Tool System (V0.2A — merged to `main`)

**Applies to:** `main`, schema `5 — tool_system`. Merged and live-verified on Railway/OpenAI, including a successful frozen approval → execution → persisted Task. See `docs/TOOL_SYSTEM.md` for the full architecture and ADR-027 for the decision record; this section is a short pointer, not a duplicate.

V0.2A adds a small, explicit, fail-closed Tool System so the model can
invoke a controlled set of internal tools from normal chat, with a
human-approval gate for any write. In module terms:

- `backend/tool_types.py`, `tool_validation.py`, `tool_registry.py`,
  `tools_reference.py`, `tool_executor.py`, `tool_budget.py`,
  `tool_operations.py`, `tool_routes.py`, `tool_conversation.py` — new.
- `backend/model_router.py` — extended with `generate_with_tools` /
  `continue_tool_turn`, normalized `ToolRequest`/`ToolConversationTurn`
  types, and an OpenAI-only opaque continuation state. The existing plain
  `generate()` path is unchanged.
- `backend/runs.py` — extended with `start_tool_run` /
  `finish_tool_run_success` / `finish_tool_run_failure` and new
  `tool_name`/`tool_version` columns (migration 5).
- `backend/main.py`'s `/chat` route — the deterministic memory/Task command
  dispatch (§ above) is unchanged and still runs first. Ordinary
  provider-backed chat now goes through
  `backend.tool_conversation.run_tool_conversation` instead of calling
  `router.generate()` directly; that function falls back to the exact
  previous behavior whenever the tool registry is empty or the configured
  provider does not implement tool calling.

Four tools are registered: `projects.list`, `memory.search`, `tasks.list`
(`read_only`, auto-execute) and `tasks.create` (`internal_write`, requires
explicit approval through `POST /tool-operations/{id}/approve`). A
`high_risk` risk level exists in the taxonomy but has no registered tool in
V0.2A and cannot execute under any circumstance, including approval.

Frozen approval operations (`tool_operations` table) let a human review and
approve/reject the model's exact request; approval can only ever run that
exact frozen call, never fresh arguments. Post-approval model continuation
is not implemented — approving returns a deterministic success/failure
receipt rather than a new model-generated reply. See `docs/TOOL_SYSTEM.md`
§12 for why, and `docs/API_REFERENCE.md` for the exact response shapes.

`frontend/app.js` renders an inline chat approval card
(`frontend/tools.css`) when a chat response carries
`approval_required: true`; `frontend/activity.js` labels tool Runs by tool
name/version in the existing `/activity` feed.
