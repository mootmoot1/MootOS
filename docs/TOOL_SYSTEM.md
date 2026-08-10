# MootOS Tool System (V0.2A, extended in V0.3A)

**Status:** V0.2A implemented and merged to `main`. Live-verified on Railway/OpenAI, including a successful frozen approval → execution → persisted Task. V0.3A's capability-aware metadata and generated catalog/manifest (Sec16) and V0.3B's structured gap reasoning (`docs/GAP_REASONING.md`) are both implemented and merged on top of it. V0.3C's three read-only tools -- `self.state`, `self.architecture` (`docs/SELF_INSPECTION.md`), and `web.search` (`docs/WEB_AWARENESS.md`) -- are implemented on branch `claude/v0.3c-self-inspection-web-awareness`, pending merge.
**Schema:** `5 — tool_system` (V0.3A added no migration -- its metadata lives on `ToolDefinition` in code, not in the database.)
**Applies to:** the Tool System added in V0.2A on top of the V0.1 foundation (PR #34), plus the V0.3A capability catalog described in Sec16.

This document describes what the Tool System *is*, how the pieces fit
together, and the safety rules that hold regardless of which tool is
involved. It complements — and does not replace — `docs/API_REFERENCE.md`
(exact routes/payloads) and `docs/CURRENT_IMPLEMENTATION.md` (whole-app
runtime map).

## 1. What problem this solves

MootOS V0.1 could talk, remember, and track Tasks, but the model could never
*do* anything inside MootOS's own data. V0.2A adds a narrow, controlled path
from "the model asked for something" to "MootOS safely did it (or asked a
human first)":

```text
user request
  -> conversation/model reasoning
  -> tool selection
  -> registry validation
  -> permission check
  -> execution OR approval request
  -> tool result
  -> model response
  -> execution receipt (Run)
```

This is intentionally **not** general automation. It is a small, explicit
port that future integrations (Calendar, Gmail, GitHub, files, studio tools)
can plug into later without redesigning the conversation engine, the Run
audit trail, or the permission model. V0.2A ships exactly four tools; see
§7.

## 2. Module map

Every module below is a flat file in `backend/`, matching this repository's
existing convention (topic-named modules, not subpackages).

| Module | Responsibility |
| --- | --- |
| `backend/tool_types.py` | The contract: `ToolDefinition`, `ToolExecutionContext`, `ToolRequest`, `ToolResult`, the risk taxonomy, and every Tool System exception. A dependency-free leaf module — everything else imports from here. |
| `backend/tool_validation.py` | A small dependency-free JSON-Schema-lite validator for tool arguments. |
| `backend/tool_registry.py` | Explicit, deterministic tool registration (`ToolRegistry`), plus the process-wide default registry singleton. |
| `backend/tools_reference.py` | The four V0.2A reference tools, each a thin adapter over an existing domain helper. |
| `backend/tool_executor.py` | The single centralized executor: resolve, validate, authorize, Run-log, execute, normalize, sanitize. |
| `backend/tool_budget.py` | Centralized per-turn tool-call budget / loop protection. |
| `backend/tool_operations.py` | The frozen-approval-operation state machine for write tools. |
| `backend/tool_routes.py` | Authenticated HTTP API for reviewing/approving/rejecting operations. |
| `backend/tool_conversation.py` | The bounded model ↔ Tool System conversation loop used by normal chat. |
| `backend/model_router.py` (extended) | Normalized `ToolRequest`/`ToolConversationTurn` boundary; OpenAI-native tool-call shapes stay inside `OpenAIProvider`. |
| `backend/runs.py` (extended) | `start_tool_run` / `finish_tool_run_success` / `finish_tool_run_failure`, and new `tool_name`/`tool_version` Run columns. |
| `backend/migrations.py` (extended) | Migration 5: `tool_name`/`tool_version` on `runs`, new `tool_operations` table. |

## 3. Tool Definition / Contract

Every tool is one `ToolDefinition` (frozen dataclass):

