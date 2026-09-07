# Continuous Builder — Persistence / Store Authority Map

**Status:** Targeted hardening (docs-only) following Architecture Economy Audit 2026-09  
**Parent audit:** `docs/future/CONTINUOUS_BUILDER_ARCHITECTURE_ECONOMY_AUDIT_2026_09.md`  
**Related ADR:** `docs/future/adrs/ADR-044-builder-queue-vs-gpd-execution-lifecycle.md`  
**Base Main (trusted):** `ba241118d5c9aa7a64df487275eb36a09bcc0826`  
**Date (America/New_York):** 2026-09-06  

**Non-goals:** This document does **not** authorize schema migrations, SQLite promotion of GP-D, merging stores, renaming states, granting execution/merge/publication authority, or any production code change.

---

## 1. Purpose

Before GP-E binds dispatch, every control-plane fact must answer: **which store is source of truth?** Worker claims, receipts, and caches never override that answer.

Three planes exist today:

| Plane | Primary persistence | Owns | Does **not** own |
| --- | --- | --- | --- |
| **Product / roadmap / slice lifecycle** | SQLite `builder_*` via `queue_store.py` (+ related queue/lease/audit tables) | Blueprint/slice progression through queue PRIMARY/SIDE states | Durable execution job truth, attempt ledger for GP-D jobs, SE certainty, EXECUTION_UNKNOWN |
| **Execution job lifecycle (GP-D)** | Append-only **JSONL** ledger under `gpd_job_store.py` | Job header, events, derived state, attempts, leases/HB, checkpoints, SE identity, reconciliation | Product roadmap position, “slice done”, Main merge, publication authorization |
| **Evidence / receipts / logs** | Content store / files / sealed receipt objects | Reconstructible evidence and digests | Trusted state; cannot flip queue or GPD derived state by themselves |

---

## 2. Plane A — `builder_*` SQLite / queue

**Modules (illustrative):** `queue_store.py`, `queue_projection.py`, `leases.py`, `audit.py`, migrations already on Main (006/007 era — not modified by this hardening).

**Owns:**

- Slice / product lifecycle along `PRIMARY`:  
  `idea → researching → designing → ready → scheduled → building → reviewing → staging → testing → ready_for_main → done`
- Side states: `blocked`, `changes_requested`, `paused`, `superseded`, `retired`, `cancelled`
- Append-only queue events + projected current slice state (projection ≤ event sequence)
- Product-side attempt/lease rows in `leases.py` (slice-oriented ownership; **not** the GP-D heartbeat/lease JSONL)
- Whether a slice is in an `EXECUTION_CAPABLE_STATES` queue state (`ready` onward in PRIMARY) — a **product** eligibility signal, **not** proof a GP-D job is execution-ready

**Does not own:**

- GP-D derived job state (`created`…`terminal_*`)
- Whether a worker lease for a **DurableJob** is live
- Checkpoint history for GP-D jobs
- Side-effect certainty / `execution_unknown` / reconciliation verdicts for execution
- Verification referee outcomes as durable execution truth
- PR publication or Main merge authority

**Rule:** Queue state answers “where is this **slice** in the product roadmap?” It must **never** be treated as “where is this **execution job**?”

---

## 3. Plane B — GP-D JSONL durable job ledger

**Modules (illustrative):** `gpd_job_store.py`, `gpd_job_header.py`, `gpd_job_events.py`, `gpd_job_state.py`, `gpd_attempt_ledger.py`, `gpd_heartbeat_lease.py`, `gpd_checkpoint.py`, `gpd_side_effect.py`, `gpd_recovery.py`, `gpd_failure.py`.

**Layout (per job):**

```
<root>/jobs/<job_id>/header.json
<root>/jobs/<job_id>/events.jsonl
<root>/jobs/<job_id>/attempts.jsonl
<root>/jobs/<job_id>/leases.jsonl
<root>/jobs/<job_id>/heartbeats.jsonl
<root>/jobs/<job_id>/checkpoints.jsonl
<root>/jobs/<job_id>/side_effects.jsonl
<root>/jobs/<job_id>/reconciliations.jsonl
```

**Owns:**

- Durable job / attempt / checkpoint / lease / heartbeat evidence
- Derived job state from `JOB_STATES` (cached only when reconstructible from events)
- `execution_unknown`, reconciliation records, side-effect identity / duplicate detection
- Explicit rule: **worker success alone never becomes `terminal_success`** (`gpd_job_state.py`)

