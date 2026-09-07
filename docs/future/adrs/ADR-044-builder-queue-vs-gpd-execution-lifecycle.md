# ADR-044 — Builder queue lifecycle and GP-D execution lifecycle are separate machines

## Status

Accepted for documentation / GP-E binding guidance. **Docs-only** in the Architecture Economy targeted-hardening pass. Does not enable worker dispatch, merge, publication, schema migration, or state renames.

## Context

Continuous Builder persists two durable lifecycles:

1. **Product / roadmap / slice lifecycle** in SQLite via `backend/continuous_builder/queue_store.py` (ADR-041 durable queue).
2. **Execution job lifecycle** in the GP-D append-only JSONL ledger via `gpd_job_store.py` / `gpd_job_state.py` (GP-D durable job ledger).

The Architecture Economy Audit (2026-09) found that accidental complexity is dominated by **worker and author confusion** between these machines (especially the shared token `ready`), not by redundant transition tables inside one module. GP-E must bind dispatch to the correct durable truth without collapsing the planes.

Related: ADR-041 (blueprint ↔ append-only queue); ADR-042 (containment/verifier); ADR-043 (deterministic receipt-driven outcomes); GP-C (admission ≠ execution); GP-D handoff notes.

## Decision

### D1 — Two machines, two authorities

| Machine | Authoritative store | State vocabulary (implemented names) |
| --- | --- | --- |
| **Builder / queue lifecycle** | SQLite `builder_*` queue events + projection | PRIMARY: `idea`, `researching`, `designing`, `ready`, `scheduled`, `building`, `reviewing`, `staging`, `testing`, `ready_for_main`, `done`. SIDE: `blocked`, `changes_requested`, `paused`, `superseded`, `retired`, `cancelled`. |
| **GP-D execution lifecycle** | JSONL job ledger; derived state from events | `created`, `admitted`, `ready`, `leased`, `running`, `waiting`, `checkpointed`, `cancellation_requested`, `cancelled`, `stalled`, `timed_out`, `failed`, `execution_unknown`, `reconciling`, `retryable`, `terminal_success`, `terminal_failure`. |

Neither machine is a projection of the other.

### D2 — Boundary rules (normative)

1. **A GPD job is not a builder slice.** Correlation by sealed IDs is allowed; identity collapse is forbidden.
2. **Queue is not execution truth.** Queue PRIMARY/SIDE must not be used as the source of truth for lease ownership, checkpoints, SE certainty, `execution_unknown`, or `terminal_*`.
3. **GPD is not roadmap truth.** GPD states must not be used as the source of truth for product position (`idea`…`done`) or backlog ordering.
4. **Homonym `ready`:** Queue `ready` means product/slice readiness (and is the start of `EXECUTION_CAPABLE_STATES`). GPD `ready` means the durable execution job is ready to lease/dispatch in the ledger. Docs and GP-E code comments must disambiguate; **do not rename** production tokens in this ADR.
5. **No auto-complete of product from worker claim.** Worker success, provider “done”, or even raw process exit must not alone transition queue to `done` or GPD to `terminal_success`. GPD already encodes: worker success alone never becomes `terminal_success`. Queue transitions remain under queue transition rules / authority — this ADR grants none.
6. **Lease expiry ≠ no side effect.** Expiry ⇒ uncertain until reconciliation; it does not prove absence of SE or that the worker stopped.
7. **Evidence/receipts never override** trusted or derived store state (see Persistence Authority Map).
8. **JSONL remains acceptable** for the current GP-D phase. SQLite promotion of the GPD ledger is a **deferred, human-approved migration** — not authorized here.
9. **`EXECUTION_CAPABLE_STATES`** (queue: PRIMARY from `ready` onward) is a **product-plane** eligibility region. It does not imply a GPD job is in GPD `ready`, leased, or authorized to launch.

### D3 — What GP-E may assume

GP-E may:

- Read sealed GPD headers, events, derived state, attempts, leases/stalls, checkpoints, SE identity, and reconciliation as **execution** inputs.
- Read queue projection/events as **product** inputs.
- Require explicit correlation records when binding slice ↔ job.

GP-E must not:

- Treat queue `ready`/`building`/`done` as substitutes for GPD `ready`/`running`/`terminal_success`.
- Treat GPD `terminal_success` as Main merge or publication authorization.
- Treat GP-C admission allow as launch authorization (unchanged from GP-C invariants).
- Expand TCB or change trusted_policy to “make the dual store easier.”

## Consequences

### Positive

- GP-E authors have an explicit dual-lifecycle contract before dispatch binding.
- Workers and docs can be trained on qualified `ready` language.
- Dual persistence cost is acknowledged as intentional until a future migration ADR.

### Negative / accepted cost

- Two stores and two vocabularies remain until a human-approved promotion/unification decision.
- Authors must keep correlation explicit (more fields, not fewer concepts).

### Explicit non-changes

- No production state renames.
- No merge of `queue_store` with `gpd_job_store`.
- No unify of `leases.py` with `gpd_heartbeat_lease.py`.
- No TCB / trusted_policy / schema / migration changes from this ADR alone.
- No grant of execution, merge, GitHub, or publication authority.

## References

- `docs/future/CONTINUOUS_BUILDER_PERSISTENCE_AUTHORITY_MAP.md`
- `docs/future/CONTINUOUS_BUILDER_CONCEPT_GLOSSARY.md`
- `docs/future/CONTINUOUS_BUILDER_ARCHITECTURE_ECONOMY_AUDIT_2026_09.md`
- `docs/future/adrs/ADR-041-continuous-builder-blueprint-queue-audit.md`
- `backend/continuous_builder/queue_store.py` (`PRIMARY`, `SIDE`, `EXECUTION_CAPABLE_STATES`)
- `backend/continuous_builder/gpd_job_state.py` (`JOB_STATES`)
