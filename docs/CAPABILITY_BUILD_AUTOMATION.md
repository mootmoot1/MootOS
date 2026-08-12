# MootOS V0.4A — Capability-Build Automation Implementation Specification

**Status:** Proposed. **Not implemented.** This document is the design record
for work that has not started. Nothing under `scripts/capability_build/`
exists; no slice below has begun.

**Carries out:** ADR-036. Read that first — it holds the decision, the
authority boundaries, and the reasoning. This document holds the build plan.

**Applies to (future):** `scripts/capability_build/`, a new
`scripts/gates/builder_containment.py`, additive fields on
`scripts/capability_pipeline/spec.py` and
`scripts/capability_pipeline/review.py`, and `build_jobs/` as an artifact
directory.

**Automates:** the manual pipeline in `docs/CAPABILITY_BUILD_PIPELINE.md`,
specifically the hand-written orchestration in
`scripts/capability_pipeline/build_proof_record.py` and
`build_proof2_record.py`.

**Target size:** comparable to `scripts/gates/` (7 modules). If it starts to
look like a platform, stop and re-read ADR-036 §33.

## 1. Global rules for every slice

- No new surface in `backend/`. No HTTP route, no registered tool, no
  database table, no migration.
- No slice may import `backend.tool_registry` from
  `scripts/capability_build/` except inside the verifier's isolated
  subprocess.
- Every slice ships with tests; adversarial tests are not optional.
- Every module is deterministic. Model calls occur only in the worker session
  and the review stage, both outside this package.
- Python 3.9–3.11 (matching CI); `pytest==8.4.1`, `flake8==7.1.2` as pinned
  in `requirements-dev.txt`. **No dependency changes.**
- Each slice is one PR, reviewed under the existing V0.3E process
  (`docs/CAPABILITY_BUILD_PIPELINE.md` §7, ADR-032).

## 2. Approved budget defaults

Locked by ADR-036 §23. Recorded here so the implementer does not have to
re-derive them.

| Budget | Default |
| --- | --- |
| max fix rounds | 2 |
| max new files | 4 |
| max existing files edited | 2 |
| max net added lines | 300 |
| max changed lines in one existing domain file | 150 |
| max bytes per file | 64 KB |
| max bytes per diff | 256 KB |
| max characters per line | 500 |

## 3. Slice 1 — BuildJob record and state machine

**Files**

- `scripts/capability_build/__init__.py`
- `scripts/capability_build/job.py`
- `tests/test_capability_build_job.py`

**Responsibilities**

Immutable `BuildJob` record; the seven-state machine plus escape states;
append-only history with required `actor`/`note`/`at`; the single budgeted
backward edge; record content hashing; JSON load/save to
`build_jobs/<job_id>/job.json`.

**No-go authority**

May not import anything from `backend.*`. May not touch `CapabilityRecord`.
May not read or write the Tool Registry. May not run a subprocess. May not
create a worktree.

**Inputs** — `capability_id`, `spec_sha256`, `base_sha`, budgets, actor, note.

**Outputs** — `job.json`; a `BuildJob` value.

**State transitions**

```text
drafted -> dispatched -> returned -> validated -> verified -> reviewed -> ready_for_pr
any state -> needs_human | cancelled
verified(FAIL) | reviewed(blocking) -> dispatched   [fix_round += 1, < max_fix_rounds]
```

**Deterministic tests**

- Forward transitions succeed one step at a time; skipping, repeating, and
  going backward all raise.
- Missing or blank `actor`/`note` raises on every transition and on creation.
- The record is immutable: every operation returns a new value.
- `fix_round` increments only on the permitted backward edge.
- `needs_human` and `cancelled` are reachable from every state and are
  terminal.
- Round-trip `save` → `load` is lossless; content hash is stable across
  serialisation.

**Adversarial tests**

- **Import containment:** static assertion that `job.py`'s AST contains no
  import of `backend.*` (mirrors the existing `lifecycle.py` independence
  test in `tests/test_capability_lifecycle.py`).
