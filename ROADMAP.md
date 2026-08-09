# MootOS Roadmap

**Last reviewed:** August 8, 2026

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

Version 0.1 foundation is live on Railway with schema 4.

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

The repository currently has no scheduler, reminder delivery, recurrence, background worker, or multi-user system.

Branch `claude/motos-v0.2a-tool-foundation-u46ew4` (not yet merged to `main`) adds a V0.2A Tool Foundation: a small, fail-closed, provider-replaceable Tool System with four registered tools, a centralized executor, a per-turn call budget, and a human-approval gate for writes. See `docs/TOOL_SYSTEM.md`, ADR-027, and Decision 011. This is a controlled internal port, not general external-tool execution — no calendar, email, GitHub, filesystem, or shell access exists.

## Sequencing change: Tool Foundation moved ahead of Scheduler/Reminder

**Recorded August 2026, ADR-027.** The sequence below (documentation sync,
audit, then Scheduler/Reminder v0.1) was the plan through PR #31. V0.2A
changes the order: a Tool Foundation (`docs/TOOL_SYSTEM.md`, ADR-027,
Decision 011) is built *before* the scheduler, on branch
`claude/motos-v0.2a-tool-foundation-u46ew4` (not yet merged to `main`).

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

Write-capable actions use frozen operation parameters, risk-classified policy checks, human approval when required, and Run records. Implemented for four internal tools in V0.2A on the branch above; write-capable *external* actions (Calendar, Gmail, GitHub, and similar) remain future work that can plug into this same boundary.

## Near-term product direction

After a reliable scheduler/reminder loop is proven, likely next candidates are:

- Task/reminder review UI
- recurrence only if one-time reminders are stable
- controlled calendar/read-only tools
- approval infrastructure before write-capable tools
- project dashboards that aggregate existing conversations, memories, Tasks, and reminders rather than duplicating data

## Deferred capabilities

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

## Long-term sequence

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
