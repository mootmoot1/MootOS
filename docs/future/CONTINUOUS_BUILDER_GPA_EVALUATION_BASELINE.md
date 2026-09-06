# GP-A — Architecture Baseline & Evaluation Corpus

Trusted Main base: `d799c23169332135773e377443779ee9f9544c04` (PR #93,
`grok/continuous-builder-cb029-context-engine-v1` — CB-029 Context Engine
v1 merged). This phase is measurement/evaluation infrastructure only.
**ZERO AUTHORITY** — nothing here executes a coding provider, routes
work, decomposes tasks, or changes trusted/production behavior. **DO NOT
MERGE AUTOMATICALLY.**

## Purpose

Before GP-B (Task Decomposer) can exist, MootOS needs a way to answer,
for any future benchmark run: *what exact architecture produced this
result, on what task, measured how?* GP-A freezes that measurement
foundation: an architecture baseline manifest, a task taxonomy, a frozen
eval case contract, a provider-neutral evidence schema, a 16-case corpus,
a deterministic offline harness, and real (not fabricated) baseline
evidence reconstructed from this repository's own git history.

THE SYSTEM OWNS TRUTH. THE WORKER ONLY PROPOSES CHANGES. Every sealed
record in this phase enforces that literally: a
`WorkerResultSubmission` is a plain, unsealed, mutable dataclass: the
system's own sealed, digest-bound records (`EvalCase`,
`EvidenceRecord`, `ArchitectureBaselineManifest`) never simply copy a
worker's claim.

## Architecture

```text
ArchitectureBaselineManifest (GP-A1)
  binds: base_sha, System Model (CB-028) digest + inventory,
         Trusted Policy (CB-027A) TCB registry digest, Context Engine
         (CB-029) version + source digest, GP-A schema suite version

TaskTaxonomy (GP-A2) -- 12 descriptive classes, no capability

EvalCase (GP-A3) -- frozen, two-sided (worker-visible / evaluator-only)
  -> EvalCorpus (GP-A5) -- 16 cases, all 12 classes, bound to base_sha

EvidenceRecord (GP-A4) -- provider-neutral, UNKNOWN-safe, provenance-typed

evaluate_worker_submission() (GP-A6)
  EvalCase + ArchitectureBaselineManifest + WorkerResultSubmission
  -> independently re-derived EvidenceRecord (never trusts the claim)

HistoricalPRObservation (GP-A7) -- reconstructed from real git history
```

## Module inventory

| Module | Lines | Slice |
| --- | ---: | --- |
| `gpa_eval_schema.py` | 215 | shared (canonical JSON/SHA-256/UNKNOWN/provenance primitives) |
| `gpa_architecture_baseline.py` | 272 | GP-A1 |
| `gpa_task_taxonomy.py` | 441 | GP-A2 |
| `gpa_eval_case.py` | 437 | GP-A3 |
| `gpa_evidence_record.py` | 385 | GP-A4 |
| `gpa_eval_corpus.py` | 529 | GP-A5 |
| `gpa_eval_harness.py` | 239 | GP-A6 |
| `gpa_baseline_evidence.py` | 449 | GP-A7 |

Every module follows the existing `trusted_policy.py` /
`system_model.py` / `context_engine.py` idiom: a frozen dataclass sealed
via a private construction token, `__post_init__` re-derives and checks
its own SHA-256 digest, every authority flag is structurally `False`.
Path canonicalization is re-exported from `paths.py`, never
reimplemented; the TCB registry digest and System Model inventory are
always read live from `trusted_policy.py`/`system_model.py`, never
duplicated into a competing list.

## Trust review (TCB)

None of `gpa_*.py` is added to `create_mootos_tcb_registry_v1()`. The TCB
registry is unchanged by this phase: **12 protected paths, 9 components,
digest unchanged** (verified: `create_architecture_baseline_manifest`'s
own `tcb_registry_sha256`/`tcb_protected_path_count`/`tcb_component_count`
fields, live-checked against `trusted_policy.create_trusted_policy_
snapshot()` in the GP-A1 test suite, match before and after this phase).

GP-A is **descriptive/observational only**:

- `architecture_baseline_is_descriptive_only()` → `True`
- `task_taxonomy_is_descriptive_only()` → `True`
- `eval_case_is_descriptive_only()` → `True`
- `evidence_record_is_observational_only()` → `True`
- `eval_corpus_is_descriptive_only()` → `True`
- `eval_harness_is_observational_only()` → `True`
- `baseline_evidence_is_observational_only()` → `True`

