# MootOS Roadmap

**Last reviewed:** August 9, 2026

## Vision

MootOS is being built as a private personal AI operating layer that owns its durable state, keeps AI providers replaceable, and expands in small verified steps.

Core rules:

- reliability before scale
- deterministic writes where practical
- one focused branch/PR at a time
- user remains final authority
- no claiming an action happened before storage/execution proves it
- permissions and auditability before risky external automation
- local/simple architecture until complexity is justified by real use

## Current position

Version 0.1 foundation plus the V0.2A Tool Foundation are both live on
`main` with schema 5.

Implemented and merged:

- private phone deployment
- persistent conversations/projects
- SQLite/WAL/migrations/readiness hardening
- memory save/review/search/correction/history/archive/restore
- deterministic concept-aware memory retrieval without embeddings
- conversation/capability hardening
- curated bootstrap-profile import
- model Run logging
- Task v0.1 lifecycle
- intelligent explicit memory correction through chat
- explicit chat-driven Task creation
- V0.2A Tool Foundation: a small, fail-closed, provider-replaceable Tool
  System with four registered tools (`projects.list`, `memory.search`,
  `tasks.list`, `tasks.create`), a centralized executor, a per-turn call
  budget, and a human-approval gate for writes. See `docs/TOOL_SYSTEM.md`
  and ADR-027. Live-tested on Railway/OpenAI, including a successful
  frozen approval → execution → persisted Task. This is a controlled
  internal port, not general external-tool execution — no calendar,
  email, GitHub, filesystem, or shell access exists.
- `AGENTS.md` — Codex's manual local-worker boundaries (read-only `main`,
  dedicated branch/worktree required, no secrets access, no destructive
  git operations, no unauthorized commit/push/merge/PR).
- V0.3A Capability-Aware Tool System: `ToolDefinition` extended with
  capability/side-effect/idempotency/limitation/dependency metadata; the
  model-facing capability manifest is generated from the live Tool
  Registry instead of hand-maintained. See `docs/TOOL_SYSTEM.md` §16 and
  ADR-028/ADR-029. No new tool, no new HTTP route, no schema migration.

- V0.3B Structured Gap Reasoning: `backend/gap_reasoning.py` turns a
  natural-language goal into a structured, audited Gap Report (classified
  `already_possible` / `composable` / `capability_gap` /
  `externally_blocked`), with model interpretation strictly separated from
  deterministic resolution against the V0.3A capability catalog. Reasoning
  only — no tool execution, no capability installation. See
  `docs/GAP_REASONING.md` and ADR-030. No new tool, no new HTTP route, no
  schema migration.

**Implemented, pending merge:** V0.3C Narrow Self-Inspection + Read-Only
Web Awareness, on branch `claude/v0.3c-self-inspection-web-awareness` —
adds three read-only registered tools. `self.state` and
`self.architecture` let MootOS answer questions about its own architecture
and current phase from an explicit allow-list of curated documents plus
live registry state, with the registry always authoritative over
documentation (`docs/SELF_INSPECTION.md`). `web.search` adds MootOS's
first external connector: bounded, read-only public web search, treating
retrieved content as untrusted data and registering only when a search
service is configured (`docs/WEB_AWARENESS.md`, ADR-035). No write-capable
external operation, no filesystem or shell access, no schema migration.

The repository currently has no scheduler, reminder delivery, recurrence,
background worker, multi-user system, or capability-builder automation.

## V0.3/V0.4 architecture lock (August 2026)

The next major phase — MootOS accurately describing what it has, reasoning
about capability gaps, and eventually (much later, human-approved at every
step) building new capabilities in isolation — is locked as of August 9,
2026. The full plan, including the reconciled position between the
original product vision and the independent architecture reviews that
shaped it, lives in **`docs/CAPABILITY_ARCHITECTURE.md`**, backed by
**ADR-028 through ADR-034**. Read that document for the actual phase
definitions; this section is a pointer, not a duplicate.

