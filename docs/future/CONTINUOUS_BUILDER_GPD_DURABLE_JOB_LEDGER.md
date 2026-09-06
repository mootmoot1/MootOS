# GP-D — Durable Job Ledger / Checkpoint / Recovery

Trusted Main base: `48233394d4ccce88244adc5c7133efea92df60fb` (PR #97 GP-C
merged). This phase is **control-plane only**. **ZERO EXECUTION
AUTHORITY** — nothing here launches workers/providers (Claude/Codex/Grok/
GPU), mutates GitHub, runs autonomous retries, widens sealed ceilings,
edits TCB/`trusted_policy`, or merges Main. **DO NOT MERGE AUTOMATICALLY.**

## Purpose

GP-D answers: **what is the durable system truth for a Golden Plan job
across process/provider/session loss?**

```text
DurableJobHeader (immutable bindings to GP-B/GP-C + ceilings)
    |
    v
Append-only JobEvent log (+ digest chaining)
    |
    +-- Attempt ledger (retry = new attempt identity)
    +-- Heartbeat / Lease / Stall evidence
    +-- Bounded Checkpoint contracts
    +-- Side-effect identity + EXECUTION_UNKNOWN + Reconciliation
    |
    v
Deterministic reducer -> DerivedJobState
    |
    v
Recovery reconstruction (no launch)
```

**SYSTEM OWNS TRUTH. WORKER ONLY PROPOSES.**

## Conflict with old CB job concepts (reported, not rewritten)

Existing `builder_*` tables / `queue_store.py` / `leases.py` model a
**blueprint-slice product lifecycle** (`idea → … → done`) with attempts
FK-bound to slices. ADR-041 notes worker-dispatch vocabulary remains
open. GP-D models a **job execution lifecycle** bound to
`FrozenTaskContract` / `ExecutionPlan` / `AdmissionDecision`. Overloading
`builder_events` would conflate vocabularies. GP-D therefore adds a
parallel `gpd_*` ledger family and does **not** rewrite CB queue tables.

## Persistence decision (no schema migration in this PR)

SQLite migration for first-class `gpd_*` tables would be the long-term
production path, but this autonomous run **STOPS before migration** per
Golden Plan rules. Instead GP-D uses a **file-backed append-only JSONL
ledger** (`JobLedgerStore`) with atomic header writes — durable across
restart without touching `backend/migrations.py` / production
`mootos.db`. A future human-approved migration can promote the same
contracts into SQLite.

## Module inventory

| Module | Slice | Role |
| --- | --- | --- |
| `gpd_job_header.py` | D1 | Immutable DurableJobHeader |
| `gpd_job_events.py` | D2 | Append-only events + digest chain |
| `gpd_job_store.py` | D2/D8 | File-backed durable ledger |
| `gpd_job_state.py` | D3 | Derived state machine reducer |
| `gpd_attempt_ledger.py` | D4 | Attempt identities |
| `gpd_heartbeat_lease.py` | D5 | Heartbeat / lease / stall evidence |
| `gpd_checkpoint.py` | D6 | Bounded checkpoint contract |
| `gpd_side_effect.py` | D7 | SE identity / UNKNOWN / reconcile |
| `gpd_failure.py` | D7 | Small failure taxonomy |
| `gpd_recovery.py` | D8 | Restart reconstruction (no launch) |
| `gpd_eval_corpus.py` | D9 | Adversarial corpus |

## How GP-D binds GP-B / GP-C

1. Header seals contract/plan/admission digests + TCB/policy versions.
2. `allow_within_bound` remains **admission evidence**, not launch.
3. `execution_authorized` / provider / merge / Main flags stay False.
4. Required human gates from the contract survive recovery.
5. Stale contract/admission/TCB bindings fail closed on reconstruct.

## EXECUTION_UNKNOWN

Lost contact while a side effect may have happened → state
`execution_unknown`. Blind retry of non-idempotent external actions is
blocked until an explicit `ReconciliationRecord` marks retry eligibility.

## Recovery invariants (tested)

History survives restart; retry = new attempt; no rewrite of prior;
duplicate event IDs rejected; sequence violations fail; malformed
rejected; stale contract/admission rejected; ceilings cannot widen;
cancelled ≠ running; terminal ≠ silent reopen; worker success alone ≠
terminal_success; missing proof → execution_unknown; unknown ≠ blind
retry; reconcile first; duplicate SE identity detected; heartbeat
without progress = stall evidence; expired lease ≠ no SE; checkpoint
tamper detected; recovery deterministic; rebuild twice identical; GP-C
human gates survive; Main merge human-controlled.

## Non-guarantees / deferred to GP-E+

- Worker/provider launch and dispatch authorization enforcement at runtime
- GitHub / network side-effect **execution** (identity only here)
- SQLite schema migration for `gpd_*` tables (human STOP)
- TCB registry expansion (none in this PR; propose-only)
- Parallel writers / consensus / Kafka

## Architecture economy

Reuses `gpa_eval_schema` digests/AUTHORITY_FLAGS, GP-B contracts/plans,
GP-C decisions, `trusted_policy` snapshots, supervisor failure vocabulary,
lease/idempotency *concepts* from `leases.py` (not the slice-FK tables),
and timestamp helpers. No enterprise cosplay.

## GP-E handoff readiness

GP-E can consume: sealed headers, event log, derived state, attempt
identities, lease/stall evidence, checkpoints, SE identity +
reconciliation gates, and recovery views — still without treating any of
them as launch permission until a separate dispatch authorization phase.

## STOP points obeyed

No schema migration applied; no TCB/`trusted_policy` edit; no worker/
provider/GitHub execution; no Main merge; no autonomous retries; dirty
primary `/Users/freeman/Desktop/MootOS` untouched.