If a future change would let any GP-A record alone authorize execution,
scope, TCB, or policy: **HOLD** — that would need to go through
`create_mootos_tcb_registry_v1()` and a real trust review, not a
performance record.

## Status legend

| Claim | Status |
| --- | --- |
| Architecture baseline manifest derives from live System Model + TCB registry, no competing inventory | **PROVEN** |
| 12-class task taxonomy, descriptive only | **PROVEN** |
| Eval case worker/evaluator views structurally separated; leakage checker recurses into nesting | **PROVEN** |
| Evidence schema distinguishes UNKNOWN from fabricated zero/False, requires provenance per known field | **PROVEN** |
| 16-case corpus spans all 12 classes; 3 fixture-backed cases independently pytest-verifiable | **PROVEN** |
| Harness overrides a false worker success claim with independent verification | **PROVEN** |
| Harness never writes an overlay path outside a case's `allowed_scope`, even to a temp copy | **PROVEN** |
| Real historical evidence reconstructed from git (files/additions/deletions/commits; provider heuristic) | **PROVEN** |
| Token/cost/duration/model-identity baseline data for Claude/Codex/Grok | **UNAVAILABLE — see below** |
| Provider execution / routing / task decomposition | **OUT OF SCOPE — deferred to GP-B+** |

## Closure answers

**1. What exact Main SHA was evaluated?**
`d799c23169332135773e377443779ee9f9544c04` (PR #93, CB-029 Context
Engine v1). Re-verified from `origin/main` at the start of this phase
after CB-029 was confirmed merged; GP-A was **not** built on the earlier
CB-028 SHA (`ccd6bbe9e6a20939d2b7978286a5a618fa9c06cf`) that CB-029 had not
yet reached when this phase was first requested.

**2. What architecture baseline digest was produced?**
`create_architecture_baseline_manifest(repo_root, base_sha=<above>)`
seals a `manifest_sha256` deterministically derived from: System Model
digest (`system_model_sha256`), its root fingerprint, the live TCB
registry digest/protected-path-count/component-count, the Context Engine
`ENGINE_VERSION` string plus a SHA-256 of `context_engine.py`'s source
bytes, the Continuous Builder component inventory (component IDs + file
count), and the GP-A schema suite version. Digest is exact-input
reproducible (see `reproduction_inputs`) and stable across repeated calls
against the same tree state (proven in
`test_manifest_is_deterministic_for_same_base_sha`).

**3. What task classes exist?**
12: `narrow_bug_fix`, `bounded_feature_addition`, `test_addition`,
`behavior_preserving_refactor`, `docs_spec_sync`, `multi_file_feature`,
`security_sensitive_change`, `tcb_adjacent_change`,
`migration_schema_change`, `dependency_api_boundary_change`,
`context_heavy_navigation_task`, `verifier_policy_sensitive_task`.
Each carries descriptive-only scope/dependency/context/verification/
reversibility/risk fields and an `autonomy_experiment_suitable` flag —
none of which grant capability.

**4. How many eval cases exist by class?**
16 total. `narrow_bug_fix`: 2, `bounded_feature_addition`: 2,
`test_addition`: 2, `docs_spec_sync`: 2, and one case each for the
remaining 8 classes.

**5. Are eval cases deterministic/replayable?**
Yes. `create_gpa_eval_corpus_v1()` is a pure function of the frozen
`_case_specs()` table (no I/O, no randomness); every case's
`case_sha256` is stable across repeated construction (proven in
`test_corpus_is_deterministic`). The 3 fixture-backed cases
(`nb_001`/`bf_001`/`refactor_001`) are additionally replayable end to
end: their synthetic "before" fixtures are checked-in, disposable, and
independently `pytest`-verifiable via a real subprocess run against a
temp copy — never the real repository tree.

**6. Can evaluator-only data leak into worker-visible context?**
`to_worker_visible_dict()` has no parameter or code path that can
include `evaluator_view` — it is built by hand from four scalar fields
plus `worker_view.to_dict()`. `verify_no_evaluator_leakage()`
additionally recurses into nested dict/list structures checking for any
of `EVALUATOR_ONLY_KEYS`. Tested for all 16 real corpus cases
(`test_no_case_leaks_evaluator_data_in_worker_view`) plus a synthetic
nested-leak case. One acknowledged **limitation**: for the 3
fixture-backed cases, the evaluator-only `acceptance.py` file physically
exists on disk next to the worker-visible source file (git needs it
tracked to be replayable) — a real future worker-facing adapter must
itself exclude such evaluator-only paths from whatever it shows a
worker; this phase does not wire up that adapter.

