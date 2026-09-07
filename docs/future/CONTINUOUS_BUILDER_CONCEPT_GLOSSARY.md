# Continuous Builder — Concept Glossary

**Status:** Targeted hardening (docs-only) following Architecture Economy Audit 2026-09  
**Parent audit:** `docs/future/CONTINUOUS_BUILDER_ARCHITECTURE_ECONOMY_AUDIT_2026_09.md`  
**Related:** Persistence map; ADR-044  
**Date (America/New_York):** 2026-09-06  

**Hard rule:** This glossary **does not rename** production states, modules, or flags. It disambiguates overloaded English for humans and future GP-E authors.

---

## Critical homonym: `ready`

| Token | Machine | Meaning | Not |
| --- | --- | --- | --- |
| **queue `ready`** | `queue_store.PRIMARY` | Product/slice has finished design and is product-ready for later scheduling/build stages. First state in `EXECUTION_CAPABLE_STATES`. | Proof a GP-D job exists, is admitted, or may be leased |
| **GPD `ready`** | `gpd_job_state.JOB_STATES` | Durable execution job has been admitted and is ready for lease/dispatch **in the execution ledger**. | Proof the blueprint slice is queue-`ready`, or that Main may merge |

**Always qualify in docs and discussions:** “queue ready” vs “GPD ready” (or “product ready” vs “execution ready”). Never write bare `ready` across planes without a prefix.

---

## Lifecycle identities

| Term | Definition | Distinguishes from |
| --- | --- | --- |
| **Slice** | Blueprint unit tracked in the durable **queue** (product/roadmap lifecycle). | GPD job; GP-B node; worker process |
| **Job (GPD / DurableJob)** | Execution unit in the GP-D JSONL ledger (`DurableJobHeader` + events). | Queue slice; “job” colloquialism for slice |
| **Attempt** | One bounded try under a job (GPD attempt ledger) **or** a product-side attempt/lease row — **always name which**. | The job itself; retry policy |
| **Retry** | New attempt identity under same (or re-planned) scope after a classified failure, when policy allows. | **Replay** of the same durable event/request identity |
| **Replay** | Re-processing an already-recorded durable identity (idempotency / event replay). | Starting a new attempt |
| **Checkpoint** | GPD durable checkpoint contract/evidence for execution resume semantics. | CE progress notes; queue projection cache |
| **Lease (product)** | SQLite lease/attempt ownership in `leases.py` for queue coordination. | GPD JSONL lease |
| **Lease (GPD)** | Execution lease record + heartbeat evidence in the job ledger. | Product lease; “worker said it’s fine” |
| **Lease expiry** | Lease no longer valid → outcome **uncertain** until reconciliation. | Proof of **no side effect (SE)**; proof worker stopped |
| **Heartbeat** | Bounded progress/liveness evidence for an execution lease. | Authority; terminal success |
| **Side effect (SE)** | External mutable effect tracked by GPD SE identity. | Log line; receipt file |
| **EXECUTION_UNKNOWN** | GPD state: execution outcome not safely known. | “Probably failed”; silent continue |
| **Reconciliation** | Explicit recorded verdict resolving uncertainty (lease/SE/crash). | Automatic guess from timeout alone |
| **terminal_success / terminal_failure** | GPD terminal derived states from validated events. | Worker exit 0; provider “done”; queue `done` |
| **Queue `done`** | Product slice exhausted its **queue** primary lifecycle. | Main merged; GPD terminal_success |
| **ready_for_main** | Queue state: product path waiting on Main human gate semantics. | Publication authorized; merge executed |

---

## Authority vs capability vs evidence

| Term | Definition | Distinguishes from |
| --- | --- | --- |
| **Capability** | What a request *asks* to do within bounds (GP-C vocabulary / admission input). | **Authority** to publish, merge, transition queue, or call GitHub |
| **Authority (flags)** | Explicit bools such as publication / queue transition / GitHub / merge — structurally false on evidence unless a trusted authority path says otherwise. | Capability allow; worker success |
| **Admission** | GP-C trusted decision: allow_within_bound / require_human_approval / deny / escalate / insufficient_evidence. Does **not** execute. | Launch authorization; dispatch |
| **Execution authorization / launch** | Separate future/control-plane act (not granted by this glossary or by GP-C decision alone). | Admission allow; GPD `ready` |
| **Receipt** | Bounded sealed metadata recording what was observed or decided. | **Proof** of terminal success or Main merge |
| **Evidence** | Reconstructible bytes/digests supporting a claim. | Trusted state override |
| **Proof** | Only when a designated trusted referee/authority path says so under policy. | Any receipt named “success” |
| **Verification result** | Trusted verifier/check outcome (TCB referee plane). | Worker self-assessment |
| **Publication receipt** | Record around PR publication authorization surfaces. | Merge to Main; queue `ready_for_main` alone |
| **Worker success** | Untrusted claim or process exit from a worker/provider. | **`terminal_success`**; queue advance; capability grant |

**Mnemonic:** **capability ≠ authority**; **worker success ≠ terminal_success**; **receipt ≠ proof**; **job ≠ slice**; **attempt ≠ job**; **retry ≠ replay**; **lease expiry ≠ no SE**.

---

## Control-plane vs descriptive planes

| Term | Definition |
| --- | --- |
| **Context Engine (CE)** | Read-only evidence librarian / package assembly (CB-029). Non-TCB. Descriptive packaging for workers. |
| **System Model (SM)** | Descriptive repo inventory / impact (CB-028). Non-TCB. Must not silently become admission authority. |
| **Chief Builder** | Planning/priority policy surface; does not launch workers by itself. |
| **Supervisor** | Receipt-driven classification / circuit breaker; does not advance queue by narrative. |
| **TCB** | Minimal trusted path set registered in `trusted_policy` (referee / policy / admission core / related). Shared helpers ≠ TCB-safe to expand casually. |

---

## State inventories (authoritative names — do not rename)

### Queue PRIMARY (`queue_store.py`)

`idea`, `researching`, `designing`, `ready`, `scheduled`, `building`, `reviewing`, `staging`, `testing`, `ready_for_main`, `done`

### Queue SIDE

`blocked`, `changes_requested`, `paused`, `superseded`, `retired`, `cancelled`

### `EXECUTION_CAPABLE_STATES`

Every PRIMARY state from queue `ready` onward (inclusive). Product-plane signal that the slice is in an execution-capable **roadmap** region — **not** GPD `ready`.

### GP-D `JOB_STATES` (`gpd_job_state.py`)

`created`, `admitted`, `ready`, `leased`, `running`, `waiting`, `checkpointed`, `cancellation_requested`, `cancelled`, `stalled`, `timed_out`, `failed`, `execution_unknown`, `reconciling`, `retryable`, `terminal_success`, `terminal_failure`

---

## Phrases to avoid (and replacements)

| Avoid | Prefer |
| --- | --- |
| “the job is ready” (ambiguous) | “queue slice is ready” or “GPD job is ready” |
| “mark the slice terminal_success” | “record GPD terminal_success for job …” / “transition queue slice to done …” (separate acts) |
| “lease expired so no SE” | “lease expired → uncertain; reconcile SE explicitly” |
| “worker succeeded so we’re done” | “worker receipt observed; GPD/queue advance only via their rules” |
| “admitted means can merge Main” | Admission ≠ publication ≠ merge |

---

## Integrity

Docs-only. No production renames. No authority granted.