- Constructing a `BuildJob` directly with `state="verified"` and empty history
  raises.
- `fix_round = 2` → the backward edge raises; only `needs_human` is
  available. No keyword, flag, or environment variable enables a third round.
- A record whose content hash does not match its contents fails to load.
- No public function advances state without an explicit call (no
  event-driven, implicit, or time-based transition exists).

**Exit criterion**

The full state machine is exercised by tests; no transition is possible
without an explicit actor and note; no import path to registry authority
exists; the third fix round is provably unreachable.

**Deferred** — everything else. Slice 1 touches no filesystem beyond
`build_jobs/`.

## 4. Slice 2 — Frozen scope, workspace, brief

**Files**

- `scripts/capability_build/scope.py`
- `scripts/capability_build/workspace.py`
- `scripts/capability_build/brief.py`
- additive changes to `scripts/capability_pipeline/spec.py`
- `tests/test_capability_build_scope.py`
- `tests/test_capability_build_workspace.py`
- `tests/test_capability_build_brief.py`
- extend `tests/test_capability_spec.py`

**Responsibilities**

`spec.py` (additive, backward-compatible): `allowed_new_files`,
`allowed_existing_files` (default `()`), `scope_justification`. Validation per
ADR-036 §11, enforced in `__post_init__` so direct construction cannot bypass
it. Existing spec files must continue to load; a spec without the new fields
is a **V0.3E spec** and is rejected only by the V0.4A pipeline, not by
`spec.py` itself.

`scope.py`: two clearly separated halves.

- `validate_scope(spec)` — **authority.** Enforces exact paths, disjointness,
  justification presence, and the unconditional forbidden list.
- `propose_scope(spec)` — **not authority.** Prints a suggested path list for
  a human to review and paste into a spec. Never called by intake, verify, or
  bundle. Enforced by a test.

`workspace.py`: `BuildWorkspace` protocol; `GitWorktreeWorkspace` with
`prepare(base_sha)`, `collect_diff()`, `dispose()`. Refuses a dirty tree in
scope paths; sets `core.hooksPath` to an empty directory; records hashes of
`.git/hooks/` and `.git/config`.

`brief.py`: `brief.md` plus the bounded context pack (~5 files, selected
deterministically from the spec); deterministic head/tail truncation with an
explicit elision count; untrusted-data delimiters around all spec free-text
and any repository excerpt.

**No-go authority**

`propose_scope` has zero authority. `brief.py` writes no code and grants no
permission. `workspace.py` performs no remote git operation and never
rebases.

**Inputs** — approved spec, base SHA, job.

**Outputs** — validated scope object; prepared worktree path; `brief.md`;
`context/`; recorded hook/config hashes.

**State transitions** — `(none) -> drafted`.

**Deterministic tests**

- Given the merged `capability_specs/projects_overview.json` extended with a
  frozen scope, `validate_scope` accepts exactly the files proof #2 changed,
  **minus** `backend/tool_registry.py`.
- Worktree is created at the exact pinned SHA; `dispose()` removes it.
- Dirty in-scope tree → refusal.
- Context pack is ≤ 5 files and byte-identical across repeated runs.
- Truncation is deterministic and reports the exact elided character count.

**Adversarial tests**

- Every entry in the unconditional forbidden list, presented as
  `allowed_new_files` or `allowed_existing_files`, makes the spec **invalid**
  — one test per class, explicitly including `tests/conftest.py`,
  `pytest.ini`, `pyproject.toml`, `setup.cfg`, `tox.ini`,
  `sitecustomize.py`, `*.pth`, and `backend/__init__.py`.
- A glob or directory prefix in a scope field is rejected.
- Case-only and Unicode-normalisation variants of an approved path do **not**
  match it.
- `allowed_existing_files` without `scope_justification` is rejected.
- Static assertion that `propose_scope` is not referenced anywhere in
  `intake.py`, `verify.py`, or `bundle.py`.