```text
name             stable, dotted, e.g. "tasks.create"
version          string, e.g. "1"
description      shown to the model in the safe catalog
input_schema     JSON-Schema-lite object (see backend/tool_validation.py)
risk             read_only | internal_write | high_risk
data_exposure    local | model_provider | tool_external (reused from backend/runs.py)
executor         Callable[[arguments: dict, context: ToolExecutionContext], dict]

-- V0.3A descriptive metadata (see §16); never read by execution/permission code --
capabilities     tuple[str, ...] = ()     semantic capability/category reference(s)
side_effects     str = ""                 what calling this tool actually does
idempotent       Optional[bool] = None    None only for undocumented test fixtures
limitations      str = ""                 short, truthful limitation statement
depends_on       tuple[str, ...] = ()     other tool names this one depends on
```

Production `ToolDefinition`s are expected to declare the V0.3A descriptive
metadata explicitly and truthfully (see §16); the permissive empty/`None`
defaults above exist primarily so legacy and test fixtures can stay
lightweight, not as an acceptable state for a real registered tool. This is
a documentation expectation only — nothing in `backend/tool_registry.py`
or `backend/tool_executor.py` currently enforces it.

`executor` is a plain Python callable selected by direct reference at
registration time (see §7) — never resolved from a model-supplied string,
never a dynamic import. Tools never see or produce provider-native
structures; that translation happens once, only inside
`backend/model_router.py` (see §9).

`ToolDefinition.to_catalog_entry()` returns the safe, JSON-serializable
subset exposed to a model or an API client — `executor` is never included.
As of V0.3A this also includes the five descriptive fields above; see §16
for how `backend/capability_catalog.py` uses them. `backend/model_router.
py`'s `_build_function_tools` still reads only `name`/`description`/
`input_schema` from a catalog entry when building the OpenAI function-tool
schema — the new fields never reach the provider.

