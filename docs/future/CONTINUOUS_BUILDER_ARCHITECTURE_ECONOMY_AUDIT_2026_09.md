# Continuous Builder — Architecture Economy Audit (2026-09)

**Audit type:** Formal ARCHITECTURE ECONOMY AUDIT (first formal pass)  
**Mode:** AUDIT-ONLY — no production code changes, no refactors, no TCB/schema/storage/state-machine edits, no migrations, no worker launches  
**Trusted Main (parent-verified):** `ba241118d5c9aa7a64df487275eb36a09bcc0826`  
**Worktree:** `/Users/freeman/Desktop/MootOS-ARCH-ECONOMY-AUDIT`  
**Branch:** `grok/continuous-builder-architecture-economy-audit`  
**Date (America/New_York):** 2026-09-06  

## 0. Mandate and non-goals

**Goal:** Identify justified vs accidental complexity. Prefer fewer accidental concepts, fewer duplicate non-security primitives, clearer boundaries, and lower worker context burden — **same or stronger security**. This is **not** a minimum-LOC exercise.

**Hard non-goals (obeyed):** Do not refactor, rewrite architecture, modify production code, merge, clean up code, change TCB/schemas/storage/state machines, migrate data, or launch workers. Do **not** propose putting untrusted helpers into the TCB merely to dedupe.

**Classification vocabulary for every duplication:**

| Code | Meaning |
| --- | --- |
| **1 ACCIDENTAL** | Same idea repeated without a trust or lifecycle reason |
| **2 INTENTIONAL TRUST-BOUNDARY** | Duplication preserves isolation / fails closed / keeps TCB small |
| **3 ACCEPTABLE LOCAL** | Thin local adapter or contract-local constant; leave |
| **4 ARCHITECTURAL DEBT** | Real cost, needs a decision or phased fix — not a drive-by edit |
| **5 FALSE POSITIVE / LEAVE ALONE** | Looks similar, different job; do not touch |

---

## 1. Methodology

1. Confirmed `origin/main == ba241118d5c9aa7a64df487275eb36a09bcc0826`.
2. Created clean worktree from that SHA (dirty primary `/Users/freeman/Desktop/MootOS` untouched; never `git clean`; never touched `data/mootos.db-*`, `job_created`, `scope_frozen`, `* 2.*`).
3. Measured `backend/continuous_builder/**/*.py` (production) and `tests/**` that import or name Continuous Builder.
4. Built CB-local import graph (fan-in/out, one cycle).
5. Inventories: digest/canonical helpers, authority flags, schema/version constants, sealed dataclasses, error classes, receipt/evidence types, state frozensets, storage backends, TCB registry paths/components, phase module LOC.
6. Read phase docs (GP-A/B/C/D), ADRs 037–043, and module headers for intentional-isolation comments (especially GP-C local helpers).
7. Bucketed findings A–E with Impact / Risk / Context savings / Security sensitivity / Timing scores for A/B/E items.
8. Deliverable is **this docs-only file** + docs-only PR. Production tree must remain byte-identical to base aside from this doc.

---

## 2. Metrics snapshot (repo measurements)

### 2.1 Production Continuous Builder

| Metric | Value |
| --- | --- |
| Modules (`backend/continuous_builder/*.py`) | **80** |
| Total lines | **32,941** |
| Non-empty lines | **29,939** |
| `@dataclass` decorators | **166** (≈**164** `frozen=True`) |
| Seal/create-style factories (`seal_*` / `_seal_*` / `create_*`) | **94** |
| `SCHEMA_VERSION =` decls | **14** |
| Broader `*_VERSION` constants | **73** |
| Digest/canonical/hash helper **defs** (name match) | **~135** (many local copies) |
| Modules with local `def _canonical(` | **25** |
| Error classes (`*Error`) | **~70** across ~68 modules |
| Receipt/Evidence/Decision/Record-style classes | **~45+** named types |
| Enum classes (`Enum` subclass) | **0** (states use frozensets / string machines) |

### 2.2 Tests