- Both existing `capability_specs/*.json` still load unchanged.

**Exit criterion**

Scope is frozen in the spec and validated exactly; the forbidden list rejects
every class including files that do not currently exist; the worktree pins,
refuses dirty trees, and neutralises hooks; the context pack is bounded and
reproducible.

**Deferred** — intake, verification, any execution of anything.

## 5. Slice 3 — Intake validation

**Files**

- `scripts/capability_build/intake.py`
- `tests/test_capability_build_intake.py`

**Responsibilities**

Validate the returned artifact against the pinned base and the frozen scope,
using `git diff --raw` (never `--name-only` alone):

base SHA matches the job · patch parses · the worktree's current diff matches
the returned artifact · every changed path is in the frozen scope · no
forbidden path · no symlink (`120000`), gitlink (`160000`), mode change, or
executable-bit change · no non-UTF-8 blob · realpath confinement under the
worktree root, rejecting `..`, absolute paths, and escapes · NFC + casefold
path comparison · `.git/hooks` and `.git/config` hashes unchanged since
prepare · byte and line budgets · pytest node-ID collection on base and head
for later removal detection · no removed test node IDs in
`allowed_existing_files` · no scratch or generated junk · `patch_sha256`
recorded.

**No-go authority**

Does not execute repository code. Node-ID collection runs under the same
isolated invocation the verifier uses (specified in Slice 4); until Slice 4
lands, intake records paths only and defers node-ID work. Never applies a
patch to the main checkout. Never modifies the worker's worktree.

**Inputs** — job, frozen scope, worktree, `changes.patch`.

**Outputs** — intake result with the complete violation list; `patch_sha256`;
node-ID sets.

**State transitions** — `dispatched -> returned` (artifacts present and
parseable) `-> validated` (all checks pass). Failure keeps the job at
`dispatched` with an `intake_failure` event and returns a **round-zero
correction** that does **not** consume a fix round.

**Deterministic tests**

- The real proof #2 diff from `f483ae1` validates cleanly against its base
  under a frozen scope derived from that capability.
- `patch_sha256` is stable and recorded on both success and failure.

**Adversarial tests**

- A mutated diff that also edits `backend/tool_registry.py` → rejected, with
  that exact path named.
- A mutated diff that edits `scripts/gates/policy.py` → rejected.
- A mutated diff that adds `tests/conftest.py` → rejected.
- A mutated diff that adds `pytest.ini` containing `addopts = --ignore=…` →
  rejected.
- An in-scope regular file converted to a symlink → rejected (the test that
  proves `--name-only` alone is insufficient).
- An in-scope file made executable → rejected.
- A submodule/gitlink entry → rejected.
- A binary blob and a 300 KB single-line file → both rejected.
- `../` traversal, an absolute path, and a case-only path variant → all
  rejected.
- A diff that deletes an existing test node ID in an `allowed_existing_files`
  test file → rejected.
- A `.git/hooks/pre-commit` written during the worker session → detected by
  hash comparison.

**Exit criterion**

Every attack in the adversarial list is rejected with a specific, actionable
reason; the real proof #2 diff passes; intake failure never consumes a fix
round.

**Deferred** — running tests, gates, evidence.

## 6. Slice 4 — Verifier and evidence (the core slice)

**Files**

- `scripts/capability_build/verify.py`
- `scripts/capability_build/_reporter.py` (MootOS-owned pytest reporter,
  loaded via `-p` from a trusted extraction)
- `tests/test_capability_build_verify.py`
- `tests/test_capability_build_evidence.py`

**Responsibilities**

*Isolation (blocking, ADR-036 §14).* Environment allowlist, temp `HOME`, temp
SQLite path set **before process start**, `PYTHONNOUSERSITE=1`,
`PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`, `-p no:cacheprovider`, explicit
`PYTHONPATH` and test paths, network disabled where OS support exists,
per-subprocess wall-clock timeout, full log capture. Gates run **inside** the
same isolation, loaded from a trusted extraction of the base ref. Generated-
code verification must not inherit normal production secrets or an
unrestricted host environment.