**`format: "utc-datetime"` (live-approval-testing fix).** `due_at` on
`tasks.create` is declared `{"type": "string", ..., "format":
"utc-datetime"}`. `backend.tool_validation` recognizes this one format and
validates/normalizes it via `backend.time_utils.normalize_optional_utc_datetime`
— the exact same rule the existing Task system already enforces at storage
time — so an invalid value (a textual placeholder like `"none"`/`"null"`/
`"unknown"`, a malformed string, or a timezone-naive datetime) is a
`ToolValidationError` at the same generic argument-validation step every
tool already goes through, before the risk/approval branch is ever reached.
Live approval testing had found the model sending `due_at: "none"` as a
stand-in for "no due time"; the old schema only checked `minLength`, so it
passed validation, froze into a pending approval operation, and only failed
once approved (Task storage's own, unweakened, unchanged validation). A
valid value is normalized to UTC *before* being frozen, so the operation a
human reviews already shows the exact value that will be stored. See §12.

## 4. Tool Registry

`backend.tool_registry.ToolRegistry`:

- `register(definition)` — raises `DuplicateToolError` on a repeated name.
- `get(name)` — raises `ToolNotFoundError` for anything not registered.
  **Unknown tools fail closed**; there is no fallback execution path.
- `list_definitions()` / `catalog()` — deterministic, name-sorted output.

`build_default_registry()` calls exactly one explicit function
(`tools_reference.register_reference_tools`) that registers the four
reference tools by direct reference. There is no plugin discovery, no
filesystem scanning, and no way for a request or a model to add a tool at
runtime. `get_tool_registry()` is a lazily-built, thread-safe, process-wide
singleton; `reset_tool_registry()` exists only for tests.

## 5. Permission / Risk Policy

```text
RISK_READ_ONLY       may execute automatically
RISK_INTERNAL_WRITE  requires explicit human approval; never auto-executes
RISK_HIGH_RISK       never executes at all in V0.2A — no exceptions
```

Risk is a property of the **registered** `ToolDefinition`, decided by the
person who wrote the tool — never by model-supplied arguments, never
inferred at call time. Two independent layers enforce this:

1. `backend.tool_conversation` (the model-facing loop) routes an
   `internal_write` request straight to the approval flow and never calls
   the executor for it directly.
2. `backend.tool_executor.execute_tool` enforces the exact same rule again,
   defensively: it raises `ToolPermissionError` for an unapproved
   `internal_write` call, and **unconditionally** for any `high_risk` tool,
   even one somehow marked `approved=True`. No real high-risk tool is
   registered in V0.2A; this is architecture proven closed before one ever
   exists.

The deterministic Task-creation chat command (`Create a task to ...`,
unchanged from V0.1) is a separate, pre-existing, explicit user-command
path. It is not reinterpreted by the Tool System and does not go through
`tasks.create`'s approval gate — that gate exists specifically for
*model-selected* tool calls.

## 6. Tool Call Budget / Loop Protection

`backend.tool_budget.ToolCallBudget`, created fresh per chat turn:

```text
MAX_TOOL_CALLS_PER_TURN        = 5   (centralized; the only cap that matters)
MAX_IDENTICAL_CALLS_PER_TURN   = 2   (repeated identical (tool, arguments))
MAX_CONSECUTIVE_FAILURES       = 2   (stops a failing loop before the hard cap)
```

A tool name that does not resolve, or arguments that fail validation, still
count as an attempt for budget purposes (`OUTCOME_UNKNOWN_TOOL` /
`OUTCOME_ERROR`) — a model that keeps guessing at nonexistent tools or
malformed arguments is stopped by the consecutive-failure rule well before
it could exhaust the full 5-call budget. A run of clean *successes* is still
hard-capped at 5.

**Precise guarantee — two different numbers.** `ToolCallBudget.total_calls`
counts every tool *request* the loop finishes processing this turn,
including one the budget itself denies (`OUTCOME_SKIPPED`: the duplicate-
call cap or the hard cap already reached). `ToolCallBudget.executions`
counts only requests that actually reached a tool's executor and ran. "At
most 5 tool executions per user turn" refers to `executions`; `total_calls`
is the number that is actually capped at 5 and is what guarantees the loop
terminates at all. This distinction matters: a denied request that were
left *unrecorded* would never advance `total_calls`, so the loop's
per-batch `allow_next()` check would never trip, and a model that kept
re-requesting an already-capped duplicate call could bounce the loop
through an unbounded number of rounds. Recording every processed request —
skipped or not — closes that gap; see `tests/test_tool_conversation.py`'s
`test_repeated_duplicate_calls_terminate_instead_of_looping_forever` and
`test_single_turn_with_more_tool_calls_than_remaining_budget`.

When the budget is exhausted mid-turn, the loop asks the provider for one
final, honest, tools-disabled answer (`continue_tool_turn(..., force_text=True)`)
so the user gets a real closing response instead of a mid-sentence cutoff.
If that request also fails, a fixed, deterministic fallback message is used
instead — the loop never leaves the user without *some* answer, and it
never silently continues past the cap.

## 7. Tool Execution

`backend.tool_executor.execute_tool` is the **only** function allowed to
invoke a tool's executor callable. Every call — including one that fails to
resolve, validate, or gain permission — does all of:

1. resolve the tool from the registry (fail closed if unknown)
2. validate arguments against the registered schema
3. check permission (risk vs. `context.approved`)
4. start a Run (`run_type = "tool"`)
5. call the executor
6. finalize the Run (`succeeded` or `failed`, sanitized)
7. return a normalized `ToolResult`

Errors reaching the model/user are sanitized: `ToolNotFoundError`,
`ToolValidationError`, `ToolPermissionError`, and `ToolExecutionError` carry
only safe text (domain-validation messages like "Project does not exist"
are fine; raw internal exception text is not). Any *unexpected* exception is
wrapped into a fully generic `ToolExecutionError` before it is ever shown —
the real exception's class name (never its message) is the only thing
persisted, and only to the Run's `error_class`.

**Early rejections also get a Run.** A request the conversation loop
rejects *before* ever calling `execute_tool` — an unknown tool name, a
schema-validation failure, or a `high_risk` refusal — still produces a
terminal `failed` tool Run, via the same centralized helper,
`backend.tool_executor.record_rejected_tool_attempt`. This is the one other
place (besides `execute_tool` itself) allowed to write a tool Run row, so
neither the conversation loop nor the approval flow duplicates Run SQL, and
neither risks writing two Run rows for one attempt — a request handled by
this helper is never subsequently passed to `execute_tool`. It resolves the
live tool version/data-exposure when the name is registered, and fails
closed to `tool_version = None` / `data_exposure = local` when it is not.
It is also reused by `backend.tool_operations.approve_operation` for an
approval that turns out to name an unregistered tool or a tool whose
version has since changed (§9) — those rejections are audited the same way.

## 8. Tool Runs / Audit Trail

Extends the existing `runs` table (unchanged `RUN_TYPE_TOOL`,
`RUN_STATUS_*`, `DATA_EXPOSURE_*` from V0.1) rather than creating a second
logging system. Migration 5 adds two nullable columns: `tool_name`,
`tool_version`. They are new columns, not repurposed `provider`/`model`
columns — those describe an AI model provider, not a tool, and overloading
them would make Run rows misleading (see ADR-027).

A Tool Run records: `id`, `run_type = "tool"`, `status`, `conversation_id`,
`tool_name`, `tool_version`, `started_at`, `finished_at`, `duration_ms`,
`error_class`, `data_exposure`. It never records tool arguments, memory
content, prompt/response bodies, or credentials. `backend.activity_routes`
already exposed `GET /activity/runs` for all Runs; it needed no backend
change to include tool Runs — only `frontend/activity.js` was updated to
label a `run_type == "tool"` row by tool name/version instead of
provider/model.

## 9. Approval Operations

`backend.tool_operations` freezes exactly what a model asked to run before
any human review happens.

```text
pending --> executing --> succeeded
   |            |
   |            `-------> failed
   |
   |--> rejected   (nothing executes)
   `--> expired     (nothing executes)
```

A frozen operation stores: `id`, `tool_name`, `tool_version`, validated
`arguments` (JSON), `conversation_id`, `project`, `created_at`,
`expires_at` (default 24h; `ttl_seconds=None` disables expiry),
`decided_at`, `status`, `result_run_id`, `result_reference`, `error_class`.

**Approval executes only the frozen call.** `approve_operation(operation_id)`
accepts *only* an operation ID — there is no argument parameter anywhere in
its signature — so nothing downstream of a human's approval click can alter
what runs.

**Approval is also pinned to the frozen tool version.** After the claim
(below) and before calling `execute_tool`, `approve_operation` re-resolves
the *currently* registered tool by name and requires
`live_definition.version == claimed["tool_version"]`. If the tool has been
unregistered since the operation was created, or its registered version has
since changed, the operation is finalized `failed` (`ToolNotFoundError` or
`ToolVersionMismatchError`) and **nothing executes** — the human reviewed
one specific version of this call, and a registry change between creation
and approval must never let a different version run silently. Both
rejections are also recorded as a Run via
`record_rejected_tool_attempt` (§7). See
`tests/test_tool_operations.py`'s
`test_approval_refuses_a_changed_tool_version_and_executes_nothing` and
`test_approval_refuses_a_removed_or_unregistered_tool_and_executes_nothing`.

**Duplicate-safety.** `executing` is a short-lived claimed state written by
an atomic `UPDATE tool_operations SET status = 'executing' WHERE status =
'pending'`. Only the first concurrent approval request can win that
claim; a retry or double-click on an already-decided operation gets a `409`
and executes nothing. If the process crashes between the claim and the
terminal write, the operation is left stuck in `executing` rather than
risking a duplicate write — an accepted, detectable-and-repairable
tradeoff, the same one already used for a "started" Run row elsewhere in
this codebase (`backend/main.py`'s `_safe_finish_failed_run`).

**Expiry is fail-closed.** A stale `pending` operation is transitioned to
`expired` in its own committed transaction *before* the approve/reject
attempt is refused — so a crash or an exception raised right after does not
roll the expiry back and leave the row looking falsely reusable.

## 10. Approval HTTP API

```text
GET  /tool-operations                 list pending operations
GET  /tool-operations/{id}            one operation and its current state
POST /tool-operations/{id}/approve    execute the frozen operation once
POST /tool-operations/{id}/reject     mark rejected; executes nothing
```

Protected by the same session middleware as every other private route (see
`docs/API_REFERENCE.md`). See §12 for the response shape and the chat card
that triggers it.

## 11. Model Provider / Tool Selection Boundary

`backend/model_router.py` gained a normalized tool-calling extension
without touching the plain-text `generate()` path other code already
depends on:

```text
ModelRouter.generate_with_tools(messages, instructions, tools) -> ToolConversationTurn
ModelRouter.continue_tool_turn(state, tool_results, ...)       -> ToolConversationTurn
```

`ToolConversationTurn` and `ToolRequest`/`ToolResult` are the only types
that cross this boundary. `state` is opaque — callers must pass it back
unmodified and must never inspect it. Inside `OpenAIProvider`, that opaque
state (`_OpenAIToolState`, module-private) holds the raw OpenAI Responses
API `input` item list (including `function_call` output items), which is
exactly the shape a future non-OpenAI provider would never need to know
about. `_build_function_tools` is the only place a MootOS `ToolDefinition`
catalog entry becomes an OpenAI `{"type": "function", ...}` object.

**Dotted MootOS tool names never reach the OpenAI API directly.** MootOS
tool names are stable and dotted (`tasks.create`); OpenAI function-tool
names must not contain `.` — a live Railway/OpenAI request with a dotted
function name is rejected outright. `_encode_tool_name`/`_decode_tool_name`
are a small, deterministic, reversible escape used only inside
`OpenAIProvider` (`_build_function_tools` encodes outgoing names;
`_parse_tool_response` decodes incoming ones before ever constructing a
`ToolRequest`), so every other module still only ever sees the real dotted
name. It escapes `_` as `_u` and `.` as `_d` — not a plain `.` → `_`
substitution, which would let two different names (e.g. `"a_b"` and
`"a..b"`) collide on the same encoded string. A decoded name that fails to
parse, or that doesn't match one of the tools actually offered on that
specific request, is rejected as unknown/unmappable — fail closed, never
guessed at. See `tests/test_model_router_tool_parsing.py`.

`ModelRouter.supports_tools()` is a duck-typed capability probe. The
conversation loop (`backend.tool_conversation._router_supports_tools`)
checks it defensively (`getattr(..., "supports_tools", None)`, falling back
to checking for `generate_with_tools` directly) so a minimal router double
implementing only `generate()` — exactly what every pre-existing V0.1 chat
test already used — is routed to the unchanged plain-text path instead of
raising `AttributeError`. This is also what lets a future provider that
never implements tool calling degrade to plain chat instead of breaking
`/chat` outright.

**Every parsed tool call must carry a usable `call_id`.** `call_id` is how
a tool result is matched back to the model's own request on the next turn
(`continue_tool_turn`'s `function_call_output` items). `OpenAIProvider`'s
response parser (`_parse_tool_response`) raises `ModelProviderError` and
refuses the whole turn — rather than continue with an ambiguous mapping —
if any parsed `function_call` item has a missing/empty `call_id`, or if two
items in the same turn share a `call_id`. See
`tests/test_model_router_tool_parsing.py`.

## 12. Tool Conversation Loop

`backend.tool_conversation.run_tool_conversation` is called from
`backend/main.py`'s `/chat` route **after** the existing deterministic
memory/Task command dispatch (unchanged — see
`docs/CURRENT_IMPLEMENTATION.md` §5). It:

1. Falls back to plain `router.generate()` immediately when the registry is
   empty or the provider does not support tools — zero behavior change for
   that case.
2. Otherwise starts a tool-calling turn with the full safe catalog
   (`registry.catalog()`) offered to the model.
3. For each tool the model requests: checks the budget, resolves the
   definition, validates arguments. Unknown tools and invalid arguments are
   fed back to the model as a failed tool result (so the model can recover
   or explain), never silently dropped.
4. `read_only` requests execute immediately through `execute_tool`.
5. The first `internal_write` request in a batch **stops the loop
   entirely**: it validates the arguments, freezes them into a pending
   operation, and returns `kind="approval_required"` — no further model
   round-trip happens for this turn. Read-only tool calls that already ran
   earlier in the same batch remain real, audited executions; that part of
   the work already happened honestly.
6. `high_risk` requests are refused with a fixed message and never reach
   the executor.
7. When the budget is exhausted, the loop stops and asks for one final,
   honest, tools-disabled answer (§6) instead of continuing indefinitely.

Tool results are always sent back through the provider's own tool-result
channel (§11) — never encoded as a fabricated user message, and the model
is never allowed to treat tool output as a new instruction from Moot.

`backend/main.py`'s `/chat` route commits the resulting assistant turn the
same way regardless of outcome: on `approval_required`, the committed
assistant message is a deterministic summary (never a claim that the tool
already ran), and the response body additionally carries
`approval_required: true` and the frozen `operation` (id, tool_name,
version, `arguments`, status, timestamps) for the frontend to render an
approval card. **Post-approval model continuation is intentionally not
implemented in V0.2A** — approving an operation returns a deterministic
success/failure receipt, not a fresh model-generated reply, because doing
otherwise would require persisting complex provider-specific continuation
state past the end of the original chat request. This is documented, not
hidden: see `docs/API_REFERENCE.md`.

## 13. Frontend

`frontend/app.js` renders an approval card inline in the chat thread
(`frontend/tools.css`) whenever a chat response carries
`approval_required: true`: a tool label, a plain key/value summary of the
frozen arguments, and Approve/Reject buttons that call the endpoints in
§10. The card disables its buttons for the duration of a request and
replaces them with a plain status line once a decision is recorded —
no client-side state pretends an action succeeded before the server
confirms it. `frontend/activity.js` labels `run_type == "tool"` rows by
tool name/version (§8); no new Activity route was needed.

## 14. Capability manifest

`backend/capability_catalog.py`'s `render_capability_manifest()` (called
fresh from `backend/model_input.py` on every prepared request, sent to the
model on every turn) names exactly the currently registered tools, states
that an `internal_write` tool never runs without explicit approval, and
instructs the model that it may not invent or assume any other tool
exists. As of V0.3A this text is *generated* from `get_tool_registry()`,
not a hand-maintained constant — see §16. See `docs/CURRENT_IMPLEMENTATION.md`
and `tests/test_model_input.py`.

**Live-testing fix: call the tool, don't ask first.** Live testing showed
the model asking a chat confirmation question ("should I create this
task?") instead of calling `tasks.create`, even when the request was
unambiguous. Two instruction sources were ambiguous enough to cause this:
the manifest's old wording ("Moot must explicitly approve it... first")
read as "get the user's confirmation before calling the tool," and
`backend/conversation_guidance.py`'s general "ask before an outside
action" rule — appended *after* the capability manifest, so closer to the
model's attention — was not scoped to exclude a registered tool call. Both
were rewritten to be explicit: calling a write-capable tool is how
MootOS's own review step starts, not something to precede with a model-
authored confirmation question; the model should call a write-capable tool
immediately once the request is clear, ask only for genuinely missing
information, and never invent optional fields the user did not state.

**V0.3A: single-sourced, not duplicated.** At V0.2A this guidance was
*repeated* as a second, independently hand-typed paragraph inside the
manifest, alongside `tasks.create`'s own tool description
(`backend/tools_reference.py`) — both said the same thing in different
words, which is exactly the kind of drift risk V0.3A exists to close (see
ADR-029). `render_capability_manifest()` now embeds each `internal_write`
tool's own registered `description` **verbatim** in the manifest's
"Calling a write-capable tool" section instead of re-authoring it — the
argument-level rules (e.g. `tasks.create`'s `due_at` handling) exist in
exactly one place, and only the mechanism-level guidance that's genuinely
generic across *any* write-capable tool (don't self-confirm, ask only for
missing information) remains fixed manifest prose. See
`tests/test_model_input.py`, `tests/test_tools_reference.py`, and
`tests/test_chat_tool_integration.py`.

## 15. Out of scope for V0.2A

No Calendar, Gmail, GitHub, web browsing, filesystem execution, shell
commands, payments, studio-booking integration, background workers,
scheduler/reminders, recurrence, autonomous agents, arbitrary plugin
installation, third-party external writes, voice, vision, or multi-user
permissions were added. This branch establishes the port, not every device
that will eventually plug into it. See ADR-027 and `ROADMAP.md` for the
sequencing decision.

## 16. V0.3A — Capability-aware metadata and the generated catalog

**Status:** implemented and merged to `main`. Schema unchanged
(`5 — tool_system`) — everything below lives on `ToolDefinition` in code,
never in the database. See
`docs/CAPABILITY_ARCHITECTURE.md` and ADR-028/ADR-029 for the decision
record this section implements.

**Goal.** Make MootOS able to truthfully answer "what can you currently
do?" from the live Tool Registry, and stop the model-facing capability
description from being a second, independently hand-maintained list that
could name a tool the registry doesn't actually have (or omit one it
does).

**What changed:**

- `ToolDefinition` (§3) gained five descriptive fields —
  `capabilities`, `side_effects`, `idempotent`, `limitations`,
  `depends_on` — validated at construction, never read by
  `backend/tool_executor.py` or `backend/tool_conversation.py`. They
  affect description only, never execution or permission.
- All four V0.2A reference tools (`backend/tools_reference.py`) now
  declare this metadata explicitly and truthfully — none rely on the
  "undocumented" defaults, which exist only for unrelated test fixtures.
- New module `backend/capability_catalog.py` — a read-only, derived view
  over the registry. Nothing in it stores, executes, or authorizes
  anything:
  - `build_tool_catalog(registry)` — the full tool catalog (same shape as
    `registry.catalog()`).
  - `build_capability_index(registry)` — groups tool names by their
    declared `capabilities` reference into a **derived, non-executable**
    view, e.g. `{"id": "tasks.manage", "label": ..., "tools":
    ["tasks.create", "tasks.list"]}`. A capability id with zero backing
    tools simply does not appear; a capability id is never itself
    passable to `execute_tool` (`ToolRegistry.get` fails closed on
    anything that isn't a real registered tool name — capability ids
    included).
  - `describe_installed_abilities(registry)` — `{"tools": [...],
    "capabilities": [...]}`, the structured, complete answer to "what can
    you currently do?" Contains only tool/capability metadata; no tool
    arguments, prompt/response content, secrets, or private user data
    (`tests/test_capability_catalog.py` asserts this directly).
  - `render_capability_manifest(registry)` — replaces the previous
    `backend.model_input.CAPABILITY_MANIFEST` constant (§14). Builds the
    model-facing prose fresh from `registry.list_definitions()` on every
    call.
- `backend/model_input.py`'s `_build_instructions` now calls
  `render_capability_manifest()` instead of interpolating a frozen
  constant. The rest of the deterministic budgeting pipeline (ADR-022) is
  unchanged.

**Why an internal catalog API, not a `self.capabilities` tool.** The
generated manifest above is already unconditionally included in the
system instructions on *every* chat turn — both the plain `generate()`
path and the tool-calling path (`backend/model_input.py`'s
`_build_instructions` runs for both). A "what can you currently do?"
question is therefore already truthfully answerable from ambient context
without any tool call. Registering a `self.capabilities` tool would add a
function-schema entry to every OpenAI request (token cost, and one more
opportunity for a redundant/off-policy tool call) for information the
model already has in front of it, and it would be the first tool whose
entire purpose is introspecting the Tool System itself — legitimate future
work (`docs/CAPABILITY_ARCHITECTURE.md` §6, V0.3C self-awareness), but not
something V0.3A's own goal requires. `describe_installed_abilities()` is
instead a plain, directly testable, zero-execution-risk Python function —
callable from tests, a future HTTP route, or a future V0.3B/V0.3C
consumer without going through the model/tool-calling loop at all.

**High-risk tools are never described as available.** `render_capability_
manifest` only ever names `read_only` and `internal_write` tools in its
"available" sections — a registered `high_risk` tool (none exist in
V0.2A/V0.3A) is never described as something the model may call, matching
`backend.tool_executor`'s unconditional block on that risk tier (§5).
`tests/test_capability_catalog.py` proves this against a synthetic
high-risk tool.

**Bug found and fixed while building this: registry truthiness.**
`backend/tool_executor.py`, `backend/tool_conversation.py`, and the new
`backend/capability_catalog.py` all resolve an optional `registry`
parameter with a pattern like `registry or get_tool_registry()`.
`ToolRegistry.__len__` makes an *empty* registry falsy — so an explicitly
passed, intentionally empty `ToolRegistry()` was silently replaced by the
real process-wide default registry instead of being treated as empty.
This was latent (masked in existing tests by an unrelated, also-true
fallback condition — see the updated
`test_falls_back_to_plain_generate_when_registry_empty` in
`tests/test_tool_conversation.py`) until V0.3A's own tests caught it
directly. Fixed in all three modules to `registry if registry is not None
else get_tool_registry()`; regression tests added in
`tests/test_tool_executor.py` and `tests/test_tool_conversation.py`. This
does not change behavior for any real caller, which always passes either
`None` or a genuinely populated registry.

**Deliberately out of scope for V0.3A** (see
`docs/CAPABILITY_ARCHITECTURE.md` for when these are planned): structured
gap reasoning over a natural-language goal (V0.3B), self-inspection beyond
the registry itself — no source paths, docs, or version/commit exposure
(V0.3C), protected-core mechanical gates (V0.3D), and any form of capability
building, installation, local node, or Codex bridge (V0.3E/V0.4A-D). No
new registered tool, no new HTTP route, and no database migration were
added by V0.3A.