| Metric | Value |
| --- | --- |
| Test files importing / under CB | **93** (`test_continuous_builder*.py` = **92**) |
| Test total lines | **19,036** (non-empty **16,219**) |
| By phase prefix (file count / LOC) | GPA 8 / 1,695; GPB 8 / 1,450; GPC 8 / 1,420; GPD 5 / 786; legacy CB 63 / 13,578 |

### 2.3 Phase module counts (production)

| Phase prefix | Modules | LOC |
| --- | ---: | ---: |
| `gpa_*` | 8 | 3,039 |
| `gpb_*` | 8 | 3,229 |
| `gpc_*` | 8 | 3,611 |
| `gpd_*` | 11 | 2,358 |
| Other CB | 45 | 20,704 |

### 2.4 Largest 20 production modules

| Rank | Module | Lines | Role (one line) |
| ---: | --- | ---: | --- |
| 1 | `context_engine.py` | 3565 | Read-only evidence librarian / package assembly (CB-029) |
| 2 | `system_model.py` | 1905 | Descriptive repo inventory / components / impact (CB-028) |
| 3 | `gpc_trusted_admission_core.py` | 1592 | **TRUSTED** capability admission algorithm |
| 4 | `worker_runtime.py` | 1356 | Bounded Docker host adapter + execution receipts |
| 5 | `trusted_policy_enforcement.py` | 1159 | TCB path → operational decision / admission |
| 6 | `gpc_eval_corpus.py` | 908 | GP-C adversarial / eval corpus |
| 7 | `supervisor.py` | 848 | Receipt-driven supervision classify (no launch) |
| 8 | `runtime_enforcement.py` | 811 | Runtime enforcement contracts / readiness |
| 9 | `trust_chain_proof.py` | 738 | End-to-end trust-chain proof assembly |
| 10 | `worker_artifact.py` | 709 | Artifact intake quarantine (**TCB**) |
| 11 | `gpc_capability_vocabulary.py` | 599 | Untrusted capability request sealing |
| 12 | `verifier_core.py` | 593 | Structural verifier referee (**TCB**) |
| 13 | `sandbox_policy.py` | 592 | Deny-by-default sandbox policy (**TCB**) |
| 14 | `trusted_policy.py` | 576 | TCB registry (**TCB**) |
| 15 | `gpb_decomposer.py` | 553 | Task decomposer / execution plan |
| 16 | `gpa_baseline_evidence.py` | 529 | Historical PR observations |
| 17 | `gpa_eval_corpus.py` | 529 | GP-A eval corpus |
| 18 | `gpb_scope_rules.py` | 529 | Scope envelope rules |
| 19 | `gpb_eval_corpus.py` | 524 | GP-B eval corpus |
| 20 | `check_runner.py` | 512 | Trusted check runner (**TCB**) |

### 2.5 Dependency hotspots (CB-local imports)

**Highest fan-in (most imported):**

| Module | Fan-in |
| --- | ---: |
| `gpa_eval_schema` | 27 |
| `text_safety` | 24 |
| `paths` | 13 |
| `worker_runtime` | 9 |
| `timestamps` | 8 |
| `trusted_policy` | 8 |
| `worker_artifact` | 6 |
| `gpb_task_contract` | 5 |
| `gpc_trusted_admission_core` | 5 |
| `system_model` | 5 |

**Highest fan-out:** `trust_chain_proof` (8), `worker_planning` (8), `gpd_recovery` / `gpd_job_store` (7), `gpb_decomposer` (6).

**Cycle:** exactly one — `check_runtime` ↔ `check_runner` (TCB-internal; treat as debt to document, not to “fix” in this audit).

**Gravity:** Context Engine depends on `system_model` + `trusted_policy` + `paths`. System Model is descriptive but large and widely consulted. `gpa_eval_schema` is the post–GP-A shared primitive hub for Golden Plan modules (not for all pre-GPA CB modules).

---

## 3. TCB economy

### 3.1 Registry (from `create_mootos_tcb_registry_v1()`)

| Field | Measurement |
| --- | --- |
| Components | **10** |
| Protected paths | **13** (12 under `backend/continuous_builder/` + `scripts/capability_build/pr_publication_authorization.py`) |
| Categories | verifier, sandbox, execution_policy, artifact_intake, approval_authority, publication_authority, worker_authorization, trusted_policy, capability_admission |
| Approx LOC of TCB path set | **~7,892** |

