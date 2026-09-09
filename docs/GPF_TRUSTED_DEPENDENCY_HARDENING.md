# GP-F trusted dependency hardening

Resume: 2898eefdded6586879163c81f3df028ff64c740f.

A trusted launch decision must not depend on worker-modifiable executable
code. The semantic kernel's closure contained seven modules that were inside
the trusted path but were not protected TCB paths. This slice closes that gap.
No launch authority is added, no worker or provider runs, and the meaning of
`TrustedLaunchEligibility` is unchanged.

## Dependency risk table

Closure of `gpf_launch_semantics`, 14 modules. "Alters verdict?" asks whether
changing that file's executable behaviour could turn a blocked candidate into
an eligible one, or corrupt the evidence a verdict is derived from.

| module | why imported | alters verdict? | action | reason |
| --- | --- | --- | --- | --- |
| `gpf_launch_semantics` | the referee itself | yes | already protected | `cb_launch_eligibility_semantics` |
| `gpf_launch_state_projection` | normalizes GP-D lifecycle facts | yes | already protected | `cb_launch_state_projection` |
| `gpf_launch_facts` | source identity/currentness tokens | yes | already protected | `cb_launch_facts_source` |
| `gpf_launch_candidate_binding` | authoritative assignment + all bounded source readers | yes | already protected | `cb_launch_assignment_authority` |
| `gpf_approval_authority` | Ed25519 verification and signed approval subject | yes | already protected | `cb_launch_approval_authority` |
| `gpc_trusted_admission_core` | policy-matrix identity in the source token | yes | already protected | `cb_capability_admission` |
| `trusted_policy` | live registry/snapshot identity for `admission_incompatible` | yes | already protected | `cb_trusted_policy` |
| `gpd_job_state` | `reduce_job_state`, `TRANSITIONS`, `TERMINAL_STATES` | **yes, directly** | **protect** | it *is* the lifecycle verdict: cancelled, execution_unknown, reconciling, stalled, timed_out, failed, terminal and active attempt all come from here |
| `gpd_job_events` | `create_job_event` recomputes `event_digest`; `JobEvent` type gates the reducer | **yes, directly** | **protect** | the digest recomputation *and* the comparison both live here, so a hostile copy accepts forged events and rewrites lifecycle at will |
| `gpd_job_header` | `create_durable_job_header`; supplies gates, scope, capabilities, admission and TCB digests | **yes, directly** | **protect** | subverts scope/capability interpretation, required gates and header/admission identity validation in one edit |
| `gpa_eval_schema` | `canonical_json`, `sha256_hex`, `require_*`, `AUTHORITY_FLAGS` for all three GP-D modules | **yes, directly** | **protect** | every digest check in the reconstruction path is built on these two functions; replacing `sha256_hex` collapses the entire integrity basis |
| `paths` | `canonicalize_repo_path` for `trusted_policy` registry construction and `require_repo_path` | **yes, indirectly but decisively** | **protect** | this function decides what a protected path *is*; a worker-editable copy can map its own target outside `protected_paths` and defeat the TCB gate itself, including the gate that protects everything above |
| `text_safety` | `utf8_length` byte bound used by `paths` | **yes, as part of canonicalization** | **protect** | neutering it lets oversized/unencodable paths through canonicalization; it is one trust unit with `paths` and is protected in the same component |
| `timestamps` | `parse_timestamp` inside `create_job_event` / `create_durable_job_header` | **no, not directly** | **protect** | honest classification: influence is validation *strictness* on header/event acceptance, not verdict flipping — `created_at` is inside the sealed digest either way, and neither approval expiry nor lease expiry uses it (both use their own stdlib parse). It is protected because it executes inside the trusted reconstruction path alongside the validators it is imported with, and it is 32 lines; the alternative is a dependency the reconstruction path calls but nobody owns |

Nothing was protected merely for being imported. Deliberately **not** protected:
the Python standard library, and any module outside this closure. The
`__init__.py` of the package contributes no executable behaviour to this path.

## Refactor considered and rejected

Option B for the GP-D modules would have been to stop importing them and
re-derive lifecycle inside the protected projection. That is exactly the
"duplicate the GP-D state machine to reduce path count" move this slice was
told not to make, and it is worse on the stated priority order: two state
machines that can silently disagree is a correctness and trust-integrity
regression bought for a smaller number. Protecting three real files is the
cleaner answer.

`paths`/`text_safety` could not be refactored away either: `trusted_policy`
and the already-protected `trusted_policy_enforcement` both depend on
`canonicalize_repo_path` to decide protected-path membership. That dependency
was already unprotected before this slice — a pre-existing hole in the gate's
own foundation, not one introduced by GP-F.

## TCB delta

Three components, seven paths, all `human_only`:

- `cb_durable_state_contract` / `execution_policy` /
  `gpd_lifecycle_reconstruction_contract` → `gpd_job_events.py`,
  `gpd_job_header.py`, `gpd_job_state.py`
- `cb_schema_digest_primitives` / `verifier` /
  `canonical_digest_and_record_validation` → `gpa_eval_schema.py`,
  `timestamps.py`
- `cb_path_canonicalization` / `trusted_policy` /
  `protected_path_canonicalization` → `paths.py`, `text_safety.py`

Cumulative from `2898eef`: seven paths, three components; **26 protected paths
/ 18 components**.
Registry digest: `21be7975fcfb9754031cbf0e741386ea5a8683648a7497b1a371164a37114d5d`.

Making these `human_only` means ordinary GP-D or utility edits now require
human review. That is the intended cost: these files are the basis of a launch
verdict, and the whole point is that a worker cannot change them.

## Side effect on an existing assertion

`test_22_no_timestamps_in_digests` scanned the System Model digest for the
substring `timestamp` to prove no wall-clock value is embedded. A protected
path is now literally named `timestamps.py`, so the scan collided with a
filename. The test now strips protected-path strings before scanning, which
preserves what it was actually asserting rather than deleting the check.

## What this does not do

Protection governs who may *change* these files, not who may invoke them.
Import-time execution by any module already inside the interpreter remains
outside this boundary; process/interpreter isolation is F10's job, not the
registry's. No authority flag changes, and `launch_authorized` remains
impossible to produce.
