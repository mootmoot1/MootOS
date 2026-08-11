# MootOS Current Checkpoint

**Last updated:** August 9, 2026  
**Repository:** `mootmoot1/MootOS`  
**Default branch:** `main`  
**Current release on `main`:** Version 0.1 foundation plus the V0.2A Tool Foundation, V0.3A Capability-Aware Tool System, V0.3B Structured Gap Reasoning, V0.3C Narrow Self-Inspection + Read-Only Web Awareness, and V0.3D Protected Core + Mechanical Release Gates  
**Current schema on `main`:** `5 — tool_system`  
**Also implemented, pending merge:** V0.3E proof #2, on branch `claude/v0.3e-proof-2-capability` (adds no migration -- schema stays `5 — tool_system` once merged; adds one new read-only registered tool, `projects.overview`, pending merge). This completes ADR-034's two-proof prerequisite for V0.4A, which remains unimplemented and still requires its own design/review step.

## Current production topology

MootOS is deployed privately on Railway as:

```text
one Railway service
one FastAPI application process
one replica
SQLite/WAL on the Railway volume
OpenAI for model-backed chat
```

Production launches `backend.application:app` and Railway uses `/ready` for deployment readiness. `/health` remains minimal liveness.

No Redis, Celery, distributed queue, vector database, background worker, scheduler, reminder-delivery system, external write-capable tool executor, or multi-replica coordination exists today.

### V0.2A Tool Foundation — merged, live-verified

`docs/TOOL_SYSTEM.md` and ADR-027. Four registered tools (`projects.list`,
`memory.search`, `tasks.list` read-only; `tasks.create` internal-write,
requires explicit human approval), a centralized executor, a per-turn
5-call budget, and a frozen-operation approval state machine. Live-tested
on Railway/OpenAI, including a successful frozen approval → execution →
persisted Task.

### V0.3A Capability-Aware Tool System — merged

`docs/TOOL_SYSTEM.md` §16, ADR-028, ADR-029. `ToolDefinition` extended
with `capabilities`/`side_effects`/`idempotent`/`limitations`/
`depends_on`; all four V0.2A tools declare it truthfully. New
`backend/capability_catalog.py` derives a non-executable capability index
and a structured "what can you currently do?" description from the live
registry. The model-facing capability manifest
(previously `backend.model_input.CAPABILITY_MANIFEST`, a hand-maintained
constant) is now generated from the registry on every request — a tool
that isn't registered can never be named as available, and a registered
tool can never be silently missing. No new tool, no new HTTP route, no
schema migration.

### V0.3B Structured Gap Reasoning — merged

`docs/GAP_REASONING.md`,
ADR-030. New `backend/gap_reasoning.py`: `analyze_goal(goal, router=...)`
turns a natural-language goal into a structured `GapReport`, strictly
separating the model's interpretation (proposed capability requirements,
in a validated JSON shape) from deterministic resolution against the
V0.3A capability index (`backend.capability_catalog.build_capability_
index`). Classifies each goal as `already_possible` / `composable` /
`capability_gap` / `externally_blocked`. Reasoning only — never executes a
tool, never registers a capability. New `ModelRouter.generate_standalone`
for the narrow, chat-pipeline-independent model call this requires. Every
call is an audited `RUN_TYPE_MODEL` Run (existing Run schema, no
migration); the Run table has no column able to hold goal/model text, so
none is ever stored. No new tool, no new HTTP route, no schema migration.

**Known integration gap:** `analyze_goal()` exists as an internal API and
is not yet invoked by normal chat. Deliberately unchanged in V0.3C; see
`docs/GAP_REASONING.md` §8 and the V0.3C section below.

### V0.3C Narrow Self-Inspection + Read-Only Web Awareness — merged

`docs/SELF_INSPECTION.md`, `docs/WEB_AWARENESS.md`, ADR-035. Adds three
read-only registered tools:

- `self.state` — live runtime truth (registry-derived), no arguments.
- `self.architecture` — one document from a seven-entry compile-time
  allow-list of architecture/status markdown files, selected by
  enum-constrained key. No path input exists; no `read_file(path)` was
  added. Cannot reach `.env`, secrets, the database, user data, source
  code, or Git history.
- `web.search` — MootOS's first external connector
  (`backend/web_connector.py`): bounded, GET-only public web search with a
  10s timeout, a 512KB streamed response cap, and at most 5
  title/URL/snippet results. Registered **only when a search service is
  configured**, so an unconfigured deployment truthfully reports no web
  capability (ADR-035).

Documentation never overrides runtime truth: when a curated document names
a tool the registry lacks, `self.state` surfaces the disagreement rather
than choosing a side. Retrieved web content is treated as untrusted data —
structurally unable to register a tool, change a risk classification, or
approve an operation. No write-capable external operation, no filesystem
or shell access, no new HTTP route, no schema migration. `httpx` is now
declared explicitly in `requirements.txt` (already a transitive dependency
of `openai`); `railway.toml` is untouched.

