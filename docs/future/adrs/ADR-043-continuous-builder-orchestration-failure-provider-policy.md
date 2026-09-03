# ADR-043 — Continuous Builder planning, providers, retries, and outcomes are deterministic and receipt-driven

## Status

Proposed. No autonomous scheduler is enabled by this record.

## Provider neutrality

Planning, coding, and advisory review use separate provider protocols. Each invocation records role, adapter name/version, model identifier as supplied by the provider, configuration digest, request/artifact digest, budgets, and receipt. Provider identity is not externally authenticated unless a later mechanism proves it. A provider cannot grant capabilities, modify policy, select commands, approve output, or report authoritative state.

## Chief Builder policy

The Chief Builder computes eligibility and priority using ADR-037's closed rules. The default priority tuple is: blueprint priority class; number and priority of eligible descendants unblocked by completion; oldest durable eligibility sequence; and normalized stable slice ID.

Security fixes and operator-pinned emergencies require explicit blueprint/policy input; prose urgency from a worker cannot raise priority. The planner emits a deterministic plan receipt containing every candidate, exclusion reason, score component, tie-break, policy version, and source digests.

## Failure, retry, stall, and uncertainty

Failures are classified from mechanical receipts: `invalid_request`, `policy_denied`, `provider_unavailable`, `worker_failed`, `verification_failed`, `environment_failed`, `stalled`, `cancelled`, `uncertain`, or `needs_human`. Narrative cannot override classification.

The inherited capability-build correction limit is at most two bounded fix rounds, but enabling any automated round requires a slice-specific approved budget. Retries retain the exact scope/base/policy and use new attempt identities. Argument, scope, base, dependency, provider-policy, or registry change requires re-planning and fresh approval where authority changes.

No retry occurs after an uncertain external side effect. A missed heartbeat, supervisor crash, cancellation timeout, duplicate receipt, or ambiguous artifact state becomes `uncertain` until reconciled. No endless loop, implicit backoff queue, or “best effort” continuation is allowed. Consecutive failures and total attempt/time/token/compute budgets stop the slice or control plane.

Dependent slices remain blocked after prerequisite failure. Independent work may continue only when conflict, global budget, and kill-switch checks still pass. A stalled slice cannot hold an unbounded lease.

## Mission and audit receipts

State is derived from queue, provider, verifier, approval, and external receipts. Required metadata includes blueprint/slice/attempt identities, source/base/tree digests, dependency snapshot, provider/config identity, policy versions, budgets consumed, timestamps supplied by the control plane, transition reasons, evidence digests, and explicit authentication/verification booleans.

## Escalation

Ambiguous requirements, new shared abstractions, protected-core changes outside approved scope, repeated verification failure, exhausted budgets, inconsistent receipts, or any requested authority expansion produce a bounded change proposal for human decision. They never silently mutate the blueprint.