*Fresh worktree.* Verification always occurs on a worktree created from the
pinned base with the patch applied — never the worker's tree.

*Two-phase run.* Phase 1 unregistered (protected-path gate must PASS); phase
2 registered (only protected path may be `backend/tool_registry.py`, and
phase 2 minus phase 1 must equal the generated registration patch
byte-for-byte).

*F2P.* Base outcome ∈ `{failed, error}`; declared `expected_base_failure`
category verified; empty-patch control run; after-patch pass; double-run
stability.

*P2P.* Touched modules + reverse-dependency modules (AST import graph) +
`tests/test_tool_registry.py`; node-ID removal detection; full suite once in
phase 2; blocking lint.

*Environmental.* Proof rule per ADR-036 §18 — base reproduction, or a narrowly
defined pre-test infrastructure failure. **No error-string matching anywhere
in this module** (enforced by test). Retry once; never consumes a fix round;
persists → `needs_human`.

*Evidence.* The full binding set from ADR-036 §15, including a materialised
verification commit on `refs/mootos/jobs/<job_id>/r<N>` and the `tree_sha`
from `git write-tree`.

**No-go authority**

Never applies the registration patch to the real checkout. Never pushes,
merges, or opens anything. Never writes outside `build_jobs/` and the
disposable worktree. Never emits a verdict field or an aggregate pass/fail
badge into the human-facing artifact.

**Inputs** — validated job, frozen scope, pinned base, patch, spec.

**Outputs** — `evidence.json`; complete logs; verification commit ref.

**State transitions** — `validated -> verified` on pass;
`validated -> dispatched (fix_round += 1)` on genuine failure; `->
needs_human` on budget, timeout, or unresolved environmental.

**Deterministic tests**

- **Replay:** proof #2's required tests FAIL at the pre-proof base and PASS
  after `f483ae1`.
- Evidence contains every binding field; `tree_sha` is stable for identical
  content and independent of commit timestamp.
- Phase 1 records the protected-path gate as PASS for a worker diff that
  touches no protected path.
- Phase 2's diff-minus-phase-1 equals the registration patch exactly.
- Environment fingerprint records interpreter, versions, allowlist keys,
  pytest argv verbatim, and `network_disabled`.

**Adversarial tests**

- A test that **skips** on base and passes after → F2P violation.
- A test that **xfails** on base → F2P violation.
- A test that **passes** on base → F2P violation (fake test).
- A test that fails on base for a reason not matching its declared
  `expected_base_failure` category → violation. One test per category.
- A test whose base outcome differs between the plain and empty-patch runs →
  non-determinism violation.
- A test with different outcomes across the two stability runs → violation.
- A simulated SQLite disk-I/O failure that **reproduces on base** →
  classified `environmental`, retried once, does not consume a fix round, and
  appears in evidence.
- The same failure **not** reproducing on base → **genuine failure**, not
  environmental.
- A test raising `RuntimeError("database is locked")` that does not reproduce
  on base → **genuine failure**. This is the test that proves string matching
  is absent.
- Static assertion: no error-string classification table exists in
  `verify.py`.
- A patched module that reads `os.environ["OPENAI_API_KEY"]` observes it
  absent; a module that opens `~/.ssh` finds a temp `HOME`.
- Evidence from job A cannot be validated against job B.

**Exit criterion**

Proof #2 replay reproduces the human-reached mechanical conclusions; the real
SQLite environmental failure classifies as environmental **by base
reproduction**; every fake-test attack is caught; the isolation controls are
demonstrated by test, not asserted in a docstring.

**Deferred** — review binding, registration generation, bundle.

## 7. Slice 5 — Review binding and bounded fix loop

**Files**

