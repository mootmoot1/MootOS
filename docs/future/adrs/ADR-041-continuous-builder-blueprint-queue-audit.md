# ADR-041 — Continuous Builder binds approved blueprints to an append-only durable queue

## Status

Implemented (migrations 006/007, `backend/migrations.py`; `backend/continuous_builder/{queue_store,queue_projection,leases,audit}.py`). Originally "Proposed... does not add tables, migrations, or a running queue" -- that persistence layer has since been built and merged. The event-sourcing/digest-chaining/fail-closed-transition *model* described below is implemented exactly; see "Queue states" for a vocabulary correction.

## Blueprint contract

The canonical blueprint is bounded, versioned JSON. Its identity is SHA-256 over canonical UTF-8 serialization. It contains `schema_version`, `blueprint_id`, `blueprint_version`, source commit, content digest, supplied approval record, global budgets/boundaries, systems, and slices.

Each slice declares a stable ID and version, objective, acceptance criteria, hard and soft dependencies, required capabilities, expected risk, exact allowed paths, test requirements, rollback, priority class, budgets, and authority requested/not requested. Unknown fields fail closed. Human-readable text is bounded and sanitized. Raw prompts, provider state, credentials, commands, and tool output are excluded.

Approval binds the exact blueprint digest. The record distinguishes supplied approver identity, internally bound identity, and externally authenticated identity. Until an authentication ADR is implemented, authentication is false. Any content mutation creates a new blueprint version requiring approval.

## Durable queue and audit model

After a separately approved migration, storage consists logically of immutable blueprint snapshots, immutable slice versions, append-only queue events, attempt/lease records, and bounded audit receipts. Current state is a replayed projection; a cached projection is never more authoritative than its event sequence.

Every event binds blueprint/slice version, prior event sequence and digest, transition, actor kind and supplied identity, reason code, dependency snapshot, attempt identity, evidence digests, and deterministic event payload. Transition validation uses a closed state machine. Unknown, skipped, stale, or conflicting transitions fail closed.

Writes use database transactions and compare-and-swap on the last sequence/digest. A lease has an owner identity, attempt identity, bounded expiry, and heartbeat policy. An expired lease makes the outcome uncertain; it does not prove the worker stopped. Re-dispatch requires reconciliation and a new attempt ID.

Idempotency keys represent request identity. Durable replay protection exists only when a unique constraint/transaction records them. No in-memory digest claims cross-process uniqueness.

Audit records are sanitized metadata, not raw logs. Large logs/artifacts live in a separately governed content store and are referenced by digest. Hash chaining detects some mutation but is not external attestation; stronger tamper evidence and retention policy are deferred.

## Queue states

**Implemented vocabulary (authoritative, supersedes the illustrative list below):** `backend/continuous_builder/queue_store.py` implements primary states `idea, researching, designing, ready, scheduled, building, reviewing, staging, testing, ready_for_main, done` and side-states `blocked, changes_requested, paused, superseded, retired, cancelled`, with a closed `TRANSITIONS` table. This differs from the illustrative vocabulary this ADR originally sketched; the implemented names track a slice through design/build/review rather than a worker-dispatch lifecycle, since no worker dispatch exists yet (ADR-042 is still unimplemented). Re-deriving `proposed`/`leased`/`running`/`artifact_returned` for an eventual worker-dispatch phase remains open, not abandoned -- Phase 2.5 deliberately did not rename the merged, event-sourced, test-covered vocabulary below to match this ADR, since doing so would rewrite already-persisted event semantics for no safety benefit.

The minimum future vocabulary originally sketched here was `proposed`, `approved`, `eligible`, `leased`, `running`, `artifact_returned`, `verifying`, `needs_correction`, `ready_for_human`, `blocked`, `failed`, `cancelled`, and `complete`. External publication/deployment states belong to their own action/receipt models. “Complete” means the approved build slice exhausted its local state machine, not merged or deployed.

## Persistence rollout

Before schema work: approve exact migration, backup/restore drill, concurrency tests, downgrade/feature-disable procedure, and retention limits. Persistence must not reuse production tool-operation tables as a hidden mission engine. No schema change is authorized by this ADR alone.