Phase sequence at a glance: **V0.3A** capability-aware Tool System (richer
tool metadata, truthful "what can you do" answers) — **implemented and
merged**, see `docs/TOOL_SYSTEM.md` §16 — → **V0.3B** structured,
advisory gap reasoning — **implemented and merged**, see
`docs/GAP_REASONING.md` — → **V0.3C** narrow self-awareness + read-only web
awareness — **implemented on branch
`claude/v0.3c-self-inspection-web-awareness`, pending merge**, see
`docs/SELF_INSPECTION.md` and `docs/WEB_AWARENESS.md` — → **V0.3D**
protected core enforced as mechanical release gates
→ **V0.3E** a manual, human-run capability-build pipeline proven on at
least two real capabilities → **V0.4A** capability-builder automation
(isolated builds only, no self-install) → **V0.4B** a usage-gated,
read-only-first Local Companion → **V0.4C** an automatic Codex worker
bridge built on `AGENTS.md`'s existing manual boundaries → **V0.4D** a
real composition mission proving capabilities compose instead of requiring
one giant bespoke tool.

The Tool Registry remains the only executable source of truth throughout —
no second "Capability Registry" is introduced. See ADR-028.

This supersedes the "Long-term sequence" section further down this
document as the current plan; that section is left in place, marked
superseded, per this repository's convention of preserving prior planning
context rather than deleting it.

## Sequencing change: Tool Foundation moved ahead of Scheduler/Reminder

**Recorded August 2026, ADR-027.** The sequence below (documentation sync,
audit, then Scheduler/Reminder v0.1) was the plan through PR #31. V0.2A
changes the order: a Tool Foundation (`docs/TOOL_SYSTEM.md`, ADR-027,
Decision 011) is built *before* the scheduler. **Since merged to `main`
and live-verified on Railway/OpenAI** — see "Current position" above.

Real V0.1 usage showed that controlled action-taking creates more immediate
product value than a scheduler would on its own — a reminder that fires
into a system with no safe action boundary just becomes another chat
message. A working, fail-closed Tool System is also the shared prerequisite
most other planned integrations (Calendar, Gmail, GitHub, files, studio
work, and eventually reminders themselves) will need.

**The original reasoning below is not deleted or wrong — it is deferred.**
Scheduler/Reminder v0.1 remains a planned next capability, and everything
this section says about it (durable state, timezone semantics, idempotent
delivery, and so on) still applies whenever it is built. It can now be
designed as a producer of tool-selectable, approval-gated work instead of
inventing its own execution/permission boundary from nothing.

## Immediate sequence (pre-V0.2A; see the sequencing change above)

**Steps 1-2 below are historical planning context, kept intact rather than
deleted.** Step 3 (Scheduler/Reminder v0.1) remains deferred — not because
it was wrong, but because the V0.3/V0.4 architecture lock above is now the
current next-phase plan. Read `docs/CAPABILITY_ARCHITECTURE.md` for what
actually comes next; treat everything below this note as history, not the
active plan.

### 1. Documentation synchronization — current

Bring central docs in line with post-PR-30 code so human and AI reviewers start from an accurate map.

### 2. Independent full-repository audit

Use multiple reviewers to challenge:

- architecture/module boundaries
- SQLite/transaction safety
- auth/security
- memory semantics
- Tasks/Runs boundaries
- documentation drift
- readiness for scheduling

### 3. Scheduler / Reminder v0.1 — proposed next feature

Goal: allow MootOS to durably represent and deliver a simple one-time reminder without pretending a full automation platform exists.

The design must solve:

- durable scheduled state
- UTC and user timezone semantics
- restart/offline catch-up
- idempotent claiming/delivery
- duplicate prevention
- delivery/failure/cancelled state
- rescheduling behavior
- deterministic clock-controlled tests
- current Railway process topology

The first scheduler version should avoid recurrence, conditional triggers, distributed queues, and external-tool execution unless the audit proves one is necessary.

### 4. Natural chat reminder creation

Only after scheduler delivery exists should wording such as:

```text
Remind me to call Mike tomorrow at 3
```

become a deterministic scheduled write. Until then, that wording must remain ordinary chat and no delivery promise should be made.

### 5. Reminder UX / review

Add a simple way to inspect, cancel, and later reschedule reminders. Keep Task state and reminder-delivery state distinct unless the scheduler design proves a simpler safe model.

## Architecture boundaries already established

### Memory

Durable facts/context. Lifecycle: active, superseded, archived. Correction preserves history.