**TCB modules (stems):** `adversarial_verifier`, `check_runner`, `check_runtime`, `chief_builder`, `gpc_trusted_admission_core`, `runtime_enforcement`, `sandbox_policy`, `trusted_policy`, `trusted_policy_enforcement`, `verifier_core`, `worker_artifact`, `worker_authorization` (+ external publication script).

### 3.2 Trusted → non-TCB imports (closure hazards to *understand*, not widen)

TCB modules import several non-registered helpers. Many are **benign shared utilities** (`paths`, `text_safety`). Others are **large behavioral surfaces** (`worker_runtime`, `sandbox_provider`, `sandbox_repository`, `docker_runtime_contract`, `repository_materialization`, `worker_action`, `worker_request`, `worker_provider`, `priority_policy`).

| Kind | Examples | Economy read |
| --- | --- | --- |
| Shared pure helpers | `paths`, `text_safety` | **3 ACCEPTABLE** — should stay small; do not promote to “authority” |
| Runtime/stack deps | `worker_runtime` ← check/verifier/artifact | **4 DEBT** — TCB *behaviorally* depends on a large non-TCB module; consolidating digests into `worker_runtime` would worsen this |
| Sandbox stack | `sandbox_policy` → provider/repository | **2/4** — policy is trusted; providers are supporting; do not merge into TCB for LOC |
| GP-C isolation | `gpc_trusted_admission_core` → **only** `trusted_policy` | **2 INTENTIONAL** — best-in-class closure hygiene |

**Wrongly trusted?** No strong false-positive of “untrusted authority living in TCB” found in this pass.  
**Wrongly untrusted authority?** GP-C thin wrappers are correctly untrusted re-exports. Older queue/lease SQLite is **not** in TCB (correct — product control plane, not referee). CE/SM are correctly descriptive / non-TCB.

**Do not** add CE, SM, `gpa_eval_schema`, queue, or GPD store into TCB to dedupe.

---

## 4. Duplicate primitives

| Primitive | Where | Class | Safe to consolidate? | Trust justify? | Verdict |
| --- | --- | --- | --- | --- | --- |
| Canonical JSON (`json.dumps` sort_keys/separators) | 25× `_canonical` / `canonical_json` in GPA schema + GPC core + nearly every sealed module | **1** outside Golden Plan; **2** inside GPC core; **3** inside other TCB modules | Non-TCB → prefer `gpa_eval_schema.canonical_json` **later**; **never** force TCB → GPA schema | GPC comment: “intentional duplication; keep trusted closure small” | **KEEP** GPC/TCB copies; **CONSOLIDATE** non-TCB/non-isolation copies **LATER** |
| SHA-256 hex | Parallel `_digest` / `sha256_hex` | same as above | same | same | same |
| Digest/ID validation (`require_sha256`, base SHA, id regex) | `gpa_eval_schema`, CE, SM, GPC core, many locals | **1/2** | Non-TCB toward GPA schema; CE/SM either import GPA schema (widens CE deps) or stay local | Avoid CE→GPA if it creates eval gravity on librarian | **REDESIGN LATER** for CE/SM; **KEEP** GPC |
| Authority flags (7 bools) | Defined in `trusted_policy.AUTHORITY_FLAGS`; re-bound in CE/SM; **re-declared** in `gpc_trusted_admission_core`, `check_runner`, `trusted_policy_enforcement` | **2** structural false on evidence; local tuple redeclares = **1/3** | Import tuple from `trusted_policy` where already depending on it | Flags are security-critical; duplication of *values* OK, drift of *names* is risk | **KEEP** pattern; **CONSOLIDATE** literal tuple copies that already import TCB |
| Bounded / UTF-8 text | `text_safety.utf8_length` (shared); CE `_utf8_len`; GPA `require_text`; GPC `_require_text`; several `_require_text_tuple` | **1** for CE private utf8 twin; **3** for domain require_* | CE should call `text_safety` (tiny) | No trust issue | **CONSOLIDATE** CE utf8 helper (tiny, safe) — still a *future* code change, not this PR |
| Path norm / scope | Central `paths.canonicalize_repo_path`; GPA `require_repo_path`; CE/SM `_canonical_repo_path`; TCB `_canonical_tcb_path` (stricter) | **2** TCB stricter; **3** GPA wrappers; **1/4** CE/SM parallel to GPA | Do not merge TCB path rules into GPA | Escape safety | **KEEP** `paths` + TCB stricter; CE/SM **REDESIGN LATER** |
| Sealed dataclasses + tokens | Ubiquitous frozen + `_token` / factory seal | **2/3** | Pattern is the security model | Yes | **LEAVE ALONE** |
| Receipts | ~30+ receipt types across boundaries | **2** per boundary; naming sprawl **4** | Do not merge receipt types | Evidence ≠ authority | **LEAVE** types; **glossary** for workers |
| Schema / policy versions | 73 version constants | **3** per contract | Single global version = footgun | Binding digests need local versions | **LEAVE ALONE** |
| Zero-authority helpers | `require_no_authority` in GPA schema; `_require_no_authority` in CE, SM, GPC | **2** GPC; **1/4** CE/SM vs GPA | Optional CE/SM import from GPA **if** dependency OK | Must stay fail-closed | **KEEP** GPC; CE/SM **LATER** |
| UNKNOWN sentinel | GPA `UNKNOWN`; used across GPA/B/C/D | **3** | Already shared | Observability ≠ fabricate zero | **LEAVE ALONE** |
| Budget / risk / capability / gates | GP-B ceilings, GP-C budgets/matrix/gates, CE budgets | **2** different layers | Do not collapse descriptive risk into admission | Security | **LEAVE ALONE** |

