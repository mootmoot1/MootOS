# ADR-027 — Tool Foundation v0.2A

## Status

Draft implementation decision for V0.2A. Implemented on branch
`claude/motos-v0.2a-tool-foundation-u46ew4`. Not merged to `main`.

## Context

MootOS V0.1 (PR #34) established conversation, memory, projects, Tasks,
model routing, authentication, Runs, and the mobile interface. The model
could talk about MootOS's data but could never act on it — every action
MootOS actually took was either the user's own deterministic chat command
(`Remember that ...`, `Create a task to ...`) or a direct authenticated API
call from the browser.

The existing `ROADMAP.md` (as of PR #31) named **Scheduler / Reminder v0.1**
as the proposed next feature after documentation synchronization. This ADR
records a deliberate change to that sequencing.

### Why the sequence changed

Real V0.1 usage showed that a scheduler/reminder loop is only valuable once
MootOS can already take *some* controlled action reliably and safely —
otherwise a reminder just fires a notification into a system that still
cannot do anything about it. A working, safe, provider-replaceable Tool
System is the prerequisite most other planned capabilities
(Calendar, Gmail, GitHub, files, studio integrations, and eventually
reminders themselves) will build on. Building the tool port first means
those integrations plug into one already-proven safety boundary instead of
each reinventing permission checks, approval flows, and audit logging.

This does not mean the scheduler/reminder design work was wrong or is
discarded — see `ROADMAP.md`'s "Immediate sequence" section, which keeps
the original reasoning intact and marks it as deferred rather than
replaced. `docs/CURRENT_CHECKPOINT.md`'s existing "Proposed next feature"
text (Scheduler / Reminder v0.1) is also left in place as a historical
record of the prior plan.

## Decision

Add a Tool System (V0.2A) that lets MootOS invoke a small, explicitly
registered set of internal tools from normal model-backed conversation,
under a fail-closed permission model, with an execution/audit trail and a
human-approval gate for any write.

### Module boundaries

See `docs/TOOL_SYSTEM.md` for the full module map and mechanism. In
summary: `tool_types` (contract, leaf), `tool_validation` (dependency-free
JSON-Schema-lite), `tool_registry` (explicit registration, fail-closed
lookup), `tools_reference` (the four V0.2A tools), `tool_executor` (single
centralized execution path), `tool_budget` (per-turn call cap and loop
protection), `tool_operations` (frozen-approval state machine),
`tool_routes` (approval HTTP API), `tool_conversation` (the bounded model
loop). `backend/model_router.py` and `backend/runs.py` were extended, not
replaced.

### Risk taxonomy

`read_only` (auto-executes), `internal_write` (requires explicit human
approval of the model's exact request), `high_risk` (never executes in
V0.2A, by architecture, not by omission — no real high-risk tool exists yet
to test this against, so the block is unconditional).

### Schema

Migration 5 (`tool_system`) adds `tool_name`/`tool_version` to `runs`
(new columns, not a repurposing of `provider`/`model` — see the "why not
reuse provider/model" note below) and a new `tool_operations` table for
frozen approval state. See `docs/DATA_AND_PERSISTENCE.md` and
`docs/TOOL_SYSTEM.md` §8.

### Why not reuse `provider`/`model` for tool identity

`runs.provider`/`runs.model` describe which AI model provider generated a
`RUN_TYPE_MODEL` row. A tool is not a model provider. Writing `tasks.create`
into `provider` (or a fabricated `"mootos"` value into both) to avoid a
schema migration would make every future query and every human reading a
Run row have to guess which meaning applied to a given row. A one-migration
cost is small compared to that permanent ambiguity, and the existing
migration system (`backend/migrations.py`) already makes an additive,
restart-safe column addition routine.

### Approval, not "trust the model"

An `internal_write` tool request is never executed merely because the model
asked. `backend.tool_operations.create_pending_operation` freezes the
already-schema-validated arguments; `approve_operation` accepts only an
operation ID (no arguments parameter exists on that function at all), so
there is no code path by which a model or a client can alter what runs
after a human approves it. See `docs/TOOL_SYSTEM.md` §9 for the
double-click/crash-safety guarantees.

### Provider replaceability preserved

OpenAI Responses API tool-call objects (`function_call`,
`function_call_output`, the raw `input` item list) are built and parsed only
inside `backend/model_router.py`'s `OpenAIProvider`. Every other module —
including the conversation loop that decides whether to auto-execute,
request approval, or refuse — only ever sees `ToolRequest`, `ToolResult`,
and an opaque provider-owned continuation `state` it must never inspect.
The existing `generate()` plain-text path is unchanged; a router or test
double that only implements `generate()` (every pre-V0.2A test fixture)
continues to work exactly as before, unmodified.

## Consequences

### Positive

- MootOS can now safely read its own data (projects, memory, Tasks) on the
  model's initiative, and can propose — but never silently perform — a
  write, inside one small, reviewable, fail-closed boundary.
- Future integrations (Calendar, Gmail, GitHub, files, studio tools) have a
  proven port to plug into instead of needing their own permission model.
- The existing Run audit spine gained tool identity without a second
  logging system.
- All existing V0.1 deterministic command paths, tests, and the plain-text
  chat path are unchanged and still pass.

### Tradeoffs

- Post-approval model continuation is not implemented; approving an
  operation returns a deterministic receipt, not a fresh model-generated
  reply summarizing the result. Documented, not hidden — see
  `docs/TOOL_SYSTEM.md` §12 and `docs/API_REFERENCE.md`.
- An operation stuck in the transient `executing` state after a process
  crash between claim and finalize is not automatically repaired in
  V0.2A. This is the same accepted category of risk as an unrepaired
  `started` Run row from V0.1 — detectable, operationally repairable,
  never silently duplicated.
- Only four reference tools exist. No calendar/email/GitHub/file/shell
  access was added; see `docs/TOOL_SYSTEM.md` §15 and `ROADMAP.md`.

## Follow-on direction

`ROADMAP.md`'s "Immediate sequence" is updated to record this reordering.
Scheduler/Reminder v0.1 remains a planned next capability; it can now be
designed as a producer of tool-selectable/approval-gated work instead of a
system that has to invent its own execution boundary from nothing.