**Does not own:**

- Product/roadmap slice position (`idea`…`done`)
- Blueprint approval as a substitute for execution terminality
- Main merge or GitHub publication

**Rule:** GPD answers “what is the durable **execution** truth for this job?” It must **never** be treated as the product backlog or slice lifecycle store.

**JSONL phase posture:** JSONL is **OK for the current phase** (no SQLite schema required for GP-D). It is **not** declared permanent. SQLite promotion is **deferred**, requires a **human-approved migration**, backup/restore drill, and a separate ADR/migration PR. This map does **not** authorize that migration.

---

## 4. Plane C — Evidence / receipts / logs

**Examples:** verifier/check receipts, worker execution receipts, CE packages, GPA/GPB sealed evidence, supervisor classifications, audit metadata, large log blobs referenced by digest.

**Owns:**

- Evidence, cache, and reconstructible observations
- Digests that *bind* claims to bytes

**Does not own:**

- Ability to override trusted/derived state in queue or GPD
- Authority flags (`publication_authorized`, merge, GitHub, queue transition, etc. remain structurally false on evidence snapshots unless a **separate** trusted authority path grants them — this doc grants none)

**Rule:** Receipt ≠ proof of terminal success; evidence ≠ authority; classification ≠ queue transition.

---

## 5. Source-of-truth table

| Fact | Source of truth | Not authoritative |
| --- | --- | --- |
| **Builder slice lifecycle** (idea…done / side states) | Queue SQLite events + projection (`queue_store`) | GPD JSONL; worker narrative; CE package |
| **Execution job lifecycle** (created…terminal_*) | GPD event log → derived state (`gpd_job_state`) | Queue PRIMARY state; worker “success” claim alone |
| **Attempt history (execution)** | GPD `attempts.jsonl` | Queue `builder_attempts` / product leases; provider chat |
| **Attempt history (product/slice)** | Queue/lease SQLite (`leases.py` / related) | GPD attempt ledger |
| **Current execution state** | GPD derived state from events (reconstructible) | Queue `building`/`ready`; ephemeral process memory |
| **Checkpoint history** | GPD `checkpoints.jsonl` | Queue projection; CE progress notes |
| **Lease ownership (execution)** | GPD `leases.jsonl` + heartbeat evidence | Queue product lease rows; worker self-report |
| **Heartbeat / progress (execution)** | GPD heartbeats / checkpoints | Queue timestamps alone; provider streaming text |
| **SE certainty / duplicate SE identity** | GPD side_effects + reconciliation records | Worker claim; missed heartbeat alone (“no SE”) |
| **Reconciliation** | GPD `reconciliations.jsonl` (+ related recovery) | Automatic inference from lease expiry |
| **Provider / worker output** | Untrusted artifacts + bounded receipts (evidence plane) | Never overrides GPD terminality or queue state |
| **Verification result** | Trusted verifier/check path receipts (TCB referee) | Worker self-grade; GPD `running` alone |
| **PR publication receipt** | Publication authority surface / receipts (TCB publication path when used) | Worker; queue `ready_for_main`; GPD `terminal_success` |
| **Main merge state** | Human-gated Main process / external VCS truth | Any CB store; staging autonomy; worker |

---

## 6. Cross-plane binding (conceptual only)

GP-E (future) may **correlate** a queue slice identity with a GPD `job_id` via explicit sealed references. Correlation is not identity:

- One slice ≠ one job by axiom (a slice may have zero, one, or many execution jobs over time).
- Advancing queue to `done` must not be inferred solely from worker success or even from GPD `terminal_success` without the product-plane transition rules and any human gates that apply.
- GPD `ready` is **not** queue `ready` (see concept glossary).

No binding in this document grants launch, merge, or publication authority.

---

## 7. Deferred decisions (explicit)

| Decision | Default now | Blocked until |
| --- | --- | --- |
| Promote GPD JSONL → SQLite | **Defer**; JSONL OK for phase | Human-approved migration + drills |
| Unify `leases.py` with `gpd_heartbeat_lease` | **Do not unify** | Separate architecture decision (high risk) |
| Treat queue as execution truth | **Forbidden** | Never (security/product error) |
| Treat GPD as roadmap truth | **Forbidden** | Never |

---

## 8. Integrity

- Docs-only; backend production tree unchanged by this file.
- Does not amend TCB, trusted_policy, schemas, or state machines.