---

## 5. Duplicate concepts

| Concept pair | Status | Class | Notes |
| --- | --- | --- | --- |
| Builder **queue job / slice** vs GP-D **DurableJobHeader** | Parallel by design (GPD doc + ADR-041) | **2/4** | Product lifecycle (`idea→…→done` in `queue_store`) vs execution lifecycle (`created→…→terminal_*`). Overloading `builder_events` rejected intentionally. Debt = dual persistence until SQLite promotion. |
| Task / slice / node / FrozenTaskContract | Layered | **3** | Blueprint slices (queue) ≠ GP-B decomposition nodes ≠ contracts |
| Attempt (`builder_attempts` / `leases.py`) vs `gpd_attempt_ledger` | Parallel | **2/4** | Same word, different identity rules (slice FK vs job ledger) |
| Receipt vs evidence vs snapshot | Pattern family | **3** | Naming noise for workers; not the same type |
| Capability vs authority flags | Distinct | **2** | GP-C capabilities ≠ publication/merge authority |
| Execution state vs workflow/queue state | Distinct machines | **2** | See §6 |
| Queue store vs durable GPD JSONL | Dual stores | **4** | Authoritative-for-what must be explicit before GP-E binds dispatch |
| Escalation / human gates | Repeated fields across GP-B/C/D | **2** | Must survive recovery; duplication is binding, not waste |
| Request types (worker_request, capability request, context request, supplement) | Different planes | **3/5** | Do not merge |
| Checkpoint / progress | GPD checkpoint vs CE progress/supplement vs queue projection | **3** | Different semantics |
| Leases | `leases.py` (SQLite) vs `gpd_heartbeat_lease` (JSONL evidence) | **2/4** | GPD reuses *concepts*, not tables (documented) |
| Failure / retry vocab | `supervisor` classes ↔ `gpd_failure` (explicit overlap) | **3** | Intentional reuse note in `gpd_failure.py` |

---

## 6. State-machine overlap

