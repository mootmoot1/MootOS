# ADR-043 — Continuous Builder planning, providers, retries, and outcomes are deterministic and receipt-driven

## Status

Partially implemented. No autonomous scheduler is enabled by this record or by any code in this repository. The Chief Builder priority policy (`backend/continuous_builder/priority_policy.py`, `POLICY_VERSION = "adr-043-v1"`) is implemented -- see "Chief Builder policy" below for one deliberate simplification versus the tuple originally described here. Provider neutrality, failure classification, and retry/stall/uncertainty semantics remain unimplemented: no provider adapter, worker dispatch, or retry loop exists.

## Provider neutrality

Planning, coding, and advisory review use separate provider protocols. Each invocation records role, adapter name/version, model identifier as supplied by the provider, configuration digest, request/artifact digest, budgets, and receipt. Provider identity is not externally authenticated unless a later mechanism proves it. A provider cannot grant capabilities, modify policy, select commands, approve output, or report authoritative state.

## Chief Builder policy

The Chief Builder computes eligibility and priority using ADR-037's closed rules. The default priority tuple is: blueprint priority class; number and priority of eligible descendants unblocked by completion; oldest durable eligibility sequence; and normalized stable slice ID.

**Implementation note (Phase 2.5):** `priority_policy.py`'s `dependency_unblocking_value` implements the descendant-count term as a raw transitive-descendant count (`_descendant_counts`), not weighted by each descendant's own priority class as "number and priority of eligible descendants" could be read to require. This is a deliberate, documented simplification rather than a defect: priority-weighting descendants would change existing rank ordering (and the tests that pin it) for a benefit that has no concrete use case yet, since no scheduler consumes this ranking. Re-deriving a priority-weighted term remains open for whenever a real scheduler is built against this policy. Similarly, "operator-pinned emergencies" (the explicit-input override mentioned below) has no distinct field or authority class in `blueprint.py`/`priority_policy.py` today -- only `critical/high/normal/low` priority classes exist; an operator-pin mechanism is unimplemented, not merely undocumented.

Security fixes and operator-pinned emergencies require explicit blueprint/policy input; prose urgency from a worker cannot raise priority. The planner emits a deterministic plan receipt containing every candidate, exclusion reason, score component, tie-break, policy version, and source digests.

## Failure, retry, stall, and uncertainty

Failures are classified from mechanical receipts: `invalid_request`, `policy_denied`, `provider_unavailable`, `worker_failed`, `verification_failed`, `environment_failed`, `stalled`, `cancelled`, `uncertain`, or `needs_human`. Narrative cannot override classification.

The inherited capability-build correction limit is at most two bounded fix rounds, but enabling any automated round requires a slice-specific approved budget. Retries retain the exact scope/base/policy and use new attempt identities. Argument, scope, base, dependency, provider-policy, or registry change requires re-planning and fresh approval where authority changes.

No retry occurs after an uncertain external side effect. A missed heartbeat, supervisor crash, cancellation timeout, duplicate receipt, or ambiguous artifact state becomes `uncertain` until reconciled. No endless loop, implicit backoff queue, or “best effort” continuation is allowed. Consecutive failures and total attempt/time/token/compute budgets stop the slice or control plane.

**Implementation note (Phase 2.5):** `leases.py` implements exactly this pattern for lease expiry: `inspect_lease` reports `expired_uncertain` (never a claim that the worker stopped) until `reconcile_expired_lease` records an explicit, audited verdict. A `worker_confirmed_running` verdict surfaces as `needs_human` -- this ADR's `needs_human` classification, concretely realized -- and leaves the lease held; only `worker_confirmed_stopped` releases it. No heartbeat mechanism exists yet (heartbeats are not implemented, only lease expiry/reconciliation), so "missed heartbeat" above remains aspirational pending a future slice.

Dependent slices remain blocked after prerequisite failure. Independent work may continue only when conflict, global budget, and kill-switch checks still pass. A stalled slice cannot hold an unbounded lease.

## Mission and audit receipts

State is derived from queue, provider, verifier, approval, and external receipts. Required metadata includes blueprint/slice/attempt identities, source/base/tree digests, dependency snapshot, provider/config identity, policy versions, budgets consumed, timestamps supplied by the control plane, transition reasons, evidence digests, and explicit authentication/verification booleans.

## Escalation

Ambiguous requirements, new shared abstractions, protected-core changes outside approved scope, repeated verification failure, exhausted budgets, inconsistent receipts, or any requested authority expansion produce a bounded change proposal for human decision. They never silently mutate the blueprint.

