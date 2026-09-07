# Continuous Builder — TCB Dependency Closure Note

**Status:** Targeted hardening (docs-only) following Architecture Economy Audit 2026-09  
**Parent audit:** `docs/future/CONTINUOUS_BUILDER_ARCHITECTURE_ECONOMY_AUDIT_2026_09.md`  
**Base Main (trusted):** `ba241118d5c9aa7a64df487275eb36a09bcc0826`  
**Date (America/New_York):** 2026-09-06  

**Non-goals:** Do not expand TCB paths/components; do not import GPA/GPB/CE/SM helpers into TCB to dedupe; do not break the `check_runtime`↔`check_runner` cycle in code; do not split CE/SM for LOC before GP-E; no production changes.

---

## 1. Registry facts (verified)

From `trusted_policy.create_mootos_tcb_registry_v1()` at base SHA:

| Field | Value |
| --- | --- |
| Protected paths | **13** |
| Components | **10** |
| Approx LOC of TCB path set | ~7,892 |

TCB stems include: `adversarial_verifier`, `check_runner`, `check_runtime`, `chief_builder`, `gpc_trusted_admission_core`, `runtime_enforcement`, `sandbox_policy`, `trusted_policy`, `trusted_policy_enforcement`, `verifier_core`, `worker_artifact`, `worker_authorization`, plus `scripts/capability_build/pr_publication_authorization.py`.

---

## 2. GP-C trusted core — narrow closure

`gpc_trusted_admission_core.py` is the **only** trusted GP-C surface.

**Direct imports:** `trusted_policy` query APIs / version constants only (plus stdlib).

**Transitive (via `trusted_policy` → `paths` → `text_safety`):** path canonicalization and UTF-8 length helpers. This is the intentional narrow closure documented in the module header.

**Forbidden (direct or transitive) into the trusted core:** `gpb_*`, `system_model`, `context_engine`, `gpa_architecture_baseline`, `gpc_eval_corpus`, untrusted GP-C assemblers, and **`gpa_eval_schema`** (intentionally avoided so the core does not pull eval-schema gravity). Local `_canonical` / digest / authority-flag helpers are **intentional duplication** to keep the trusted closure small.

### Closure rules for future authors

1. **Do not** import GPA / GPB / CE / SM helpers into TCB modules merely to dedupe LOC.
2. **Trusted expansion** (adding paths/components to the registry, or widening what trusted cores import) is a **security design change**, not a cleanup PR.
3. **Shared ≠ TCB-safe.** A widely imported helper (`paths`, `text_safety`, `gpa_eval_schema`, `worker_runtime`) is not automatically eligible for TCB membership or for trusted-core import.
4. **System owns truth.** Workers, providers, CE packages, and receipts do not redefine TCB membership or admission outcomes.

---

## 3. `worker_runtime` gravity warning

Several TCB modules import `worker_runtime` (large non-TCB host/Docker adapter + execution receipts). Audit classification: **architectural debt** to *understand*, not to “fix” by stuffing digests into `worker_runtime` or by promoting `worker_runtime` into the TCB.

**Do not:**

- Add more TCB importers of `worker_runtime` casually during GP-E.
- Consolidate canonical/digest helpers *into* `worker_runtime` to “share” them with TCB.
- Register `worker_runtime` as a TCB path for convenience.

Breaking the TCB→`worker_runtime` edge is a **large redesign** (deferred). Awareness is the hardening deliverable now.

---

## 4. Digest / helper economy inventory (docs only — no consolidation)

Disposition codes for this table:

| Code | Meaning |
| --- | --- |
| **REMAIN LOCAL** | Keep private copy (TCB/GPC isolation or domain-local) |
| **SAFE FUTURE NON-TCB CONSOLIDATION** | Later may migrate toward `gpa_eval_schema` / `text_safety` / `trusted_policy` imports — **not now**, not in GP-E critical path |
| **LEAVE ALONE** | Pattern is intentional; do not “economy” it |