### V0.3D Protected Core + Mechanical Release Gates — merged

`docs/GATES_AND_RELEASE_SAFETY.md`,
ADR-031. Converts ADR-031's protected-core rules into five deterministic
CI gates under `scripts/gates/`: a protected-path diff check
(`protected_paths.py`), an AST-based migration-safety check that
distinguishes a brand-new additive migration from a rewrite of migration
machinery or history (`migration_safety.py`), a risk-metadata check that
fails a `ToolDefinition.risk` field given a default value or an invalid
live registry risk value (`risk_metadata.py`), a narrow pattern scan for
plugin-discovery/dynamic-import/executor-bypass constructs
(`registration_authority.py`), and a repo-local secret/database-file scan
(`secret_scan.py`), orchestrated by `run_gates.py`. All five run
automatically in a new `protected-core-gates` CI job (added to
`.github/workflows/python-package.yml`, alongside the existing unchanged
test/lint job) and report pass/fail. **Making that check actually block
the merge button still requires the repo admin to enable it as a required
GitHub branch-protection status check after this PR merges** — workflow
presence alone does not make GitHub enforce it (see
`docs/GATES_AND_RELEASE_SAFETY.md` §10). The gate policy protects its own
directory (`scripts/gates/` is itself a denied path) and CI runs the gate
code extracted from the base ref rather than the PR's own copy, so a diff
cannot weaken the policy and have that weakening apply to itself.

