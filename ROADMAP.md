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

The repository currently has no scheduler, reminder delivery, recurrence, background worker, external-tool executor, approval UI, or multi-user system.

## Immediate sequence

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

### Future approvals/tools

Write-capable external actions should eventually use frozen operation parameters, policy checks, approvals when needed, and Run records.

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