| Primitive / helper family | Where (examples) | Disposition | Notes |
| --- | --- | --- | --- |
| Local `_canonical` / digest in **`gpc_trusted_admission_core`** | GP-C trusted core | **REMAIN LOCAL** | Intentional; keeps closure free of `gpa_eval_schema` |
| Local digest helpers in **other TCB** modules (`trusted_policy`, `verifier_core`, `sandbox_policy`, `worker_artifact`, `worker_authorization`, `runtime_enforcement`, …) | TCB path set | **REMAIN LOCAL** | Do not force TCB → GPA schema |
| `gpa_eval_schema.canonical_json` / `sha256_hex` | Golden Plan shared hub | **LEAVE ALONE** (hub) | Preferred target for *non-TCB* later consolidation |
| Pre-GPA / non-isolation sealed modules with private `_canonical`/`_digest` (e.g. many `worker_*`, sandbox stack, CE/SM parallels) | Non-TCB | **SAFE FUTURE NON-TCB CONSOLIDATION** | After GP-E; exclude isolation comments / TCB |
| Authority flag **tuple redeclares** in modules that already import `trusted_policy` | e.g. some TCB/enforcement | **SAFE FUTURE NON-TCB CONSOLIDATION** (import the tuple) | Values duplication OK; name drift is risk |
| Authority flags structurally false on evidence | CE/SM/GPA evidence | **LEAVE ALONE** | Security pattern |
| CE `_utf8_len` vs `text_safety.utf8_length` | `context_engine` | **SAFE FUTURE NON-TCB CONSOLIDATION** | Tiny; still future micro-PR |
| CE/SM `_canonical_repo_path` vs `paths` / GPA | CE/SM | **SAFE FUTURE NON-TCB CONSOLIDATION** / redesign later | Do not merge TCB stricter path rules into GPA |
| TCB `_canonical_tcb_path` (stricter) | `trusted_policy` | **REMAIN LOCAL** | Escape safety |
| Sealed dataclass + factory token pattern | Ubiquitous | **LEAVE ALONE** | Security model |
| Per-contract `*_VERSION` constants | Many modules | **LEAVE ALONE** | Global version = footgun |
| Receipt type proliferation | Many boundaries | **LEAVE ALONE** (types); glossary for naming | Evidence ≠ authority |
| GP-C thin re-export wrappers | `gpc_policy_matrix`, etc. | **LEAVE ALONE** | Slice-shaped API; core stays one file |
| `require_no_authority` locals in GPC | GPC core | **REMAIN LOCAL** | Fail-closed isolation |
| UNKNOWN sentinel in GPA schema | Shared across GP-* | **LEAVE ALONE** | Already shared appropriately |
| Budget/risk/capability matrices vs CE budgets | GP-B/C vs CE | **LEAVE ALONE** | Different layers |

**Do not implement consolidation in this hardening pass.**

---

## 5. `check_runtime` ↔ `check_runner` import cycle

**Fact:** Exactly one production import cycle in Continuous Builder: `check_runtime` ↔ `check_runner` (both TCB).

**Likely reason:** Split between check **orchestration/policy surface** (`check_runner`) and check **process execution** (`check_runtime`), with a lazy/local import from runner into runtime execution (`execute_checks`) while runtime imports runner types/constants at module level.

| Aspect | Assessment |
| --- | --- |
| Benign vs debt | **Benign enough to ship**; still **documented debt** |
| Risk if “fixed” hastily | High — both modules are TCB; cycle-breaking refactors easily change referee behavior |
| Default disposition | **DOCUMENT AND DEFER** |
| Action now | None in code — do **not** break the cycle in a cleanup PR |

---

## 6. CE / SM disposition

| Module | LOC (audit) | Role | Disposition before GP-E |
| --- | --- | --- | --- |
| `context_engine.py` | ~3565 | Read-only evidence librarian / package assembly | **Known large**; split *may* help worker context later along CB-029 seams |
| `system_model.py` | ~1905 | Descriptive inventory / impact | **Known large**; inventory vs impact seams possible later |

**Rules:**

1. **No split before GP-E for LOC reasons.**
2. Any future split must **preserve determinism and eval** (same digests, same package semantics, same uncertainty handling).
3. CE/SM must **not** be imported into TCB/GPC trusted core to dedupe.
4. CE/SM must **not** gain admission/execution/merge authority by structural split accidents.

---

## 7. Integrity

Docs-only. TCB registry unchanged. `trusted_policy` unchanged. No migrations.