| Machine | Location | States (summary) | Authority |
| --- | --- | --- | --- |
| Queue primary lifecycle | `queue_store.PRIMARY` | `idea → researching → designing → ready → scheduled → building → reviewing → staging → testing → ready_for_main → done` + side `blocked/paused/cancelled/changes_requested` | Durable SQLite events; execution-capable from `ready` onward |
| Candidate proposal | `queue_proposal.CANDIDATE_STATES` | `proposed/blocked/ready` | Pre-queue |
| GP-D derived job | `gpd_job_state.JOB_STATES` | 17 states incl. `admitted/leased/running/checkpointed/execution_unknown/reconciling/retryable/terminal_*` | Derived from JSONL events; worker success alone ≠ terminal_success |
| Supervisor classify | `supervisor` | Classification / circuit breaker — **does not** advance queue | Receipt-only |
| Runtime / sandbox lifecycle strings | `runtime_enforcement`, sandbox receipts | Foundation readiness strings | Contract evidence |
| PR publication | `scripts/.../pr_publication_authorization.py` (TCB) | Publication authorization | Human-gated publication authority |
| Verification outcomes | verifier / check_runner / trusted_policy_enforcement | Outcome frozensets | Referee |

**Overlap diagnosis:** Queue “ready/building/done” and GP-D “ready/running/terminal_success” **rhyme but are not the same machine**. Treating them as one would be a security/product error. The economy cost is **worker/docs confusion** and **dual persistence**, not redundant transition tables inside one module.

---

## 7. Wrapper sprawl

| Wrapper | Lines | Role | Class |
| --- | ---: | --- | --- |
| `gpc_policy_matrix.py` | 26 | Re-export core matrix | **2** — slice-shaped API, trusted core stays one file |
| `gpc_scope_risk_tcb.py` | 18 | Re-export scope/risk | **2** |
| `gpc_budget_constraints.py` | 18 | Re-export budget | **2** |
| `gpc_admission_decision.py` | ~119 | Untrusted adapter AdmissionInput → TrustedAdmissionFacts → core | **2** |
| `text_safety.py` | 19 | Shared utf8_length | **3** good |
| `timestamps.py` | 32 | Shared parse | **3** good |
| `blueprint_store.py` | 46 | Thin SQLite store | **3** |

**Verdict:** GP-C thin wrappers look like sprawl in module count but are **intentional trust-boundary packaging** (documented in GP-C doc). Deleting them to save files would either widen import of core into untrusted call sites awkwardly or encourage copying. **LEAVE ALONE** for economy-of-security.

---

## 8. Storage sprawl

| Store | Mechanism | Authoritative for | Cache / evidence? |
| --- | --- | --- | --- |
| `builder_*` SQLite tables (migrations) | SQLite | Blueprint / slice / queue events / leases / idempotency / artifacts metadata | Authoritative **product** control plane |
| `queue_store` / `queue_projection` / `readiness_bridge` | SQLite events | Queue transitions + dependency snapshots | Authoritative for queue eligibility |
| `leases.py` | SQLite | Attempt ownership for queue/dispatch era | Authoritative for those leases |
| `gpd_job_store.JobLedgerStore` | Filesystem JSONL + atomic `header.json` | GP-D job truth (header, events, attempts, leases, heartbeats, checkpoints, side effects, reconciliations) | Authoritative for **Golden Plan job execution** until SQLite promotion |
| Context / system model | Mostly ephemeral build + optional sqlite mentions | Descriptive snapshots | Evidence / descriptive — not launch authority |
| Receipts on disk / in proofs | Files / structs | Audit evidence | Non-authorizing |
| Logs | Various | Debug | Non-authoritative |

**Economy call:** Dual durable systems are **architectural debt with an intentional reason** (no migration in GP-D; vocabulary conflict). Before GP-E dispatch binds “the job,” publish a one-page **store authority map** (docs-only hardening). Do **not** merge stores in a drive-by refactor.

---

## 9. God modules / context burden