**7. What performance fields can currently be measured?**
Directly, via the harness against the repo/fixtures: `files_changed`,
`scope_violation`, `policy_violation`, `outcome_state` (of the harness's
own evaluation step), and — only for the 3 fixture-backed cases —
`verifier_result` and `first_pass_success` (via a real `pytest`
subprocess against a disposable temp copy). Via GP-A7, from git history:
`files_changed`/`additions`/`deletions`/`commits_on_branch` for any past
merge, plus a `provider_label` heuristic from branch-naming convention.

**8/9/10. Which fields remain UNKNOWN for Claude / Codex / Grok?**
Every efficiency field for all three: `wall_clock_seconds`,
`model_time_seconds`, `input_tokens`, `output_tokens`, `cached_tokens`,
`cost_usd_cents`, `context_bytes_supplied`, `supplement_request_count`,
`supplement_bytes`. Also `repair_attempts`,
`success_after_repair`/`first_pass_success` for any *historical* PR
(GP-A7 has no repair-loop signal from git), and `human_acceptance`/
`human_review_outcome`/`human_review_reason` for any run not actually
human-reviewed. None of these were network-fetched or guessed to fill
this gap — they are recorded as `"unknown"`, never a fabricated zero.

**11. What actual baseline observations were captured?**
`create_baseline_evidence_snapshot(repo_root, limit=25)` reconstructs 25
real `HistoricalPRObservation`s from this repository's own merge
history — **when run against a full (non-shallow) local clone**.
Concretely verified that way: PR #93 (CB-029) reconstructs as branch
`grok/continuous-builder-cb029-context-engine-v1`, `provider_label`
`"grok"`, `+5646/-0` across 11 files, 9 commits. Across the last 25
merges the real, mixed distribution recovered was `codex: 15, grok: 4,
chatgpt: 3, unknown: 2, claude: 1` (branch-prefix heuristic; 2 merges'
branch names didn't match any of the 4 known prefixes and were correctly
left `"unknown"` rather than guessed).

This local, full-history reconstruction is **not** universally available
— it requires a full clone. CI checks out this repository with
`fetch-depth: 1` (shallow), where the commit graph above simply does not
exist locally. `discover_merge_commit_shas`/`reconstruct_pr_observation`
detect this via `repository_history_is_shallow()` and raise
`HistoryUnavailableError` rather than returning an empty/zero result;
`BaselineEvidenceSnapshot.history_available` carries the same signal
through the aggregate snapshot API, so "history could not be checked" is
never conflated with "history was checked and found empty". The GP-A7
test suite is split accordingly: hermetic logic tests run a synthetic,
disposable git repository built fresh in `tmp_path` (works identically
in any CI checkout depth) and are the primary/required coverage; the
CB-029 real-history proof above is an explicit, environment-dependent
test that is skipped (not failed) when the outer checkout is shallow.

**12. What was reconstructed vs directly measured?**
Every `HistoricalPRObservation` field carries an explicit
`field_provenance` entry of `"reconstructed"` for everything it reports
(files/additions/deletions/commits/pr_number/provider_label) — none of
it is claimed as `"measured_directly"`, because none of it was captured
at the time the work happened; it is all derived after the fact from
git. Within GP-A6's harness output, `scope_violation`/`policy_violation`/
`files_changed`/`outcome_state` (of the evaluation step itself) and, for
fixture-backed cases, `verifier_result`/`first_pass_success` ARE
`"measured_directly"` — the harness observed them live in the same
process call.

**13. Did anything change production/runtime behavior?**
No. Every new module is additive, under `backend/continuous_builder/
gpa_*.py`, imported by nothing outside GP-A's own tests. No existing
module's source was modified except `gpa_evidence_record.py` moving its
`PROVENANCE_CODES` constant into the shared `gpa_eval_schema.py` (both
new-this-phase files). No network access, no credentials, no new
dependency, no CI/workflow change, no runtime/queue/worker behavior
touched.

**14. Did TCB membership change?**
No. `create_mootos_tcb_registry_v1()` in `trusted_policy.py` was not
touched; component count (9), protected-path count (12), and
`registry_sha256` are identical before and after this phase (verified
live in `test_manifest_binds_live_tcb_registry_digest`).