**The PR that merged this used a one-time bootstrap exception**, since
`main` did not yet contain `scripts/gates/` for the trusted-base-extraction
path to run against, and the protected-path gate correctly failed on that
PR (it touched `scripts/gates/` and `.github/workflows/` to introduce
itself). It required one explicit human override limited to those two
paths -- not a general precedent for merging with a red gate. That
exception has already retired itself: every PR since (including V0.3E's)
runs against a real trusted `scripts/gates/` on `main` and must pass the
normal gate like any other change. See
`docs/GATES_AND_RELEASE_SAFETY.md` §6.

`backend/tool_registry.py` remains protected intentionally. V0.3E's first
proof capability confirmed the intended flow: its one registration edit
to that file correctly failed the protected-path gate, surfacing it for
elevated human review rather than needing (or getting) a bypass — see
`docs/CAPABILITY_BUILD_PIPELINE.md` §6.

Every gate is a deterministic script — none of them calls a model, and
none of them is a source of merge authority; human approval still
controls merge (ADR-032, unchanged). No capability builder, local node,
Codex bridge, external write tool, workflow persistence, or
self-installation exists yet or is enabled by this work. No new tool, no
new HTTP route, no schema migration, no runtime behavior change.

### V0.3E Manual Capability-Build Pipeline — merged (proof #1); proof #2 on branch, pending merge

`docs/CAPABILITY_BUILD_PIPELINE.md`, ADR-034. Proves the manual
capability-build lifecycle end to end on one real capability,
`tasks.status_summary` -- a new `RISK_READ_ONLY` tool
(`backend/tools_task_summary.py`) that reports Task counts by status,
backed by a new `backend.tasks.count_tasks_by_status()` aggregate (no
schema change). Adds `scripts/capability_pipeline/`: a validated
`CapabilitySpec` schema (`spec.py`, fail-closed on unknown fields,
invalid risk/data-exposure, a read_only spec declaring side effects, or a
protected-core touch left unflagged) and a small, explicit,
human-transition-only lifecycle record (`lifecycle.py`:
`proposed -> specified -> implemented -> tested -> reviewed ->
ready_for_pr -> merged`, one step at a time, no automatic transitions,
zero coupling to `backend/tool_registry.py`) plus three distinct advisory
review roles (`review.py`: correctness/test quality, security/
permissions, architecture/duplication -- all advisory only, never able to
mutate lifecycle state). The one protected-core touch this capability
needs -- one line registering it in `build_default_registry()` -- fails
V0.3D's protected-path gate exactly as intended; no gate was weakened and
no alternate registration path was created. No autonomous builder exists:
no automatic branch/commit/PR/merge/registration/deployment anywhere in
this phase. No new HTTP route, no schema migration.

**Proof #2 -- `projects.overview`, on branch
`claude/v0.3e-proof-2-capability`, pending merge.** A read-only
cross-table rollup (`backend/project_insight.py`,
`backend/tools_project_insight.py`) reporting per-project active-memory,
open/total-Task, and conversation counts plus a last-activity timestamp,
scoped optionally to one project. Deliberately a different resource and
query shape from proof #1, so the second pass tested whether the pipeline
generalizes rather than repeating the first exercise. It did: the V0.3E
spec schema, lifecycle model, artifact pattern, and V0.3D gates were all
used unchanged, with no pipeline redesign needed.

The advisory review stage proved load-bearing rather than ceremonial.
Run with three genuinely independent reviewer instances (separate model
instances, independent contexts, read-only tools, all reviewing the same
immutable commit) instead of one model writing three reviews in
sequence, two of the three returned `concerns_noted` against the first
implementation and surfaced four reproducible correctness defects (a
case-merge that overwrote instead of accumulating; rows naming a
deleted project vanishing from both the per-project entries and
`unassigned`; a last-activity timestamp that did not move when a Task
was completed; and one that could move backward when a memory was
archived), plus a CI regression the diff itself introduced, a false
docstring claim, and an unbounded result size. All were fixed with
regression tests before the lifecycle record reached `ready_for_pr`.
Proof #1's single-model reviews had found nothing.

**Both proof capabilities ADR-034 requires are now complete.** That
satisfies the two-pass prerequisite and removes a blocker on V0.4A --
it does not start or approve it. V0.4A (capability-builder automation)
remains unimplemented and still requires its own design and review step.

Next planned work is V0.4A's design/review step, not yet started.

## Production-verified capabilities

The following have direct production verification recorded in the project history/checkpoint process:

- private password/session login
- persistent SQLite on the Railway volume
- `/health` and `/ready`
- OpenAI-backed chat through the private phone interface
- persistent conversations/messages/projects
- explicit chat memory save and cross-chat recall
- protected memory review/search
- memory correction with preserved history
- recoverable archive/restore
- active-memory recall surviving Railway rebuilds
- hardened private HTTP boundary
- atomic provider-backed chat persistence behavior
- intelligent explicit memory correction from PR #29, verified through the real phone UI

## Latest production-verified memory milestone

PR #29 added deterministic explicit memory correction. After merge and Railway deployment, production testing confirmed:

1. an old test memory was saved
2. a correction using `Actually, ... Remember that instead.` was accepted
3. a brand-new conversation recalled only the replacement value
4. the old superseded value did not appear as a conflicting active memory

That verifies the new correction path against the persistent production database and real phone UI.

## Merged on main; production-smoke status tracked separately

The capabilities below are implemented and merged on `main`. Their implementation status should not be confused with a dated production-verification record unless such a record is explicitly added later.

### Curated bootstrap profile import

- protected `/profile` interface
- preview and atomic import APIs
- duplicate/lifecycle checks
- `bootstrap_profile` memory type
- reviewed manifest stays out of the model-provider path
- production composition through `backend.application:app`

### PR #27 — Model Run logging v0.1

- migration 3 adds `runs`
- normal model-provider attempts gain structured execution metadata
- failures record sanitized exception class metadata rather than prompt/response duplication
- Runs establish an execution/audit spine separate from Tasks

### PR #28 — Task v0.1

- migration 4 adds `tasks`
- create/list/get/complete/cancel lifecycle
- states: open/completed/cancelled
- optional timezone-aware `due_at` normalized to UTC
- canonical project scope
- authenticated Task API routes
- Task remains intention, not execution authority

### PR #30 — Chat-driven Task creation v0.1

- explicit commands such as `Create a task to call Mike`
- colon form such as `Add task: export stems`
- Task inherits the existing conversation project
- shared Task validation/storage
- conversation + user message + Task + assistant confirmation commit atomically
- false-positive task-like ordinary chat remains model chat
- memory command path regression-tested
- `Remind me ...` intentionally remains ordinary chat because no scheduler exists
- CI green and external second-pass review returned SAFE TO MERGE

## Current schema

Migrations are:

1. `initial_schema`
2. `memory_lifecycle`
3. `model_runs`
4. `tasks`
5. `tool_system`

Current durable domains/tables include:

- `schema_migrations`
- projects
- conversations/messages
- memories/history/lifecycle
- runs
- tasks
- tool_operations

## Current memory boundary

Current memory behavior includes:

- explicit `remember` / `save` writes
- deterministic explicit correction commands
- unique strong-match requirement for chat-driven corrections
- refusal to guess on zero/multiple correction targets
- append-and-supersede correction history
- active/superseded/archived lifecycle
- protected review/search
- deterministic keyword plus reviewed concept-alias retrieval

There are no embeddings or vector database.

## Current Task boundary

MootOS can create durable Tasks, but `due_at` is only stored scheduling metadata.

Therefore:

```text
Create a task to call Mike
```

can create a Task, while:

```text
Remind me to call Mike tomorrow at 3
```

is still ordinary chat and must not be reported as a scheduled reminder.

**Task = intention/work item. Task does not authorize external execution.**

## Development branch (not yet merged to `main`): `feature/v0.1-mvp-completion`

This branch adds three authenticated, additive browser pages plus two small
read-only routes. **Not merged to `main`, not yet production-verified —
implementation status only, tracked here so it isn't mistaken for a
production claim.**

- `GET /task` — Task viewer/creation UI, consuming the existing, unmodified
  `/tasks` JSON API. Named singular to avoid colliding with it.
- `GET /activity` — read-only recent-activity feed: recent model Runs
  (`GET /activity/runs`, wraps existing `backend.runs.list_runs`), recently
  *created* Tasks regardless of status (`GET /activity/tasks`, a dedicated
  creation-recency query — the existing `/tasks` listing orders due tasks
  first, which is not the same thing and would have mislabeled data as
  "recent"), and recently saved active memories, server-side limited
  (`GET /activity/memories`, a dedicated bounded query — `/memories` itself
  stays unlimited for its existing consumer, the Memory review page).
- `GET /settings` — read-only current configuration (provider, model, schema
  version) via `GET /settings/status`. Never exposes secrets. Provider/model
  remain environment-variable-only; this page does not add mutable settings
  storage.
- A direct "add a memory" form on the existing `/memory` page.
- `/profile`, `/task`, `/activity`, and `/settings` were added to the
  private-session middleware's `HTML_PATHS` set, so an unauthenticated
  browser GET to any of them now redirects to `/login` unconditionally
  (previously this depended on the request's `Accept` header for `/profile`,
  and the other three pages did not exist yet).

No schema migration, no changes to chat/memory/task/run core logic, no new
dependencies.

## V0.2A Tool Foundation — merged to `main`, live-verified

V0.2A added a Tool Foundation on top of the merged V0.1 MVP. **Merged to
`main` and live-verified on Railway/OpenAI, including a successful frozen
approval → execution → persisted Task.** See `docs/TOOL_SYSTEM.md` for the
architecture and ADR-027 for the decision record (including why this was
built before Scheduler/Reminder v0.1, below).

- Migration 5 (`tool_system`): `tool_name`/`tool_version` columns on
  `runs`; new `tool_operations` table for frozen write-tool approvals.
- Four registered tools: `projects.list`, `memory.search`, `tasks.list`
  (read-only, auto-execute), `tasks.create` (internal-write, requires
  explicit approval).
- A centralized tool executor, a per-turn 5-call budget with duplicate- and
  repeated-failure protection, and a frozen-operation approval state
  machine with duplicate-approval and expiry safety.
- `backend/main.py`'s `/chat` route now runs a bounded model-tool
  conversation loop after the unchanged deterministic memory/Task command
  dispatch; it falls back to the exact previous plain-text behavior when
  there is nothing to gain from tool calling.
- New authenticated API: `GET /tool-operations`,
  `GET /tool-operations/{id}`, `POST /tool-operations/{id}/approve`,
  `POST /tool-operations/{id}/reject`.
- An inline chat approval card (`frontend/tools.css`, `frontend/app.js`)
  and tool-aware labeling on the existing `/activity` Runs feed
  (`frontend/activity.js`); no new page and no new Activity route.
- Capability manifest (`backend/model_input.py`) now names exactly the
  four registered tools and states that `tasks.create` never runs without
  approval.
- 100 new automated tests; all pre-existing V0.1 tests, including the
  chat/Run integration tests that supply a minimal fake router, pass
  unmodified.

## Proposed next feature

**Superseded by the V0.3/V0.4 architecture lock; kept for history.** The
next proposed development area *was* **Scheduler / Reminder v0.1**, before
ADR-027 moved the Tool Foundation ahead of it. With V0.3A now merged, the
active next-phase plan is V0.3B (structured gap reasoning) per
`docs/CAPABILITY_ARCHITECTURE.md` and ADR-030 — not the scheduler.
Scheduler/Reminder v0.1 remains a deferred, planned capability (Decision
011).

Before implementation, the design should answer:

- reminder schedule/delivery storage model
- UTC and user-timezone representation
- relative-time resolution policy
- restart/offline catch-up
- duplicate-fire prevention and durable claiming
- retry/failure/delivery state
- cancellation and rescheduling
- whether a small scheduler loop belongs in the current process or another Railway process/service
- deterministic tests with controlled time

The scheduler should preserve this separation:

**Task = intention. Run = execution/audit record. Reminder/schedule = future trigger/delivery state.**

## Documentation status

PR #31 synchronizes current source-of-truth docs after PR #30 and also updates previously stale live guides such as the operations runbook, bootstrap-profile guide, and Task guide.

Historical ADRs, old branch-specific documents, and dated production-verification records should remain historically accurate even when they mention older schemas. They must not be mistaken for the current runtime map.

After PR #31 is reviewed and merged, a full independent repository audit can use the synchronized current docs as orientation while still verifying every important claim against code.