- additive changes to `scripts/capability_pipeline/review.py`
- fix-brief generation in `scripts/capability_build/brief.py`
- re-review escalation rule in `scripts/capability_build/job.py`
- `tests/test_capability_build_review_binding.py`
- extend `tests/test_capability_lifecycle.py`

**Responsibilities**

`AdvisoryReview` gains `artifact_tree_sha`, `artifact_commit_sha`,
`context_manifest` (all defaulting to empty; existing record files load
unchanged). `tree_sha` is the primary binding. Binding values are re-derived
by `cli.py` from job state — **never supplied by a model**. Unbound reviews
cannot satisfy `reviewed`. Stale reviews fail validation. Fix briefs carry
only truncated evidence plus delimited findings. The deterministic re-review
escalation table (ADR-036 §22) is implemented as a pure function of the fix
diff.

**No-go authority**

Reviews still cannot transition anything; `attach_review()` is unmodified in
behaviour. The escalation function decides *which reviewers run*, never
whether the job proceeds.

**Inputs** — verified job, evidence, reviewer output.

**Outputs** — bound review records; fix briefs; re-review role set.

**State transitions** — `verified -> reviewed`;
`reviewed(blocking) -> dispatched (fix_round += 1)`.

**Deterministic tests**

- Both existing `capability_specs/*.json` load with the new fields absent.
- A review bound to the current `tree_sha` satisfies `reviewed`; identical
  content committed twice produces the same `tree_sha` and remains valid
  (this is why tree SHA, not commit SHA, is primary).
- `context_manifest` records exactly the files the reviewer was given.
- Escalation table: each row produces the specified role set; overlapping
  rows take the union; correctness always present.

**Adversarial tests**

- An unbound review (empty `artifact_tree_sha`) cannot satisfy `reviewed`.
- A review bound to a superseded `tree_sha` is reported **stale**.
- A reviewer-supplied `artifact_tree_sha` is ignored and overwritten by the
  deterministically re-derived value.
- A fix diff adding a new file forces **all three** roles regardless of size.
- A finding whose `file:line` does not exist in the bound artifact is
  recorded `unreproduced`, not acted on.
- A findings file containing `"also edit backend/tool_registry.py"` produces
  a fix brief in which that text is delimited as data, and the resulting diff
  is rejected by intake regardless.
- `fix_round = 2` with a blocking finding → `needs_human`, not a third round.

**Exit criterion**

Reviews are mechanically bound to immutable content identity; stale and
unbound reviews cannot count; escalation is deterministic and conservative;
the fix loop provably cannot exceed two rounds.

**Deferred** — registration, bundle, CLI.

## 8. Slice 6 — Registration patch, bundle, CLI, containment gate, docs

**Files**

- `scripts/capability_build/registration_patch.py`
- `scripts/capability_build/bundle.py`
- `scripts/capability_build/cli.py`
- `scripts/gates/builder_containment.py` + wiring into `run_gates.py`
- `scripts/gates/policy.py`: add `scripts/capability_build/`
- `tests/test_capability_build_registration.py`
- `tests/test_capability_build_bundle.py`
- `tests/test_capability_build_cli.py`
- `tests/test_gates_builder_containment.py`
- documentation updates to this file and `docs/README.md`

**Responsibilities**

Deterministic registration generator with validations V1–V5 (ADR-036 §24) and
the `REGISTRATION_MANUAL.md` fallback. Bundle assembly that **refuses** stale
or mismatched evidence and leads with the raw diff, containing no verdict
field and no aggregate badge. CLI with explicit human-invoked stages and a
hard refusal under `CI` / `GITHUB_ACTIONS` / non-interactive stdin, with no
override. The `builder_containment` gate's five checks (ADR-036 §28.B).

**No-go authority**

The registration patch is never applied to the real checkout by any code. The
CLI performs no remote git operation. The bundle produces no recommendation.

**Inputs** — reviewed job, evidence, spec, reviews.

**Outputs** — `registration.patch` (or `REGISTRATION_MANUAL.md`); the
assembled bundle; `ready_for_pr`.

