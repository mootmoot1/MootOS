# CB-027A — trusted policy / TCB registry v1

Base: `b29bb81aded896a41b86504bc86ac127a9ea636a` (trusted Main after CB-026C /
PR #89 merge). Sync correction: protect
`backend/continuous_builder/adversarial_verifier.py` under existing
`cb_verifier_core` (category `verifier`).

## Boundary

`backend/continuous_builder/trusted_policy.py` adds an immutable,
content-addressed **Trusted Computing Base (TCB) path registry** for Continuous
Builder referee and authority surfaces. It classifies repository-relative paths
only. It does **not**:

* reject worker actions automatically
* grant publication, queue, GitHub, merge, or Main authority
* expose a worker-facing constructor that can mark arbitrary paths protected
* pull Docker, run workers, or migrate databases

The sole public registry factory is `create_mootos_tcb_registry_v1()`. Query
helpers always derive from that canonical registry. Snapshot receipts are
evidence only.

## Architecture

```text
create_mootos_tcb_registry_v1()
  -> TrustedComponent[] (sealed, exclusive path ownership)
  -> TrustedPolicyRegistry (canonical protected path set + registry_sha256)
create_trusted_policy_snapshot()
  -> TrustedPolicySnapshot (evidence; all authority flags false)
is_tcb_path(path) / classify_tcb_path(path)
  -> read-only classification from the canonical registry only
```

Construction follows existing CB seal patterns (`_canonical`, `_digest`, frozen
dataclasses, private construction tokens) from `verifier_core` / `check_runner`.

## Categories (bounded)

`verifier`, `sandbox`, `execution_policy`, `artifact_intake`,
`approval_authority`, `publication_authority`, `worker_authorization`,
`trusted_policy`

## Change policies (classification only)

`human_only`, `trusted_system_only`, `protected_core_review`

No mutation mechanism is provided in this slice.

## Protected paths (exact files, v1)

| Component | Category | Paths | Why |
| --- | --- | --- | --- |
| `cb_verifier_core` | verifier | `adversarial_verifier.py`, `verifier_core.py` | Structural / adversarial verifier referee |
| `cb_check_runner` | verifier | `check_runner.py`, `check_runtime.py` | Bounded behavioral check authority |
| `cb_sandbox_policy` | sandbox | `sandbox_policy.py` | Deny-by-default containment policy |
| `cb_runtime_enforcement` | execution_policy | `runtime_enforcement.py` | Runtime foundation / enforcement contracts |
| `cb_artifact_intake` | artifact_intake | `worker_artifact.py` | Quarantine intake boundary |
| `cb_worker_authorization` | worker_authorization | `worker_authorization.py` | Dispatch authorization evidence |
| `cb_approval_authority` | approval_authority | `chief_builder.py` | Blueprint approval evidence |
| `cb_publication_authority` | publication_authority | `scripts/capability_build/pr_publication_authorization.py` | Explicit PR publication authorization |
| `cb_trusted_policy` | trusted_policy | `trusted_policy.py` | Self-protection of this registry |

Paths are canonical, sorted, unique, non-overlapping, exact files (no globs,
no directory prefixes, no `.git` / `.env` / traversal / absolute paths).

## Digests

* `component_sha256` — SHA-256 of the component's canonical body
* `registry_sha256` — SHA-256 of the registry body (ordered components +
  protected paths + versions)
* `protected_paths_sha256` / `snapshot_sha256` — snapshot evidence digests

Ordering is deterministic: component IDs and paths are sorted. Reordering is
rejected before a digest can be accepted.

## Self-protection

The registry fails closed unless it includes
`backend/continuous_builder/trusted_policy.py` under category `trusted_policy`
with `human_only` change policy.

## Zero authority

`TrustedPolicySnapshot` keeps all of these structurally false:

`publication_authorized`, `queue_transition_authorized`, `github_authorized`,
`merge_authorized`, `main_advancement_authorized`, `result_trusted`,
`worker_output_trusted`

Passing classification never authorizes action. Query helpers return
classification only.

## Fail-closed validation

Rejects: unknown category/policy, empty components, duplicate IDs, overlapping
path ownership, malformed/non-canonical/glob/dot-segment/absolute/traversal
paths, forged digests, authority promotion on snapshots, tokenless construction.

## Next slice

TCB **enforcement wiring** (use the registry inside worker/candidate path
gates). Not implemented here — classification and registry identity only.

## Out of scope

Docker proofs, worker execution, queue/GitHub/merge automation, ADR-031 gate
replacement, broad protected-core expansion, CB-027B enforcement wiring.

## Sync note (post CB-026C)

After Main advanced to `b29bb81aded896a41b86504bc86ac127a9ea636a`, this slice
adds the CB-026C file `backend/continuous_builder/adversarial_verifier.py` to
the canonical protected set under `cb_verifier_core` / `verifier`. Path count
is 11; component count remains 9. Digests are recomputed by canonical
construction (`registry_sha256` =
`7ee7252f202f07fc23e05b52bcb328614adf16262e4f6e7df9b1ecc623347e15`). Adding the path grants classification only
— zero authority.

## Sync note (GP-C trusted admission)

Authorized GP-C follow-up adds exactly one protected path:
`backend/continuous_builder/gpc_trusted_admission_core.py` under new
component `cb_capability_admission` / category `capability_admission`
(`human_only`). Path count **13**; component count **10**. Current
`registry_sha256` =
`642c451728ba422ae4a4e229c02021ce79c4be8b9fc199996f27e8cd9873d692`.
