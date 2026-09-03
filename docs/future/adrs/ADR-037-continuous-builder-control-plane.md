# ADR-037 — Continuous Builder is a bounded control plane over existing workers

## Status

Proposed. This decision grants no authority until its implementation slices are separately approved and merged.

## Context

V0.4A–V0.4C provide offline build evidence, workflow, human-review, publication-authorization, inert-action, and external-receipt contracts. V0.4D proves bounded composition through the live Tool Registry and central executor. None launches coding workers, owns a durable build queue, executes GitHub operations, or provisions an Evolution Lab.

Continuous Builder must coordinate those seams without becoming a second registry, executor, approval system, or source of product truth.

## Decision

Continuous Builder is a control plane with five separately authorized roles:

1. **Blueprint loader** validates an exact approved blueprint version and digest.
2. **Chief Builder** deterministically derives eligible work and priority from that blueprint plus durable receipts.
3. **Worker supervisor** may dispatch replaceable coding providers only inside the containment contract in ADR-042.
4. **Verifier** reconstructs and evaluates worker artifacts using its own approved command policy.
5. **Publication/staging adapters** remain separate future authorities governed by ADR-038 and additional execution ADRs.

The Chief Builder may select, dispatch, monitor, cancel, verify, request a bounded correction, and assemble review evidence only after each authority-bearing boundary is implemented and approved. It may never alter the blueprint, invent work, widen scope, approve its own output, merge Main, deploy production, or convert worker text into authority.

## Sources of truth

| Question | Authority |
| --- | --- |
| Product intent and slice scope | Exact human-approved blueprint version |
| Executable MootOS tools | Live Tool Registry |
| Build eligibility | Blueprint dependencies plus durable verified receipts |
| Queue state | Validated append-only queue events |
| Worker artifact | Untrusted patch/artifact until independent verification |
| Verification result | Trusted verifier receipt bound to exact base, scope, tree, and commands |
| Approval | A distinct human decision/authorization record |
| External truth | Independently verified external receipt, when a future verifier exists |

`authoritative` means internally reconstructed and invariant-checked. It does not mean externally authenticated, signed, or attested.

## Deterministic planning policy

A slice is eligible only when its exact blueprint version is approved, every hard dependency has a passing authoritative receipt, no conflicting active lease exists, its required provider and verifier policies are available, and all budgets permit another attempt. Soft dependencies affect priority but never silently become hard gates.

Among eligible slices, order by the blueprint's explicit priority class, then dependency-unblocking value, then oldest queue eligibility sequence, then normalized stable slice ID. Every input and tie-break is recorded. Model narration may propose a change but cannot decide eligibility or priority. An ambiguity produces `needs_human`; it is not filled by inference.

## Authority boundaries

Initial implementation remains advisory and in-memory. Durable state, automated dispatch, command execution, GitHub operations, staging promotion, and Lab provisioning each require the ADR and hard approval stop identified in the implementation program.

No monolithic `continuous_builder` tool is created. Existing V0.4C capability-build models are precedent for immutable binding, not a runtime path. V0.4D's registry/executor composition is reused only where registered MootOS tools are actually needed; coding workers use the distinct, contained provider protocol in ADR-042.

## Consequences

- Providers are replaceable and untrusted; policy and evidence remain MootOS-owned.
- State is derived from receipts, never agent claims.
- Control-plane convenience cannot bypass approval or execution boundaries.
- Parallelism is permitted only after durable leases and conflict checks exist.
- Main and production remain human-gated.