**15. Did any evaluation component gain authority?**
No. Every sealed GP-A record structurally forces all 7 authority flags
(`publication_authorized`, `queue_transition_authorized`,
`github_authorized`, `merge_authorized`, `main_advancement_authorized`,
`result_trusted`, `worker_output_trusted`) to `False`; `require_no_
authority()` raises if any is ever anything else. Proven directly:
`test_completed_outcome_does_not_imply_trust` and
`test_zero_authority_regardless_of_outcome` construct records whose
`outcome_state`/`verifier_result` claim full success and assert
`result_trusted is False` and `worker_output_trusted is False` anyway.

**16. What exact prerequisites are now proven for GP-B?**
- A reproducible way to name "this exact MootOS architecture"
  (`ArchitectureBaselineManifest.manifest_sha256`) that GP-B's decomposer
  output can be benchmarked against.
- A task taxonomy GP-B can classify decomposed sub-tasks into, with
  descriptive (not authoritative) risk signals it can consult before
  deciding whether a sub-task is autonomy-appropriate — that decision
  itself remains GP-C's, per this phase's boundary.
- A worker-visible/evaluator-only separation pattern
  (`EvalCase`/`to_worker_visible_dict`) GP-B's decomposer-to-worker
  handoff can reuse directly instead of inventing its own.
- A provider-neutral evidence vocabulary (`EvidenceRecord`) any future
  Claude/Codex/Grok/GPU adapter can emit into, with the
  UNKNOWN-vs-fabricated-zero and provenance discipline already load-bearing.
- Proof (via the harness) that "the system independently re-derives
  evidence; it does not trust the worker's claim" is achievable without
  running a real provider — GP-B's decomposer output will need the same
  discipline once it dispatches real sub-tasks.

**17. What remains intentionally deferred?**
- Actually invoking Claude/Codex/Grok/GPU providers (explicitly out of
  scope for GP-A; GP-B/later).
- Wiring `evaluate_worker_submission()`'s independent verification to the
  repository's existing heavier verifier/sandbox infrastructure
  (`verifier_core.py`, `check_runner.py`, Docker runtime) for the 13
  structural-only corpus cases — deferred because that infrastructure
  expects a full sandboxed worker run, not an offline record; wiring it
  in was judged out of proportion to GP-A's "smallest useful harness"
  charge, and is flagged as the natural next increment.
- A real worker-facing context adapter that guarantees evaluator-only
  fixture paths (e.g. `acceptance.py`) are excluded from what a live
  provider actually sees (see item 6's limitation).
- Task decomposition, routing, and any trusted capability policy tied to
  taxonomy risk labels (GP-B, GP-C).
- Expanding the corpus beyond 16 cases, and adding real historical
  Claude/Codex/Grok token/cost telemetry once such data is actually
  captured going forward (this phase cannot retroactively invent it).

## Reproducibility

```python
from pathlib import Path
from backend.continuous_builder.gpa_architecture_baseline import (
    create_architecture_baseline_manifest,
)
from backend.continuous_builder.gpa_eval_corpus import (
    create_gpa_eval_corpus_v1, CORPUS_BASE_SHA,
)

baseline = create_architecture_baseline_manifest(
    Path("."), base_sha=CORPUS_BASE_SHA,
)
cases = create_gpa_eval_corpus_v1()
print(baseline.manifest_sha256, len(cases))
```

Re-running the above against a checkout at the exact same
`CORPUS_BASE_SHA` reproduces an identical `manifest_sha256` and an
identical list of `case_sha256` values — both are pure functions of
static repository content plus the frozen `_case_specs()` table, with no
timestamp, hostname, or random input anywhere in either digest.

## Known limitations

- The 13 structural-only corpus cases cannot be independently
  mechanically verified in this phase; the harness honestly returns
  `verifier_result="unknown"` for them rather than trusting a worker's
  claim or attempting a check it cannot back up.
- `HistoricalPRObservation.provider_label` is a branch-naming-convention
  heuristic, not a cryptographically or organizationally verified
  identity claim.
- No external, untrusted corpus-loading path exists (cases are authored
  directly in Python and covered by uniqueness tests); a future
  JSON/YAML corpus loader would need its own duplicate-ID and
  leakage-prevention checks re-verified independently of this phase's.
- Real MootOS-history reconstruction (GP-A7) requires a full local
  clone; it is not available in a shallow checkout (e.g. CI's
  `fetch-depth: 1`), and is not claimed to be — see item 11 above.