| Module | LOC | Responsibilities (compressed) | Split help? | Trust risk if split poorly |
| --- | ---: | --- | --- | --- |
| `context_engine.py` | 3565 | Budgets, scope, task request, excerpts, selection plan, interfaces, deps, package, receipt, supplements, adapters | **Yes, by CB-029 slice seams** (extract/selection/assemble/supplement) | Low trust (non-TCB) but high **regression** risk; workers lose one-file map |
| `system_model.py` | 1905 | Inventory, components, edges, ownership, uncertainty, build, impact queries | **Yes** (inventory vs graph vs impact) | Must not silently gain authority |
| `gpc_trusted_admission_core.py` | 1592 | Matrix, scope/risk/TCB, budget, facts, decision, receipt | **Resist split** — wrappers already exist; core unity is the TCB story | **High** if algorithm fragments across trust boundary |
| `worker_runtime.py` | 1356 | Docker CLI, materialization, enforcement evidence, execution receipt | Possible host-adapter vs receipt types | Medium — many TCB importers |
| `trusted_policy_enforcement.py` | 1159 | Match, decision, receipt, admission | Optional decision vs admission sections | High — TCB |

**Worker context cost (ordinary change):**

| Change type | Files typically needed (estimate) | Pain |
| --- | ---: | --- |
| Touch GP-A sealed field | 1 module + `gpa_eval_schema` + 1 test | Low–medium |
| Touch GP-B contract | contract + decomposer + maybe CE/SM + tests | Medium |
| Touch GP-C rule | **must** edit `gpc_trusted_admission_core` (+ thin wrapper only if API) + corpus/tests | Medium; core is large but single place |
| Touch GP-D state edge | `gpd_job_state` + events + maybe recovery/store + tests | Medium; **plus** confusion vs `queue_store` |
| Touch CE selection | Often **entire CE file** in prompt | **High** (3565 LOC prompt-size pain) |
| Touch verification chain | verifier + policy enforcement + artifact + maybe runtime | High fan-in |

Naming pain: `job`, `attempt`, `lease`, `ready`, `receipt`, `admission` appear on both sides of queue vs GP-D / policy vs capability.

---

## 10. Import / dependency complexity

- **Cycles:** 1 (`check_runtime` ↔ `check_runner`).
- **Trusted → untrusted hazards:** listed in §3.2; worst gravity is **TCB → `worker_runtime`**.
- **Fan-in hubs:** `gpa_eval_schema`, `text_safety`, `paths` (good hubs); `worker_runtime` (heavy hub).
- **CE/SM gravity:** SM feeds CE, GP-B decomposer/receipts, GPA baseline — descriptive hub. Do not make SM authoritative for admission (GP-C already treats SM boundary carefully).

---

## 11. Phase-by-phase sprawl

| Phase | What was added | Economy pattern |
| --- | --- | --- |
| Pre-GPA CB | Queue, leases, worker stack, verifier, TCB, CE, SM | Each sealed module copied `_canonical/_digest` |
| GP-A | Introduced `gpa_eval_schema` shared hub | **Good** — subsequent GP-* largely reuse it |
| GP-B | Contracts/nodes/receipts/scope still seal-locally but import GPA schema | Mostly aligned |
| GP-C | Trusted core **re-localizes** digests; thin wrappers; untrusted vocabulary | **Intentional isolation** (do not destroy for LOC) |
| GP-D | New JSONL ledger + state machine beside SQLite queue; reuses GPA schema + supervisor failure vocab | Parallel concept cost accepted |

**Lesson:** Accidental sprawl is concentrated in **pre-GPA sealed modules** still carrying private digest stacks, and in **dual job systems**. Not in GP-C wrappers.

---

## 12. Test economy

- **~19k** test LOC vs **~33k** prod LOC — healthy ratio for a security-sensitive control plane.
- Legacy CB tests dominate (63 files / ~13.5k LOC); Golden Plan phases are smaller but dense.
- Duplication: adversarial corpora per phase (GPA/B/C/D) are **intentional** evaluation surfaces (**2/3**), not accidental clones of unit tests.
- Pain: changing a shared authority flag or digest helper can require wide test updates — another reason **not** to casually merge helpers across the TCB boundary.

---

## 13. Bucketed findings

### A — SAFE TARGETED HARDENING (before GP-E)

Docs / inventory / glossary only in the immediate window; tiny non-TCB helper alignments only if a **separate** approved hardening PR is filed later. **This audit PR does not implement them.**

