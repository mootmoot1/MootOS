# CB-027B–F — Trusted Policy / TCB Enforcement Phase

Trusted Main base: `e10022c33ad24cffda7042e07eec1adfdca88c21` (after CB-027A /
PR #90). This phase turns the CB-027A TCB registry into an operational
decision boundary, sealed evidence receipts, and narrow candidate admission
wiring. **ZERO AUTHORITY** — no publication, queue, GitHub, merge, Main
advancement, or worker-output trust is granted. **DO NOT MERGE AUTOMATICALLY.**

## Purpose

Continuous Builder workers only propose changes. The system owns truth about
which repository-relative paths are Trusted Computing Base (TCB). This phase:

1. Evaluates bounded changed-path sets against `create_mootos_tcb_registry_v1()`
2. Seals immutable decision receipts (evidence, not authorization)
3. Admits authoritative inventories inside `verify_candidate_structure`
4. Proves adversarial bypasses fail closed
5. Integrates Cases A–H across real in-repo components

## Architecture

```text
worker-proposed / reconstructed changed paths
  -> evaluate_changed_paths_against_tcb()     [CB-027B]
       uses ONLY create_mootos_tcb_registry_v1()
  -> TrustedPolicyDecision (sealed, zero authority)
  -> create_trusted_policy_decision_receipt() [CB-027C]
  -> admit_changed_paths_against_tcb()        [CB-027D]
  -> verify_candidate_structure() maps non-ordinary
       admissions to structural failure codes
```

Law: **THE SYSTEM OWNS TRUTH. THE WORKER ONLY PROPOSES CHANGES.**

## Trust assumptions

| Claim | Status |
| --- | --- |
| Canonical registry factory is the sole classification source | **PROVEN** |
| Callers cannot supply an alternate registry | **PROVEN** |
| Decisions/receipts/admissions cannot claim authority flags | **PROVEN** |
| Structural verifier admits changed paths against TCB | **PROVEN** |
| Enforcement module itself listed in TCB registry | **DEFERRED** (see limitations) |
| Cryptographic signatures against compromised host code | **DEFERRED** (in-process tokens only) |
| Every CB admission path beyond verifier_core | **DEFERRED** |

## Flow

1. Artifact intake yields an authoritative inventory (CB-023).
2. Verifier core reconstructs changed paths from trusted base + admitted bytes.
3. TCB enforcement classifies the reconstructed path set.
4. Ordinary → structural pipeline continues (subject to existing contract rules).
5. `protected_core_review` → `tcb_protected_change_requires_review` (non-authorized review).
6. `human_only` / `trusted_system_only` → `tcb_protected_change_forbidden`.
7. Malformed / uncertain / identity mismatch / stale receipt → stop.

## Exact TCB path set (v1, unchanged from CB-027A)

Path count: **11**. Registry digest (`registry_sha256`):

`7ee7252f202f07fc23e05b52bcb328614adf16262e4f6e7df9b1ecc623347e15`

| Path | Component | Category | Policy |
| --- | --- | --- | --- |
| `backend/continuous_builder/adversarial_verifier.py` | cb_verifier_core | verifier | protected_core_review |
| `backend/continuous_builder/verifier_core.py` | cb_verifier_core | verifier | protected_core_review |
| `backend/continuous_builder/check_runner.py` | cb_check_runner | verifier | protected_core_review |
| `backend/continuous_builder/check_runtime.py` | cb_check_runner | verifier | protected_core_review |
| `backend/continuous_builder/sandbox_policy.py` | cb_sandbox_policy | sandbox | protected_core_review |
| `backend/continuous_builder/runtime_enforcement.py` | cb_runtime_enforcement | execution_policy | protected_core_review |
| `backend/continuous_builder/worker_artifact.py` | cb_artifact_intake | artifact_intake | protected_core_review |
| `backend/continuous_builder/worker_authorization.py` | cb_worker_authorization | worker_authorization | protected_core_review |
| `backend/continuous_builder/chief_builder.py` | cb_approval_authority | approval_authority | human_only |
| `scripts/capability_build/pr_publication_authorization.py` | cb_publication_authority | publication_authority | human_only |
| `backend/continuous_builder/trusted_policy.py` | cb_trusted_policy | trusted_policy | human_only |

## Decision states

| Outcome | Meaning |
| --- | --- |
| `ordinary_change` | No TCB hits; may continue existing pipeline |
| `protected_change_requires_review` | TCB hit with `protected_core_review` |
| `protected_change_forbidden` | TCB hit with `human_only` / `trusted_system_only` |
| `malformed_change` | Unsafe / non-canonical / duplicate / bound failure |
| `policy_uncertain` | Registry integrity / unsupported policy |

Mixed sets take the **worst** outcome (malformed > uncertain > forbidden > review > ordinary).

## Receipt structure (CB-027C)

`TrustedPolicyDecisionReceipt` binds: receipt/policy/registry versions,
`registry_sha256`, `decision_sha256`, outcome, `canonical_paths_sha256`,
TCB match count + digest, reason codes + digest, optional candidate /
worker-request digests, optional input identity, `receipt_sha256`.
All authority flags structurally false. Sealed construction only.

## Admission wiring (CB-027D)

`admit_changed_paths_against_tcb()` binds authoritative inventory to
decision + receipt identities. `verify_candidate_structure` calls it on
reconstructed changed paths and unions `tcb_*` failure codes into the
structural receipt. Worker-declared path overrides and stale/cross-candidate
receipts fail closed.

## Adversarial cases (CB-027E)

Covered: traversal, absolute, dot-segment hide, duplicates, case collision,
backslash separators, fake registry/component, forged digests/receipts,
stale/cross-candidate replay, inventory lie vs TCB, mixed downgrade,
self-mod trusted_policy, verifier/artifact/worker-auth/approval/publication
mods, unknown policy injection, malformed encoding, oversized set,
duplicate ownership at registry, authority flags true, omission cannot pass,
uncertainty ≠ pass. **No bypass became ordinary** in the suite.

## Integration proof (CB-027F Cases A–H)

| Case | Result |
| --- | --- |
| A ordinary safe | structural pass; ordinary decision |
| B protected verifier_core | structural fail + review code |
| C adversarial_verifier | structural fail + review code |
| D trusted_policy self-mod | structural fail + forbidden code |
| E malformed bypass | malformed; admission blocked |
| F replay / identity mismatch | stale / mismatch stop |
| G mixed (protected wins) | review wins over ordinary |
| H authority check | all six flags false on phase objects |

## Limitations

* `trusted_policy_enforcement.py` is **not** yet listed in the TCB registry
  (DEFERRED; should join `cb_trusted_policy` in a follow-up human-reviewed
  registry expansion).
* Only `verify_candidate_structure` is wired; supervisor/queue/publication
  surfaces remain unwired (DEFERRED by design for this phase).
* In-process construction tokens are integrity controls, not signatures.
* No network, Docker weakenings, DB migrations, or auto-merge were added.

## Deferred

* Expand TCB to include enforcement module + future policy files
* Wire remaining admission surfaces beyond verifier core
* Durable authenticated evidence storage
* Human review queue UX for `protected_change_requires_review`

## Authority

All remain **false** on decisions, receipts, admissions, and snapshots:

`publication_authorized`, `queue_transition_authorized`, `github_authorized`,
`merge_authorized`, `main_advancement_authorized`, `worker_output_trusted`

(`result_trusted` likewise false on CB-027A snapshots.)

## Out of scope

System Model, Context Engine, Task Decomposer, provider router, GPU, parallel
workers, credentials, DB migrations, auto GitHub ops, broad refactors,
unrelated UI, Main merge.