**State transitions** — `reviewed -> ready_for_pr`.

**Deterministic tests**

- The generated registration patch for proof #2 is equivalent, modulo
  whitespace, to the hunk the human actually wrote in
  `backend/tool_registry.py`.
- Applying it still **fails** the protected-path gate — the intended
  elevated-review signal, preserved.
- The bundle contains diff, evidence, gate output, bound reviews,
  registration patch, and full job history, with the diff first.
- CLI stage commands are the only way to advance state.

**Adversarial tests**

- A `capability_id` crafted to escape the identifier regex → generator
  refuses (V2).
- A target module absent from `allowed_new_files` → refuses (V3).
- A target module in `allowed_new_files` but absent from the verified patch →
  refuses (V3).
- A generated patch that would touch two files or add two calls → refuses
  (V4).
- A registration patch from job A applied against job B's bundle → refused
  (V5).
- Bundle refuses on each of: mismatched `patch_sha256`, mismatched
  `base_sha`, mismatched `tree_sha`, mismatched `spec_sha256`, foreign
  `verifier_run_id`.
- Bundle output contains no verdict field and no aggregate pass/fail badge
  (asserted on the rendered artifact).
- Worker report renders escaped and fenced, positioned below the diff.
- `CI=true` → CLI refuses; `GITHUB_ACTIONS=true` → refuses; non-interactive
  stdin → refuses. **No flag, environment variable, or config enables it.**
- `builder_containment`: a fixture `backend/` file importing
  `capability_build` → gate FAILS; a fixture workflow referencing
  `capability_build` → FAILS; a `backend/` file reading `build_jobs/` →
  FAILS; a `git push` string under `scripts/capability_build/` → FAILS; a
  `cli.py` with its refusal guard removed → FAILS.

**Exit criterion**

Registration generation is safe under all five validations with a working
fallback; the bundle cannot be assembled from mismatched artifacts; the CLI
provably cannot run unattended; `builder_containment` fails closed on all five
checks; this document and `docs/README.md` are updated to reflect the
implemented state.

**Deferred** — everything in ADR-036 §27.

## 9. Final acceptance plan

### A. Replay real history

Drive the completed pipeline against the actual Proof #2 commits — `f483ae1`
(initial implementation), `089243c` (review fixes), `38a53bb` (Unicode/SQLite
NOCASE fix); base = `f483ae1`'s first parent, expected `9f323a4`, verified at
implementation time.

Confirm the automation reproduces: frozen-scope validation against the real
diff; F2P red-then-green with correct base-failure categories; P2P including
node-ID removal detection; the intended protected-path gate behaviour in both
phases; environmental classification of the real SQLite noise **by base
reproduction**; complete artifact binding; correct registration preparation;
and bounded fix handling across the review-fix cycle.

**Stated explicitly:** the replay does **not** prove that deterministic checks
would have found the four semantic defects the reviewers found, or the NOCASE
release blocker. They would not have. The replay proves the automation
reproduces the *mechanics*. Semantics remain the advisory review stage's job,
which is exactly why ADR-032's roles are retained unchanged.

### B. Proof #3

One genuinely new small capability, end to end, through the automated pipeline
from approved spec to PR-ready bundle. Constraints matching proof #1 and #2:
read-only, local, no credential, no migration, no configuration gate, none of
the excluded categories.

The human still: selects and launches the worker, approves the spec, reviews
the bundle **and the diff**, applies the registration change, merges, deploys,
and live-verifies.

**Proof #3 is the acceptance proof for V0.4A.** Until it passes, V0.4A is
implemented but not accepted.

## 10. Non-blocking follow-up (not V0.4A scope)

A small `CapabilitySpec` validation rule: every **optional** field in
`input_contract` must document the semantics of omission. This addresses the
Proof #2 live observation where the model invented an "ALL" project rather
than calling `projects.overview` with `{}`. The schema and executor were
correct; this is tool-contract clarity. Ship only if it does not delay
Slices 1–6.