| ID | Item | Impact | Risk | Context savings | Security sensitivity | Timing |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| A1 | Publish **Store Authority Map** (queue SQLite vs GPD JSONL vs receipts) | High | Low | High | Low | **NOW** |
| A2 | Publish **Concept Glossary** (job/attempt/lease/ready/admission/receipt) | High | Low | High | Low | **NOW** |
| A3 | Inventory table of `_canonical/_digest` copies: TCB/GPC keep vs non-TCB migrate-to-`gpa_eval_schema` | Med | Low | Med | Med | **NOW** (docs) / code **AFTER GP-E** |
| A4 | Document TCB import closure + `worker_runtime` gravity | Med | Low | Med | High (awareness) | **NOW** |
| A5 | Document `check_runtime`↔`check_runner` cycle as known | Low | Low | Low | Low | **NOW** |
| A6 | Prefer `text_safety.utf8_length` over CE `_utf8_len` (future micro-PR) | Low | Low | Low | Low | **AFTER GP-E** |

### B — ARCHITECTURE DECISION REQUIRED

| ID | Item | Impact | Risk | Context savings | Security sensitivity | Timing |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| B1 | Confirm GP-E dispatch binds **GPD ledger** as execution truth; queue remains product lifecycle (ADR amendment) | High | Med | High | High | **NOW** (decision), implement with GP-E |
| B2 | Future SQLite promotion of `gpd_*` vs long-lived JSONL | High | High | Med | High | **AFTER GP-E** / human migration window |
| B3 | Whether to split CE / SM and along which seams | Med | High | High if done well | Med | **AFTER GP-F** / LATER |
| B4 | Whether TCB should eventually include a minimal digest primitive module (not GPA eval schema) | Med | High | Med | **Very high** | **LATER** — default no |

### C — DEFER

- Full non-TCB digest consolidation code pass.
- CE/SM structural split.
- Unifying leases.py with gpd_heartbeat_lease tables.
- Removing GP-C thin wrappers.
- Merging receipt type hierarchies.
- Breaking TCB→`worker_runtime` dependency (large redesign).

### D — INTENTIONAL / LEAVE ALONE

- GP-C local canonical/digest helpers in `gpc_trusted_admission_core`.
- GP-C thin re-export modules.
- Seven authority flags forced false on evidence records.
- Sealed dataclass + factory token pattern.
- Per-contract `*_VERSION` constants.
- UNKNOWN sentinel and provenance codes.
- Descriptive risk (GPA/GPB) ≠ admission (GPC).
- Parallel queue lifecycle vs GPD execution lifecycle **as a concept split**.
- `gpd_failure` overlap with supervisor vocabulary.
- `paths.canonicalize_repo_path` as the single path algebra.

### E — DELETE / RETIRE CANDIDATE

| ID | Item | Impact | Risk | Context savings | Security sensitivity | Timing |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| E1 | Retire **duplicate mental model** that GPD jobs “are” builder slices (docs-only retirement) | Med | Low | Med | Low | **NOW** |
| E2 | Eventually retire JSONL store **after** SQLite promotion (not now) | High | High | Med | High | **LATER** |
| E3 | No production module deletion recommended in this audit | — | — | — | — | — |

**No safe E-item deletes production code in this window.**

---

## 14. Top 10 economy opportunities (ranked)

| Rank | Opportunity | Bucket | Risk | Context savings |
| ---: | --- | --- | --- | --- |
| 1 | Store authority map + glossary (docs) | A | Low | **Very high** |
| 2 | ADR confirmation: GPD = execution truth for GP-E; queue = product lifecycle | B | Med | **Very high** |
| 3 | Non-TCB digest helper consolidation plan → `gpa_eval_schema` | A/C | Med | High |
| 4 | CE split by CB-029 seams (extract / plan / assemble / supplement) | B/C | High | High |
| 5 | Document TCB↔`worker_runtime` gravity; avoid adding more TCB importers | A | Low | Med |
| 6 | Align authority-flag tuple imports (stop local re-declares where TCB already imported) | A/C | Low–Med | Low–Med |
| 7 | SM split inventory vs impact query API | B/C | Med–High | Med |
| 8 | Keep GPC core monolithic; resist “save LOC” splits | D | — | Protects security economy |
| 9 | SQLite promotion plan for GPD (retire dual persist) | B/E | High | Med–High long-term |
| 10 | CE use shared `text_safety` utf8 helper | A | Low | Low |