### Task

Intention/work item. Lifecycle: open, completed, cancelled. Task does not itself authorize external execution.

### Run

Execution/audit record. Current usage records model-provider attempts; future tool execution may use the same audit spine.

### Future Reminder/Schedule

A future trigger/delivery concern. It must not silently turn mutable Task fields into execution authority.

### Tool System (V0.2A; see `docs/TOOL_SYSTEM.md`)

Write-capable actions use frozen operation parameters, risk-classified policy checks, human approval when required, and Run records. Implemented for four internal tools, merged to `main` and live-verified on Railway/OpenAI; write-capable *external* actions (Calendar, Gmail, GitHub, and similar) remain future work that can plug into this same boundary.

### Capability / Connector (V0.3+; see `docs/CAPABILITY_ARCHITECTURE.md`)

A Capability is a semantic grouping of one or more registered Tools; it never executes anything itself. A Connector is the access boundary a Tool uses to reach something outside MootOS's own store (web search, GitHub, a local device, and so on). Neither is a second executable system — the Tool Registry above remains the only one. See ADR-028.

## Near-term product direction

After a reliable scheduler/reminder loop is proven, likely next candidates are:

- Task/reminder review UI
- recurrence only if one-time reminders are stable
- controlled calendar/read-only tools
- approval infrastructure before write-capable tools
- project dashboards that aggregate existing conversations, memories, Tasks, and reminders rather than duplicating data

## Deferred capabilities

See also `docs/CAPABILITY_ARCHITECTURE.md` §9 for the V0.3/V0.4-specific
deferred-items list (second capability registry, generalized connector
framework, persistent workflow engine, large lifecycle machinery before a
builder exists, and others). The list below predates that document and is
kept as-is rather than merged into it.

These remain later work:

- embeddings/vector database unless deterministic retrieval proves inadequate
- multi-user accounts/roles
- multiple Railway replicas while SQLite is the live store
- distributed task queues
- autonomous background agents
- broad external tool write access
- voice
- vision/media understanding
- commercial multi-tenant deployment

## Long-term sequence (superseded by the V0.3/V0.4 architecture lock above)

**This section predates the V0.3/V0.4 architecture lock and uses an older,
now-conflicting version numbering** — its "Version 0.3" and "Version 0.4"
are unrelated to the current V0.3A-E / V0.4A-D phases defined in
`docs/CAPABILITY_ARCHITECTURE.md`. It is kept below as historical planning
context, per this repository's convention of preserving prior context
rather than deleting it, but it is no longer the active plan. For the
current plan, use `docs/CAPABILITY_ARCHITECTURE.md` and the "V0.3/V0.4
architecture lock" section near the top of this document. Any themes below
that are still relevant (project dashboards, memory intelligence, coding
agent) remain plausible future work, but their sequencing and version
numbers should be treated as superseded, not authoritative.

### Version 0.2 — Project intelligence

Project dashboards, goals/status, Tasks/reminders, related conversations/memories/files, and useful workspace views.

### Version 0.3 — Memory intelligence

Better source/confidence metadata, semantic retrieval if justified, summaries, temporary/expiring memory, richer relationships.

### Version 0.4 — Controlled tools and approvals

Read-first external integrations, explicit permissions, frozen operations, approval policy, audit trails, safe write actions.

### Version 0.5 — Coding/engineering intelligence

Repository understanding, planning, code generation, tests, PR preparation, engineering decision memory, review roles.

### Version 0.6 — Studio/content workflows

Prove useful revenue-producing workflows inside Moot's real work before packaging them for others.

### Version 0.7+ — Voice, vision, broader automation

Add richer interfaces only after the underlying memory, permission, execution, and audit systems are trustworthy.

## Database scaling direction

SQLite remains intentional while MootOS is single-user and one-replica. Evaluate PostgreSQL before meaningful multi-user/multi-replica commercial use, not merely for architectural appearance.

## Completion rule for every meaningful feature

A feature is not complete because code exists. It should pass:

1. focused implementation
2. automated tests/CI
3. internal review
4. independent external review for meaningful changes
5. explicit merge approval
6. controlled deployment
7. production verification when user-facing/runtime behavior changes
8. documentation synchronization
