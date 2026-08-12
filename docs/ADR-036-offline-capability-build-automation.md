# ADR-036 — V0.4A automates the mechanics of the proven capability-build pipeline as offline, human-invoked tooling; MootOS owns the evidence and the worker owns nothing

## Status

**Proposed.** Recorded August 2026. Supersedes nothing.

This ADR is the separate design/review step ADR-034 required before any
capability-builder automation is built. It carries out ADR-034's deferred
"V0.4A (Capability Builder Automation)" phase. It depends on, and does not
modify, ADR-028 (Capability is semantic grouping, not a second registry),
ADR-029 (generated catalog), ADR-030 (advisory gap reports), ADR-031
(protected core + mechanical gates), ADR-032 (advisory multi-AI review with
distinct roles), ADR-033 (Local Node / Codex dispatch are usage-gated), and
ADR-034 (manual proof before automation).

**Prerequisite satisfied.** ADR-034 required two real capabilities to pass
the manual pipeline before any part of it is automated.
`tasks.status_summary` (proof #1) and `projects.overview` (proof #2) are both
merged, deployed, and live-verified — see `docs/CAPABILITY_BUILD_PIPELINE.md`
§11–§13.

**Nothing in this ADR is implemented.** It is a design record. The
implementation is divided into six future slices described in
`docs/CAPABILITY_BUILD_AUTOMATION.md`; Slice 1 begins only after this
document is reviewed and merged.

Section numbering below follows the approved design document: §1 (Title) is
this document's heading and §2 (Status) is this section, so the numbered
sections begin at §3. Internal cross-references (§11, §14, §15, §18, §19,
§22, §24, §28) use those numbers.

## 3. Context

V0.3E proved the capability-build pipeline by hand, twice. The second proof
was the informative one: the first implementation passed every test and was
still wrong in four reproducible ways; independent advisory review found
them; a later adversarial audit found a release-blocking Unicode/SQLite
NOCASE defect; Codex remediated it; Grok re-audited the corrected commit; CI
passed; the protected-path gate correctly flagged the registry change; a
human merged, deployed, and live-verified. Along the way the local
environment produced genuine SQLite disk-I/O failures that also reproduced on
clean `main`.

Two scripts — `scripts/capability_pipeline/build_proof_record.py` and
`build_proof2_record.py` — performed the orchestration by hand for those two
runs. V0.4A generalises exactly those two scripts. It automates the
*mechanics* around the process: preparing an isolated checkout, writing a
bounded brief, validating a returned diff against an approved scope, running
the tests and gates, producing evidence, and assembling a reviewable bundle.

External research (mini-SWE-agent, SWE-agent, SWE-ReX, OpenHands, Aider)
converged on three findings that shape this design. First, scaffold
complexity buys little: on SWE-bench Verified, holding the model constant at
Claude 4 Sonnet and single attempt, two very different scaffolds differ by
about four points, while a model-generation change under one scaffold moves
about seventeen. Second, the durable idea worth borrowing is not an agent
architecture but an *evidence contract* — SWE-bench's FAIL_TO_PASS /
PASS_TO_PASS grading with a separate class for environmental outcomes. Third,
the failure modes to avoid are named and concrete: OpenHands'
`LLMSecurityAnalyzer` lets the model declare its own risk level, and
OpenHands V1 makes sandboxing opt-in with the unisolated path as the default.
Both are inversions of MootOS's posture.

Adversarial review of the draft design surfaced four defects that this ADR
resolves rather than inherits, because each falsified a guarantee the draft
claimed:

- `scripts/gates/risk_metadata.py` imports `backend.tool_registry` and calls
  `build_default_registry()`. The mechanical gates therefore already execute
  the code they are inspecting. "Gates are deterministic and execute nothing
  untrusted" is false in this repository today.
- This repository has no `conftest.py`, no `pytest.ini`, no `setup.cfg`, no
  `pyproject.toml`, and no `tox.ini`. `scripts/gates/policy.py`'s
  `DENIED_PATHS` protects paths that exist. Files that do not yet exist but
  would be privileged if created were entirely ungoverned.
- Whether verification runs with or without the registration change applied
  was unspecified, and both naive answers are broken.
- A tidy evidence summary is an attention-laundering device. V0.3E's safety
  came from a human reading a diff.

## 4. Problem statement

Automate the repetitive mechanics of the proven capability-build pipeline
without granting any new authority to any non-human actor, without creating a
second source of truth about what MootOS can execute, and without believing
anything a coding worker says about its own work.

Specifically: what is the smallest set of deterministic tooling that turns "a
human directs a worker and then carefully checks everything by hand" into "a
human directs a worker and then reads MootOS-produced evidence plus the
diff", while making the following structurally impossible rather than merely
forbidden — self-registration, evidence forgery, scope escape, silent
regression, and unattended execution.

## 5. Decision

MootOS adopts **V0.4A: an offline, human-invoked capability-build automation
package** under `scripts/capability_build/`, governed by one rule:

> **MootOS produces the brief and owns the evidence.
> The worker produces a diff.
> Nothing else the worker says counts.**

Concretely, MootOS decides:

1. **V0.4A adds zero authority to the running service.** No HTTP route, no
   registered tool, no database table, no migration, no daemon, no scheduler,
   no event bus. Nothing under `scripts/capability_build/` may be imported by
   `backend/` or referenced by `.github/workflows/`. This is enforced by a
   new mechanical gate, not by prose.
2. **Worker invocation is file handoff only.** MootOS prepares a job
   directory, a pinned worktree, a brief, a frozen scope, and a bounded
   context pack. A human opens Codex or Claude Code against that worktree.
   MootOS never spawns a worker, holds worker credentials, or supervises a
   worker process.
3. **The human-approved `CapabilitySpec` is the write-authority document.**
   Write scope is *frozen in the spec before dispatch* as exact
   repository-relative paths. Scope-generation logic may propose those paths
   for human review; it has no authority after approval. Write permission is
   never derived from generic fields such as `resource_or_connector` after
   the human has approved.
4. **Default posture is new-file-only.** Editing an existing file requires
   explicit listing in the approved spec, a written justification, and
   tighter diff inspection.
5. **MootOS runs the tests and gates itself and produces its own
   `evidence.json`**, cryptographically bound to the job, spec, base commit,
   patch, and resulting tree. `worker_report.md` is narrative and is read by
   no state transition.
6. **FAIL_TO_PASS is stronger than "red on base."** Each required test
   declares an expected base-failure category from a closed vocabulary, and
   the verifier confirms the base failed for the declared reason. `skipped`,
   `xfailed`, `xpassed`, and `passed` are all F2P contract violations.
7. **Environmental failure requires proof, not pattern matching.** Only base
   reproduction under the same recorded environment, or a narrowly defined
   pre-test infrastructure failure, may be labelled environmental.
8. **Registration remains privileged and human-controlled.**
   `backend/tool_registry.py` is unconditionally forbidden to the worker. A
   deterministic generator may prepare a separate registration patch under
   strict preconditions; if any precondition fails, MootOS emits the exact
   line for a human to type instead.
9. **The fix loop is bounded at two rounds with no override.** At the limit,
   the job goes to `needs_human`.
10. **Human approval points stay at two:** spec approval before build, and
    PR/merge approval after evidence and review. Dispatch and
    registration-patch application are deliberate human terminal actions
    within those.

## 6. Architectural invariants

Each invariant names the mechanism that enforces it, because an invariant
with no mechanism is an aspiration.

| # | Invariant | Enforced by |
| --- | --- | --- |
| I1 | The live Tool Registry is the sole executable authority | ADR-028; `builder_containment` gate forbids `backend/**` reading `build_jobs/` or `capability_specs/` |
| I2 | A spec, a lifecycle record, or a BuildJob can never make a capability live | `job.py` has no import path to `backend.tool_registry`; test-enforced |
| I3 | Generated code cannot register itself | `backend/tool_registry.py` on the unconditional forbidden list; registration emitted by template with strict identifier validation |
| I4 | Generated code gets no production deployment authority | `railway.toml` forbidden; no component performs a deploy or a remote git write; test-enforced |
| I5 | No production secrets reach the verification environment | Environment allowlist (not denylist), temp `HOME`, temp SQLite path, `.env*` forbidden |
| I6 | No arbitrary modification of protected core | Frozen scope + unconditional forbidden list + V0.3D protected-path gate |
| I7 | Protected-core changes require elevated human review | V0.3D gate unchanged; the registration patch deliberately still trips it |
| I8 | AI reviewers are advisory | `attach_review()` returns state unchanged (V0.3E, unmodified); verdicts are not approve/reject |
| I9 | Mechanical gates remain authoritative | `run_gates.py` unchanged, invoked by the verifier from a trusted extraction |
| I10 | The user is the final merge/install authority | No component opens a PR, merges, or installs |
| I11 | No model chooses its own risk classification | `CapabilitySpec` risk enum + cross-field rule; **and** environmental classification is proof-based, not string-based, closing the side channel |
| I12 | Unknown execution paths fail closed | Every check in the pipeline denies on unrecognised input |
| I13 | No uncontrolled autonomous or background loops | No daemon; `cli.py` refuses under CI/non-interactive stdin; `builder_containment` forbids workflow references |
| I14 | No permanent arbitrary shell or root exposed through MootOS | V0.4A is not reachable from the service at all |
| I15 | Workers are workers, not authorities | Worker narrative read by no transition |
| I16 | **New:** V0.4A never becomes a runtime surface without a new ADR | `builder_containment` gate + §31 of this ADR |

## 7. Trust / authority boundaries

| Actor | May | May never |
| --- | --- | --- |
| **Human** | approve spec (and therefore the literal file list); dispatch; read the diff and evidence; apply the registration change; open PR; merge; deploy | — (final authority) |
| **MootOS offline tooling** | prepare worktree; write brief; validate patch; run tests/lint/gates; classify failures; write evidence; advance BuildJob; generate registration patch; assemble bundle | transition a `CapabilityRecord`; register; merge; push; deploy; open a PR; run unattended; dispatch a worker |
| **Worker** | read approved context; edit approved paths; run approved commands; return a patch and a narrative | commit; push; merge; PR; deploy; register; touch forbidden paths; alter gates, pipeline, permissions, or its own risk classification; **be believed** |
| **AI reviewer (critic)** | read an immutable verified artifact; return findings | block; unblock; approve; edit; transition anything; supply its own binding values |
| **Mechanical gates** | block auto-merge | approve; be overridden by any AI |

**Source-of-truth hierarchy (unchanged, restated as binding):**

```text
what can execute            -> live Tool Registry
what abilities exist        -> registry-derived capability catalog
what is missing             -> advisory gap reasoning, checked against registry truth
what was approved to build  -> human-approved CapabilitySpec
what the worker produced    -> a patch; untrusted until verified
what proves the patch       -> deterministic evidence bound to the exact artifact
what reviewers think        -> advisory review artifacts
what decides merge/install  -> human authority + V0.3D mechanical gates
```

**BuildJob is never inserted into this hierarchy.** It is a build-process
record. It answers "what happened during this build", never "what MootOS can
do".

## 8. Components

Target size and shape: roughly `scripts/gates/` (7 modules), not a platform.

```text
scripts/capability_build/
  job.py                  BuildJob record + state machine (immutable, append-only)
  scope.py                Frozen-scope validation + (separately) scope proposal
  workspace.py            BuildWorkspace protocol + GitWorktreeWorkspace
  brief.py                Brief + bounded context pack + deterministic truncation
  intake.py               Artifact validation against the frozen scope
  verify.py               Evidence producer: F2P/P2P/gates/lint, isolated execution
  registration_patch.py   Deterministic registration emitter (privileged)
  bundle.py               Binding validation + PR-ready assembly
  cli.py                  Human-invoked stage commands; refuses non-interactive use

scripts/gates/
  builder_containment.py  NEW gate (see §28.B) — added to run_gates.py
```

Reused unchanged: `scripts/capability_pipeline/spec.py` (extended
additively), `lifecycle.py`, `review.py` (extended additively),
`scripts/gates/*`, `backend/gap_reasoning.py`,
`backend/capability_catalog.py`.

## 9. BuildJob state machine

```text
drafted -> dispatched -> returned -> validated -> verified -> reviewed -> ready_for_pr

escape / terminal (reachable from any state):
    needs_human        blocked; requires a human decision; never auto-retried
    cancelled          human aborted; worktree disposed, artifacts retained

only permitted backward edge:
    verified(FAIL) or reviewed(blocking_concern)  ->  dispatched
    with fix_round += 1, permitted only while fix_round < max_fix_rounds (2)
    at the limit: -> needs_human. No override flag. No exception.
```

BuildJob mirrors `CapabilityRecord`'s proven shape: frozen dataclass,
append-only history, every event carrying `actor`, `note`, and `at`,
persisted as version-controlled JSON, replayable.

It differs in exactly one respect, deliberately: deterministic transitions
record a machine actor (`mootos:builder`). This is honest and auditable, and
it does not weaken `CapabilityRecord`'s human-only rule, because **a BuildJob
cannot transition a `CapabilityRecord`**. The job produces evidence; a human
reads it and then makes the V0.3E lifecycle transitions by hand.

Records live in `build_jobs/<job_id>/`, **not** in `capability_specs/`, so a
directory listing can never be mistaken for a capability catalog.

## 10. Worker contract

A pure file contract. No SDK, no API client, no vendor adapter — which is
what makes it vendor-neutral. Codex, Claude Code, a future local model, or a
human satisfies it identically.

**MootOS writes (job inputs):**

| Path | Contents |
| --- | --- |
| `build_jobs/<job_id>/brief.md` | task; frozen allowed paths; forbidden paths; required tests and their expected base-failure categories; allowed commands; budgets; explicit prohibitions |
| `build_jobs/<job_id>/spec.json` | the approved `CapabilitySpec`, verbatim |
| `build_jobs/<job_id>/context/` | bounded context pack (§26) |
| `build_jobs/<job_id>/findings.md` | fix rounds only: MootOS's own failure evidence plus reviewer findings, delimited as untrusted data |
| worktree | `git worktree` at the exact pinned base SHA |

**Worker writes (job outputs):**

| Path | Contents |
| --- | --- |
| `build_jobs/<job_id>/r<N>/changes.patch` | `git diff` against the pinned base; **uncommitted** |
| `build_jobs/<job_id>/r<N>/worker_report.md` | narrative; **untrusted; read by no transition** |

**Explicit prohibitions stated in every brief:** no commit, no push, no
merge, no PR, no deploy, no registration, no edit outside the frozen scope,
no dependency change, no test-collection configuration.

These are stated in the brief for clarity, but none of them is *enforced* by
the brief. Every one is enforced mechanically at intake against the returned
artifact. Prose is not a boundary.

## 11. Write-scope contract

`CapabilitySpec` gains three additive fields, frozen at human approval:

```text
allowed_new_files:      tuple[str, ...]   # exact repo-relative paths, created by this capability
allowed_existing_files: tuple[str, ...]   # exact repo-relative paths, may be edited; DEFAULT ()
scope_justification:    Mapping[str, str] # required: one entry per allowed_existing_files path
```

Validation rules (fail-closed, enforced in `__post_init__` so direct
construction cannot bypass them, mirroring the existing pattern):

- Exact paths only. **No globs, no directory prefixes, no patterns.**
- Every `allowed_existing_files` entry requires a non-empty
  `scope_justification` entry.
- A spec naming any path on the unconditional forbidden list is **invalid** —
  not "requires elevated review", invalid.
- `allowed_new_files` and `allowed_existing_files` must be disjoint.
- Paths are compared after NFC normalisation and case-folding, so a case-only
  or Unicode-normalisation variant cannot masquerade as an approved path.

**Unconditional forbidden paths** (apply to every job regardless of spec):

| Class | Paths | Protects |
| --- | --- | --- |
| Registry authority | `backend/tool_registry.py` | what can execute |
| Release gates | `scripts/gates/**` | the gates themselves |
| Pipeline authority | `scripts/capability_pipeline/**`, `scripts/capability_build/**` | the build process |
| Deployment | `railway.toml`, `.github/workflows/**` | production + CI |
| Dependency surface | `requirements*.txt`, `requirements-dev.txt` | installed packages |
| Migration machinery | `backend/migrations.py` | schema history |
| Secrets / data | `.env*` (except `.env.example`), `data/**` | credentials + user data |
| **Test-collection control** | `conftest.py` (any directory), `pytest.ini`, `tox.ini`, `pyproject.toml`, `setup.cfg`, `setup.py`, `*.pth`, `sitecustomize.py`, `usercustomize.py` | evidence integrity |
| Package initialisation | any `__init__.py` | import side effects |
| Everything in V0.3D policy | all of `scripts/gates/policy.py`'s `DENIED_PATHS` | the existing protected core |

The test-collection class is the one V0.3D does not cover, because **none of
those files currently exists in this repository**. A `tests/conftest.py`
executes at collection before any assertion runs; a `pytest.ini` with
`addopts = --ignore=…` silently deletes the regression evidence that
constitutes PASS_TO_PASS. A protection list that only names existing files
does not protect against creation.

`conftest.py` is forbidden in V0.4A with **no exception, per-job or
otherwise**. If a future capability genuinely requires shared test fixtures,
that is a change to this ADR, not a per-job override.

`scripts/capability_build/**` is additionally added to
`scripts/gates/policy.py`'s `DENIED_PATHS`, so a *human-authored* PR touching
the builder receives the same elevated review as a gate change. The builder
is pipeline authority and is protected like it.

## 12. Workspace model

```text
BuildWorkspace (protocol)
    prepare(base_sha) -> Path
    collect_diff()    -> bytes
    dispose()         -> None

GitWorktreeWorkspace  (the one V0.4A implementation)
```

The protocol exists only so a stronger isolation implementation can be added
later without rewriting the pipeline. V0.4A does not build SWE-ReX-style or
OpenHands-style runtime infrastructure, and adding a second implementation is
not in scope.

Preparation rules:

- Pin an exact base SHA; record it. **Never silently rebase.**
- Refuse to prepare if the repository has uncommitted changes in any path in
  the frozen scope.
- Set `core.hooksPath` for the job worktree to an empty directory, and record
  a hash of `.git/hooks/` and `.git/config` at prepare time for comparison at
  intake. A `git worktree` shares the common `.git` directory, so hooks
  written during a worker session would otherwise execute later under the
  human's identity in the main checkout, invisible to every diff.
- One job per `capability_id`; the job directory's creation is the mutex.
- **Verification always occurs on a fresh worktree** created from the pinned
  base with the returned patch applied — never on the worker's worktree.

## 13. Edit isolation vs execution isolation

These are different properties and this ADR states both plainly.

**Edit isolation — a `git worktree` is sufficient for V0.4A, and it is not
doing the job the name implies.**

A worktree does not confine the worker. In file-handoff mode the worker runs
under the human's shell, environment, network, credentials, and filesystem
access. What actually provides the safety property is (a) exact-file scope
validation of the returned artifact and (b) verifying on a fresh worktree
built from the pinned base plus the patch. Nothing the worker did during
editing can reach the evidence.

The correct term is **edit scoping**, not isolation, and this ADR uses that
term. This is acceptable in V0.4A because the worker is manually launched by
the user, on the user's own machine, under `AGENTS.md`'s existing worker
boundaries. It is a decision made explicitly rather than by omission.

**Execution isolation — a worktree is NOT sufficient, and stronger controls
are blocking.**

The verifier executes AI-generated Python. It does so twice: through pytest
collection and execution, and through `run_gates.py`, whose risk-metadata
gate imports `backend.tool_registry` and calls `build_default_registry()`.
That code otherwise runs on a machine holding a real `.env`, live API keys in
the shell, the real `data/mootos.db`, git push credentials, and network
egress. That is not a hypothetical adversary; it is the default state of the
machine where V0.4A will run.

## 14. Verifier execution model

The verifier runs every subprocess under a clean, recorded, fail-closed
environment. **All of the following are blocking requirements for Slice 4.**
Generated-code verification must not inherit normal production secrets or an
unrestricted host environment.

| Control | Requirement |
| --- | --- |
| Interpreter | exact `sys.executable` and `sys.version` recorded in evidence |
| Environment | explicit **allowlist**, not denylist: `PATH`, `LANG`, `LC_ALL`, `TMPDIR`, `PYTHONNOUSERSITE=1`, `PYTHONDONTWRITEBYTECODE=1`, `MOOTOS_DATABASE_PATH=<temp>`. Nothing else. `MOOTOS_ALLOW_UNSAFE_DATABASE_PATH` explicitly absent |
| HOME | fresh temporary directory (blocks `~/.ssh`, `~/.aws`, credential helpers) |
| Secrets | no `.env` resolvable from the working directory or any parent |
| Database | temporary SQLite file. Note `backend/db.py` resolves `DATABASE_PATH` **at module import**, so scrubbing must happen before the process starts, never in a fixture |
| PYTHONPATH | explicit; the verification worktree only |
| Network | disabled by default. Where OS support exists (`unshare`/`bwrap` on Linux), enforce it; where it does not, record `network_disabled: false` in the environment fingerprint so every downstream artifact carries that fact |
| pytest plugins | `-p no:cacheprovider`, ambient plugin autoloading disabled (`PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`), explicit test paths, MootOS-controlled argv recorded verbatim |
| Gates | `run_gates.py` executed **inside the same isolation**, loaded from a trusted extraction of the base ref — reusing the pattern CI already uses |
| Timeouts | wall-clock timeout per subprocess; exceeded → `needs_human` |
| Output | captured completely to job artifacts; only deterministically truncated excerpts (head/tail with an explicit elision count) are ever passed to a model |

**Stated plainly, without overclaiming:** the verifier is the primary residual
execution-risk boundary in V0.4A, because generated code actually runs there.
The controls above raise the floor substantially; they are not a container
and they are not a proof. A full container/runtime sandbox is deferred until
either (a) a future threat model requires it, or (b) automated worker
dispatch removes the human from the loop — at which point it becomes
blocking.

Users running V0.4A on a machine that holds production credentials should
enable OS-level network and filesystem confinement. This ADR records that as
an explicit user decision rather than a default assumption.

## 15. Evidence contract

`worker_report.md` is narrative. It is never evidence. **No state transition
reads it.**

MootOS generates `evidence.json` independently, bound mechanically to:

```text
schema_version, job_id, capability_id, fix_round
spec_sha256              canonical JSON of the approved spec
base_sha                 pinned commit
patch_sha256             bytes of changes.patch
tree_sha                 git write-tree of the verification worktree after apply
verification_commit      commit on refs/mootos/jobs/<job_id>/r<N>
verifier_run_id          uuid4, one per verifier invocation
environment_fingerprint  interpreter, versions, env allowlist keys, pytest argv,
                         network_disabled, isolation_mode
started_at, finished_at
phase1 {...}  phase2 {...}  gates {...}  lint {...}  budgets {...}
outcome: pass | fail | environmental_blocked
```

`bundle.py` **refuses** on: stale evidence, mismatched patch hash, mismatched
base SHA, mismatched tree SHA, mismatched spec hash, or a `verifier_run_id`
belonging to another job. `verified` is reachable only when matching evidence
exists.

**Two-phase verification** resolves the registration question, where both
naive answers fail. Without the registration change, the new tool is never
registered, so F2P cannot exercise the registered tool surface and
`tests/test_tool_registry.py`'s exact-set assertion fails misleadingly. With
it applied unconditionally, the protected-path gate fails on every job and
its signal is destroyed by alarm fatigue.

```text
Phase 1 — unregistered
  patch applied; registration NOT applied
  F2P at module/domain level; P2P targeted; lint; gates
  ASSERT: protected-path gate PASSES
  -> this phase is the artifact that PROVES worker containment

Phase 2 — registered
  registration patch additionally applied, inside the disposable worktree only
  F2P at registered-tool level; tests/test_tool_registry.py; full suite; gates
  ASSERT: the only protected path in the phase-2 diff is backend/tool_registry.py
  ASSERT: (phase-2 diff minus phase-1 diff) is byte-identical to the
          generated registration patch
```

This is consistent with "the registration patch is never auto-applied": it is
never applied to the real checkout by any code. Applying it inside a
disposable verification worktree is *execution for evidence*, not
installation, and phase 1 exists precisely so worker containment is proven
separately from it.

## 16. FAIL_TO_PASS / PASS_TO_PASS semantics

**F2P — every one of these must hold for every required test:**

1. Base outcome ∈ `{failed, error}`. `passed`, `skipped`, `xfailed`, and
   `xpassed` are all contract violations. Parsed from a machine-readable
   report, never from stdout.
2. Base failure matches the spec's declared `expected_base_failure` (§17).
3. **Empty-patch control run:** apply a zero-byte patch to base and re-run.
   Any test whose outcome differs from the plain base run is
   non-deterministic and fails the job.
4. After-patch outcome = `passed`, in both phases where applicable.
5. **Stability:** F2P runs twice per phase; outcomes must be identical.

**P2P:**

1. Targeted set = tests for every touched module, plus
   `tests/test_tool_registry.py`, plus tests for every module that imports a
   touched module (computed by deterministic AST import graph).
2. **Test-removal detection:** collect pytest node IDs on base and on head.
   Any node ID present on base and absent on head fails the job unless the
   spec names it explicitly. This is the cheapest defence against the most
   direct attack on P2P evidence.
3. Full suite: once, in phase 2, before `ready_for_pr`.
4. Blocking lint (`flake8 --select=E9,F63,F7,F82`) every verify, matching CI.

**The verifier owns test selection and execution. The worker does not decide
what constitutes sufficient verification.**

Mechanism: the verifier loads a MootOS-owned pytest reporter plugin via `-p`,
from a trusted extraction outside the verification worktree, writing
structured per-node outcomes (node id, outcome, exception type, crash
message). This requires no new dependency and cannot be influenced by the
worker. `--junitxml` serves as an independent cross-check.

## 17. Expected-base-failure schema

Declared per required test in the spec, human-approved. A closed vocabulary
of five categories — meaningful failure identity, not brittle snapshot
matching. No stack-trace comparison.

| `category` | Required fields | Verifier asserts |
| --- | --- | --- |
| `tool_not_registered` | `tool_name` | failure is `ToolNotFoundError` (or registry lookup failure) naming exactly that tool |
| `module_missing` | `module` | `ModuleNotFoundError`/`ImportError` naming that module |
| `symbol_missing` | `module`, `symbol` | `ImportError`/`AttributeError` naming that symbol |
| `behavior_assertion` | `failure_id` | `AssertionError` in the named test node; `failure_id` is a stable human-chosen label recorded in the spec and in the test |
| `domain_exception` | `exception_type`, optional `message_contains` | that exception type; substring match only if declared |

A mismatch between the declared category and the observed base failure fails
the job. This distinguishes "correctly fails because the capability is
absent" from "fails because the test is broken", which "pytest exited
nonzero" cannot.

The declaration is written by the human in the approved spec, not by the
worker, and is verified against observed reality — so it is not a
self-classification channel.

## 18. Environmental failure proof rule

**Error-string matching is prohibited.** A worker-authored test can raise
`RuntimeError("database is locked")`; classifying on that string would let
generated code choose how its own failure is treated, which is invariant I11
violated through plumbing.

A failure may be classified `environmental` **only** when:

- **(A)** the same failure signature reproduces on the pinned base under the
  same recorded environment, in the same verifier session; **or**
- **(B)** the failure occurred *before any test executed* and in
  infrastructure demonstrably outside the changed code — specifically:
  interpreter or pytest failed to start, or a collection-time I/O failure
  occurred in a file outside the import closure of the changed files (closure
  computed deterministically by AST).

(B) is deliberately narrow. "Outside the changed path" is not generally
provable in Python because of import side effects, so (B) is restricted to
pre-test failures only. If neither (A) nor (B) is confidently true, the
outcome is a **genuine failure** or `needs_human` — never environmental.

Handling:

- retried **once**;
- if proven environmental, it does **not** consume a fix round;
- if it persists after retry → `needs_human` with reason
  `environmental_unresolved`;
- always recorded in evidence and always visible in the bundle. An
  environmental failure never silently disappears.

This rule exists because Proof #2 produced real SQLite disk-I/O noise that
also reproduced on clean `main` — the exact case (A) is designed to
recognise, and the exact case a string matcher would have handled by accident
rather than by proof.

## 19. Path / symlink normalisation rules

A textual git path is not sufficient. Intake must, for every changed entry:

- use `git diff --raw` (never `--name-only` alone) so mode and type are
  visible;
- **reject** symlinks (mode `120000`), gitlinks/submodules (`160000`), any
  mode change, and any transition to or from executable (`100755`);
- **reject** any blob that fails UTF-8 decode (binary artifacts);
- normalise to NFC, casefold, and compare against the frozen scope — so a
  case-only or Unicode-normalisation variant cannot impersonate an approved
  path;
- reject `..` components, absolute paths, and any path whose `realpath`
  resolves outside the prepared worktree root;
- verify strict confinement of the resolved path under the worktree root
  after symlink resolution;
- reject unexpected nested repositories.

Rationale: within an *allowed* path, converting a regular file into a symlink
passes a name-only scope check while pointing anywhere on the filesystem.
Path allowlisting without type and mode enforcement is not scope control.

## 20. Collection / test hardening

Generated code must not be able to game collection. Controls, in order of
importance:

1. **The test-collection class of the unconditional forbidden list** (§11) —
   `conftest.py`, `pytest.ini`, `pyproject.toml`, `setup.cfg`, `setup.py`,
   `tox.ini`, `*.pth`, `sitecustomize.py`, `usercustomize.py`, any
   `__init__.py`. Forbidden whether or not they currently exist.
2. **MootOS-controlled pytest invocation.** Explicit argv, explicit test
   paths, `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`, `-p no:cacheprovider`,
   MootOS's reporter loaded via `-p` from a trusted extraction. Repository
   default collection behaviour is never relied on when verifying untrusted
   generated code. The exact argv is recorded in evidence.
3. **Skip/xfail rejection** in the F2P contract (§16).
4. **Node-ID removal detection** for P2P (§16).
5. **New-capability tests must exercise the public tool surface or the
   documented domain API**, not private implementation details. Stated as a
   spec requirement and as a review-role responsibility, since it is a
   judgement, not a mechanical check — recorded honestly as such.
6. Modifications to existing test files require explicit
   `allowed_existing_files` approval and heightened review.

## 21. Review artifact binding

`AdvisoryReview` gains three additive, backward-compatible fields:

```text
artifact_tree_sha:   str   = ""    # "" means legacy/unbound
artifact_commit_sha: str   = ""
context_manifest:    tuple = ()    # exact file list the reviewer was given
```

**Semantics, exactly:**

- **`tree_sha` is the primary binding, not `commit_sha`.** A tree SHA is the
  content identity; two identical trees committed at different times produce
  different commit SHAs, so commit SHA alone would report false staleness. The
  commit SHA is recorded for navigability only.
- A review with `artifact_tree_sha == ""` is **unbound**. It remains valid as
  a V0.3E record (the two existing record files are untouched and still
  load), but it **cannot satisfy a V0.4A `reviewed` transition**.
- A review whose `artifact_tree_sha` differs from the job's current verified
  `tree_sha` is **stale** and mechanically fails validation.
- **A model never supplies binding values.** The reviewer supplies only
  `role`, `reviewer`, `summary`, `findings`, and `verdict`. `cli.py`
  re-derives `artifact_tree_sha`, `artifact_commit_sha`, and
  `context_manifest` from the job's own state at attach time.
- `context_manifest` records what the reviewer was actually shown. Without
  it, "review bound to the right artifact but performed against incomplete
  context" is invisible.
- Findings should include `file:line` where practical. A finding that cannot
  be located in the bound artifact is recorded as `unreproduced` and surfaced
  as such rather than acted on.

Reviews remain advisory. `attach_review()` still returns the record state
unchanged (V0.3E, unmodified).

## 22. Fix-loop behaviour

Bounded at `max_fix_rounds = 2`. No override flag, no "one more round", no
autonomous continuation. At the limit: `needs_human`.

A fix brief contains **only** (a) MootOS's own failure evidence,
deterministically truncated, and (b) reviewer findings — both inside an
explicit untrusted-data delimiter. Never the full history, never the
repository, never the previous brief.

**Re-review escalation is deterministic and conservative.** Re-running only
the reviewer that previously complained is rejected: in Proof #2 the
architecture reviewer found nothing, so under that rule it would never see a
fix that introduced new architectural surface.

| Condition on the fix diff | Roles re-run |
| --- | --- |
| any new file added | **all three** |
| `allowed_existing_files` usage grows (a file edited that was not edited in the previous round) | **all three** |
| changes to validation, input handling, error paths, risk metadata, or any new import | correctness + **security** |
| changes to public symbols, module structure, or > 50 changed lines | correctness + **architecture** |
| purely localised change, no new file, no new import, ≤ 20 lines, single file already reviewed | correctness only (targeted re-review permitted) |

When two rows match, take the union. Correctness always re-runs.

## 23. Budgets

Deterministic, checked before dispatch and before each retry. **Escalation
heuristics, not security guarantees** — the frozen path list, the gates, and
human review are the actual authority controls.

| Budget | Default |
| --- | --- |
| `max_fix_rounds` | **2** |
| new files | 4 |
| existing files edited | 2 |
| net added lines | 300 |
| changed lines in any single existing domain file | 150 |

Plus **integrity limits**, which are not size budgets and exist to close a
verified blind spot: `secret_scan._content_violations` skips any file over
200,000 bytes and any file that fails UTF-8 decode, so a line-based budget
alone lets a single enormous line evade content scanning entirely.

| Integrity limit | Default |
| --- | --- |
| bytes per file | 64 KB |
| bytes per diff | 256 KB |
| longest single line | 500 chars |

Exceeding any budget → `needs_human` / split the capability. Code compression
to fit a budget is explicitly not a goal; the integrity limits exist partly to
remove the incentive.

## 24. Registration authority

The worker **never** edits `backend/tool_registry.py`. It is on the
unconditional forbidden list, and a returned diff touching it fails intake
before anything executes.

`registration_patch.py` may prepare a separate deterministic registration
patch **only if all of the following hold**:

- **V1** — the generator is pure and deterministic; no `eval`, no dynamic
  import, no arbitrary module-path strings, no worker-controlled text
  interpolated into the template.
- **V2** — every identifier comes only from the approved spec and matches
  `^[a-z][a-z0-9_]*$` after slugification (module name, function name), with
  `capability_id` and `tool_names` already constrained to dotted lowercase
  identifiers by `spec.py`.
- **V3** — the target module is present in the job's `allowed_new_files`
  **and** present in the verified patch. A registration patch for a module
  that does not exist, or that the human did not approve, is refused.
- **V4** — the generator parses its own output and asserts it contains
  **exactly** one added import and **exactly** one added call inside
  `build_default_registry()`, touching exactly one file. Anything else fails.
- **V5** — the patch header embeds `job_id`, `capability_id`, `base_sha`, and
  `patch_sha256`; the applier refuses a patch whose `job_id` does not match
  the bundle.

The patch is **never auto-applied to the real repository**. A human reviews
and applies it. The V0.3D protected-path gate still fires on it — that is the
intended elevated-review signal, unchanged.

**Fallback, specified rather than implied:** if any precondition cannot be
satisfied, `registration_patch.py` emits `REGISTRATION_MANUAL.md` containing
the exact line for a human to type, and the job proceeds normally. Authority
simplicity is not traded away to save one line of typing.

`registration_patch.py` is itself added to `scripts/gates/policy.py`'s
`DENIED_PATHS` — it is registration authority now and is protected
accordingly.

## 25. Human approval points

Exactly two primary approvals, both of which already exist:

1. **CapabilitySpec approval, before any build.** Because write scope is
   frozen *in the spec*, approving the spec is also approving the literal
   file list, the forbidden set, the required tests, and their expected
   base-failure categories. The human approves a scope they actually read.
2. **PR / merge approval, after evidence and review.** Unchanged from V0.3E.

Two deliberate human terminal actions sit inside those: **dispatch** (running
the CLI command that hands the job to a worker) and **applying the
registration change** while preparing the PR.

No approval ceremony is added for any deterministic step.

## 26. Cost / model-usage rules

**Rule: if a step has a correct answer a script can compute, a model is not
asked.**

Models are used at exactly three points: goal interpretation and spec
drafting assistance (existing), implementation (the worker), and adversarial
review (the critics). Everything else is deterministic — registry truth,
scope validation, path checks, patch hashing, worktree creation, evidence
binding, test selection and execution, F2P/P2P grading, environmental
reproduction, lint, gates, state transitions, registration generation, bundle
assembly, staleness detection.

**No planner role.** The approved `CapabilitySpec` is the plan. Aider's own
published benchmark data shows a same-model architect/editor split buying
~3 points for ~36% more cost and ~43% more latency; MootOS would be paying
that to re-derive a plan a human already approved.

**No router / worker-selection logic.** One worker slot, filled by a human
dispatch decision.

**Context is bounded and deterministic.** The pack is ~5 files selected from
the approved spec: the spec itself, the nearest analogous sibling tool
implementation, its tests, the relevant domain module, and the relevant
tool-system documentation. The worker may request more context manually;
every addition is logged in the job record. **Context expansion never expands
write scope** — the two are separate fields and only the spec grants writes.

Repository content, spec free-text, reviewer findings, and worker reports are
all treated as untrusted with respect to prompt injection, and are delimited
as data wherever they enter a brief.

Expected cost per capability, happy path: ~6 model calls (1 gap analysis,
1 spec drafting, 1 implementation, 3 reviews). Worst case with both fix rounds
and escalated re-review: ~12. Hard-capped by `max_fix_rounds`.

## 27. Explicitly deferred scope

Not in V0.4A: autonomous coding; automatic Codex dispatch; local companion;
device-control bridge; container platform; daemon; queue; scheduler; event
bus; generic workflow engine; generic connector framework; AI Board of
Directors; Dream Catcher; Pattern Scout; proactive Jarvis layer; multi-agent
swarm; planner/implementer chain; best-of-N generation; autonomous deploy;
autonomous merge; autonomous install; a second capability registry; arbitrary
shell or root exposed through MootOS; a second `BuildWorkspace`
implementation; the "worker requests more context" path as an automated
channel.

## 28. Security analysis

Residual risk is stated honestly. Nothing below claims perfect security.

### A. Threat table

| Threat | Control | Residual |
| --- | --- | --- |
| Malicious generated code | frozen scope pre-execution; gates; three reviews; human merge; isolated verifier | **REAL** — the verifier executes it (§13, §14) |
| Import/collection side effects | execution isolation; no way to import Python without executing it | accepted; process-boundary control only |
| **Gates execute subject code** | `risk_metadata` imports `build_default_registry()`; gates run inside verifier isolation, loaded from trusted extraction | documented, not eliminated |
| Secret access | env allowlist; temp `HOME`; no resolvable `.env`; `secret_scan` on the diff | worker can still read repo source it was given |
| Network exfiltration | network disabled where OS supports it; `network_disabled` recorded in fingerprint | **REAL where OS support is absent** — recorded, not hidden |
| Worker modifies forbidden path | unconditional forbidden list checked on returned diff before execution | low |
| Scope/path normalisation bypass | NFC + casefold + realpath + confinement (§19) | low |
| Symlink escape | reject mode `120000` and any type change | low |
| Binary files | reject non-UTF-8 blobs; byte caps | low |
| Executable-bit change | reject any mode change | low |
| Test weakening / deletion | node-ID removal detection; existing-test edits require scope approval | medium — assertion *weakening* within a kept test still needs human eyes |
| Skip / xfail abuse | base outcome must be `failed`/`error` | low |
| Fake F2P (passes on base) | F2P-on-base requirement | low |
| Wrong-reason F2P | declared `expected_base_failure` verified against reality | low |
| Broken / non-deterministic tests | empty-patch control run; double-run stability | low |
| pytest plugin/config manipulation | forbidden-path class + MootOS-controlled argv + autoload disabled | low |
| Stale base / force-push | pinned SHA; reachability re-check at bundle time; final verify against current default-branch SHA | low |
| Stale reviews | `tree_sha` binding; unbound reviews cannot satisfy `reviewed` | low |
| Stale / replayed evidence | full binding set; bundle refuses mismatches | low |
| Corrupted BuildJob JSON | record content hash; CLI refuses on mismatch | integrity vs accident, **not** vs a determined local editor — stated |
| Patch hash mismatch | `patch_sha256` bound into evidence and checked at bundle | low |
| Context-pack / repo prompt injection | untrusted-data delimiters; scope cannot be widened by text | medium — human is the last line |
| Reviewer prompt injection | findings enter fix briefs delimited; scope check catches any resulting violation | medium |
| Worker-report prompt injection | read by no transition; rendered escaped/fenced, below the diff | medium |
| Registration identifier injection | V1–V5 (§24) | low |
| Dependency change | `requirements*.txt` forbidden → `needs_human` | **medium** — misuse of an already-installed package is not prevented; import-graph check is a partial control |
| Gate weakening | `scripts/gates/**` forbidden; CI runs gates from trusted base extraction | low |
| Pipeline self-modification | `scripts/capability_build/**` forbidden to worker **and** in `DENIED_PATHS` | low |
| BuildJob becoming capability authority | no import path to registry; records in `build_jobs/`; containment gate forbids `backend/**` reading them | low |
| **Future accidental runtime exposure** | `builder_containment` gate + CLI refusal + §31 | low — but the highest-lifetime-risk item |
| Runaway fix loop | `max_fix_rounds = 2`, no override; no daemon; dispatch is human | very low |
| Worker crash / never returns | job stays `dispatched`; no timer, no auto-retry; `returned` requires both artifacts | none — silence is a valid permanent state |
| Verifier timeout | wall-clock cap → `needs_human` | low |
| Environment-only failures | §18 proof rule; retry once; never consumes a fix round | low |
| Human cancellation | `cancelled`; worktree disposed; artifacts retained | none |
| Concurrent related jobs | one job per `capability_id`; directory creation is the mutex; one worktree per job | medium — *related but distinct* capabilities can still interact; final verify against current base catches most |

### B. New mechanical gate: `builder_containment`

Added to `scripts/gates/run_gates.py`. Five deterministic checks:

1. No file under `backend/**` imports or references `capability_build`.
2. No file under `.github/workflows/**` references `capability_build`.
3. `scripts/capability_build/cli.py` contains its non-interactive refusal
   guard.
4. No file under `backend/**` reads `build_jobs/` or `capability_specs/`.
5. No `git push`, `git merge`, `gh`, or remote-network call appears anywhere
   under `scripts/capability_build/**`.

This converts the four most important "we promise not to" statements in this
ADR into checks that fail closed in CI.

### C. Honestly stated limits

- **The final-artifact problem.** If a worker temporarily edits a forbidden
  file and perfectly restores it, git cannot prove the temporary edit
  happened. V0.4A inspects the *final artifact*. The human-supervised worker
  remains a trusted-ish local actor under `AGENTS.md` boundaries. True
  behavioural isolation is deferred until automated worker execution, at which
  point it becomes blocking. Verification on a fresh worktree means such an
  edit cannot affect *evidence*, which is the property that matters most —
  but it is not the same as proving it did not occur.
- **Attention risk.** V0.3E's safety came from a human reading a diff. Any
  summary artifact tempts a human to read the summary instead. Mitigation is
  presentational and is a requirement, not a nicety: the bundle leads with the
  raw diff; `evidence.json` presents facts and contains **no verdict field and
  no aggregate pass/fail badge**; the worker report renders escaped, fenced,
  labelled untrusted, and never above the diff.
- Deterministic tests could not have found every semantic defect the Proof #2
  reviewers found. This ADR does not claim otherwise (§32).

## 29. Failure / recovery behaviour

| Situation | Behaviour |
| --- | --- |
| Intake fails | job stays `dispatched`; `intake_failure` event recorded with specific violations; a round-zero correction is returned to the worker and **does not consume a fix round** |
| Verify fails (genuine) | `verified(FAIL)` → `dispatched`, `fix_round += 1` |
| Verify fails (environmental, proven) | retry once; if persists → `needs_human` (`environmental_unresolved`); never consumes a fix round |
| Verifier timeout | `needs_human` |
| Budget exceeded | `needs_human`; recommend splitting the capability |
| Blocking review finding | `reviewed(blocking)` → `dispatched`, `fix_round += 1` |
| Fix-round limit reached | `needs_human`. Always. No override |
| Worker never returns | job stays `dispatched` indefinitely. No timer, no auto-retry |
| Base moved / force-pushed | staleness detected at bundle time; `needs_human`. **Never silently rebase** |
| Corrupted job record | CLI refuses to act; `needs_human` |
| Human cancels | `cancelled`; worktree disposed; all artifacts retained |
| Registration precondition fails | `REGISTRATION_MANUAL.md` emitted; job proceeds |

**The job directory is the audit trail:** brief, context pack, patch plus
hash, worker report, evidence, gate output, reviews with bindings, and full
history with actor, note, and timestamp per event. Ordinary version-controlled
text, reviewed like any other file — the same choice V0.3E made, and the
reason it needed no new storage.

## 30. Consequences / tradeoffs

### Positive

- The repetitive mechanics of the proven pipeline are automated while every
  authority boundary that made V0.3E safe is preserved or strengthened.
- Three invariants move from policy to construction: self-registration
  (forbidden path + template), evidence forgery (MootOS-derived evidence
  only), and runtime exposure (`builder_containment` gate).
- Two previously unnoticed classes are closed: files that do not exist yet but
  would be privileged if created, and type/mode changes within allowed paths.
- The acceptance plan validates against real history rather than synthetic
  fixtures.

### Tradeoffs

- **Dispatch stays manual.** The human opens the worker. This is real
  friction, and it is the price of not holding worker credentials or running
  unattended.
- **The verifier is a genuine residual risk boundary.** The §14 controls raise
  the floor; they are not a container and not a proof.
- **Two-phase verification roughly doubles verification wall-clock time.**
  Accepted: it is the only way to prove worker containment and registered-tool
  behaviour separately.
- **Frozen scope means more spec work up front.** Accepted: it is what makes
  the human's approval mean what it appears to mean.
- **Edit-time behaviour is not observable.** Stated, not solved.
- V0.4A adds a package of comparable size to `scripts/gates/`. That is real
  code with real maintenance cost, justified by removing hand-orchestration
  from every future capability.

## 31. Future extension points

Clean seams, none implemented now:

| Future | Seam it plugs into |
| --- | --- |
| Automatic worker dispatch | `cli.py dispatch` becomes a second dispatch implementation; the file contract is unchanged. **Requires a new ADR and makes container isolation blocking.** |
| Stronger container sandbox | second `BuildWorkspace` implementation + a second verifier isolation mode; the pipeline is unchanged |
| Local MootOS node (V0.4B) | unrelated; usage-gated per ADR-033 |
| Codex worker bridge (V0.4C) | the file contract already describes what a bridge must satisfy |
| Worker selection / routing | a worker registry read at dispatch; roles are already vendor-neutral |
| Pattern Scout, Dream Catcher, AI Board, proactive Jarvis | all become *proposers*: they produce a `CapabilitySpec` proposal and enter this pipeline at spec approval. **None may bypass capability authority.** |
| Read-only build visibility in chat | a future `builds.status` read-only tool reading `build_jobs/` — **requires a new ADR**, because it is the first backend read of builder state |

**Permanent invariant, recorded here so it cannot be lost:**

> Nothing under `scripts/capability_build/` may be registered as a runtime
> tool, imported into the running MootOS service, or invoked from CI, without
> a new architecture decision record. The offline builder must not silently
> evolve into a self-modification API.

Enforced mechanically by `builder_containment` (§28.B) and by the CLI's
non-interactive refusal.

## 32. Acceptance criteria

V0.4A is accepted when **both** levels pass.

**A. Replay real history.** Run the automation against the actual Proof #2
commits (`f483ae1` initial implementation, `089243c` review fixes, `38a53bb`
the Unicode/SQLite NOCASE fix; base = `f483ae1`'s first parent, expected
`9f323a4` — verify at implementation time) and confirm the automation
reproduces the mechanics the humans performed: scope validation, evidence
production, gate behaviour including the intended protected-path failure,
environmental classification of the real SQLite noise, artifact binding,
registration preparation, and bounded fix handling.

**This ADR explicitly does not claim** that deterministic checks would have
discovered the four semantic defects the reviewers found, or the NOCASE
release blocker. They would not have. The replay proves the automation
correctly reproduces the *mechanics*; the advisory review stage remains the
thing that catches semantics, which is precisely why ADR-032's review roles
are retained unchanged.

**B. Proof #3.** After V0.4A is implemented and reviewed, run one genuinely
new small capability end-to-end through the automated pipeline, from approved
spec to PR-ready bundle. The human still selects and launches the worker,
approves the spec, reviews the bundle, merges, deploys, and live-verifies.
**Proof #3 is the acceptance proof for V0.4A.**

## 33. Rejected alternatives, and why

| Alternative | Rejected because |
| --- | --- |
| Runtime builder inside `backend/` (route or registered tool) | Grants the running service build authority; violates I13/I14 structurally; nothing about V0.4A needs it, since a human is already at a terminal |
| MootOS spawns Codex/Claude processes | Requires holding worker credentials and creates an unattended execution path — the exact thing this phase exists to prevent. Deferred to a later phase with its own ADR |
| SWE-ReX / OpenHands-style runtime | Solves massive parallelism and cross-platform deployment. MootOS has neither problem. Adopt the interface shape (`BuildWorkspace`), not the infrastructure |
| Container platform now | The threat that needs addressing now is credential and network exposure during verification, which §14's env allowlist, temp `HOME`, and OS-level confinement address at a fraction of the cost. Containers become blocking when automated dispatch removes the human |
| Deriving write scope after spec approval | The human would approve a scope they never saw. Hidden authority expansion |
| Directory-prefix or glob scope | `tests/**` admits `tests/conftest.py`. Exact paths only |
| Error-string environmental classification | Worker controls the strings; a self-classification channel violating I11 |
| "Fails on base" as the whole F2P contract | Satisfied by a skipped test and by a test that fails for an unrelated reason |
| LLM-declared risk (OpenHands `LLMSecurityAnalyzer`) | Direct violation of I11 |
| Opt-in sandboxing with unisolated default (OpenHands V1 principle 1) | Inverts MootOS's fail-closed posture; if the isolated path is non-default, someone eventually runs the default |
| Auto-commit per edit (Aider) | MootOS needs one reviewable diff against one pinned base; a stream of model-authored commits makes "what was reviewed?" unanswerable |
| Planner/implementer split | Aider's data: ~+3 points for ~+36% cost with the same model, to re-derive an approved plan |
| Best-of-N with a critic selecting | Multiplies cost; produces a selected answer with no human-legible reason; single-attempt on a newer model beat 2+-attempt on an older one in the verified records |
| Re-review only the reviewer who complained | The reviewer who found nothing never sees the fix — exactly the "fix introduces new surface" case |
| BuildJob transitions `CapabilityRecord` | Breaks V0.3E's human-only transition rule, which is load-bearing |
| Merging `returned` and `validated` | Considered; the two carry genuinely different information (artifacts present vs artifacts valid), and separating them keeps the intake-failure path clean without adding a real corruption mode |

## Follow-on direction

See `docs/CAPABILITY_BUILD_AUTOMATION.md` for the six-slice implementation
specification and the final acceptance plan, `docs/CAPABILITY_ARCHITECTURE.md`
§6 (V0.4A) for the phase this carries out, and
`docs/CAPABILITY_BUILD_PIPELINE.md` for the manual pipeline being automated.