---

## 15. Recommended targeted hardening scope (exact)

**In-scope for a hardening PR series (still not this audit PR’s code):**

1. Docs: store authority map + concept glossary + TCB closure note (can land as follow-ons under `docs/future/`).
2. Optional ADR-044 (or amend ADR-041): dual lifecycle explicit for GP-E.
3. Later code (non-TCB only): replace private `_canonical/_digest` in modules that **already** depend on `gpa_eval_schema` or have no isolation comment; **exclude** all TCB paths and `gpc_trusted_admission_core`.
4. Later micro: CE `_utf8_len` → `text_safety.utf8_length`.

**Explicitly OUT of scope / NOT to refactor now:**

- `gpc_trusted_admission_core` helper dedupe into `gpa_eval_schema` or shared TCB digest module.
- Merging `queue_store` with `gpd_job_store`.
- Merging `leases.py` with `gpd_heartbeat_lease.py`.
- Splitting CE/SM in the same PR as GP-E.
- Expanding TCB path set for convenience.
- Changing state machines, schemas, authority flags semantics, or migrations.
- Deleting GP-C wrappers.
- Any production behavior change “while we’re here.”

---

## 16. Expected benefit before GP-E

If A1–A5 docs land before GP-E coding:

- Workers stop treating queue `ready` as GPD `ready`.
- GP-E authors bind dispatch to the **correct** durable truth (GPD header/events/leases).
- Fewer accidental TCB widen proposals during GP-E.
- Clear list of which digest copies are sacred vs migratable.

If skipped: GP-E likely re-encodes queue/GPD confusion into runtime authorization — expensive to unwind.

---

## 17. Should GP-E proceed immediately?

**Not immediately into a large dual-store binding.**  
**Yes, proceed after short targeted hardening (docs + ADR decision B1).**  
Do **not** wait for CE/SM splits or digest consolidation code.

GP-D handoff already states GP-E can consume sealed headers, events, derived state, attempts, leases/stalls, checkpoints, SE identity + reconciliation — **without** treating them as launch permission until dispatch authorization exists. That is the right spine.

---

## 18. Final recommendation

### **PROCEED TO TARGETED HARDENING**

Then proceed to GP-E.  
**Do not** PROCEED DIRECTLY TO GP-E without A1/A2/B1 clarity.  
**Do not** HOLD the entire program for CE/SM redesign (B3 is later).

---

## 19. Audit integrity

- Production code changed in this PR: **NONE** (docs-only).
- Dirty primary tree: **not modified**.
- No `git clean`, no DB/job artifact touch, no merge, no workers launched.

---

## Appendix A — TCB protected path list (as of base SHA)

1. `backend/continuous_builder/worker_artifact.py`  
2. `backend/continuous_builder/gpc_trusted_admission_core.py`  
3. `backend/continuous_builder/chief_builder.py`  
4. `backend/continuous_builder/check_runner.py`  
5. `backend/continuous_builder/check_runtime.py`  
6. `backend/continuous_builder/runtime_enforcement.py`  
7. `backend/continuous_builder/sandbox_policy.py`  
8. `backend/continuous_builder/trusted_policy.py`  
9. `backend/continuous_builder/trusted_policy_enforcement.py`  
10. `scripts/capability_build/pr_publication_authorization.py`  
11. `backend/continuous_builder/adversarial_verifier.py`  
12. `backend/continuous_builder/verifier_core.py`  
13. `backend/continuous_builder/worker_authorization.py`  

## Appendix B — Queue PRIMARY vs GP-D JOB_STATES

**Queue PRIMARY:** `idea, researching, designing, ready, scheduled, building, reviewing, staging, testing, ready_for_main, done`  

**GP-D JOB_STATES:** `created, admitted, ready, leased, running, waiting, checkpointed, cancellation_requested, cancelled, stalled, timed_out, failed, execution_unknown, reconciling, retryable, terminal_success, terminal_failure`  

Shared token `ready` is a **homonym**.
