# MootOS Manual Capability-Build Pipeline (V0.3E)

**Status:** Pipeline and proof #1 (`tasks.status_summary`) implemented and
merged. **Proof #2 (`projects.overview`) implemented on branch
`claude/v0.3e-proof-2-capability`, pending merge** — see §12. With both
proofs complete, ADR-034's two-pass prerequisite is satisfied; **V0.4A
remains unimplemented and still requires its own design/review step**
(§11). See `docs/CAPABILITY_ARCHITECTURE.md` §6 (V0.3E) and ADR-034 for
the decision this document carries out.
**Applies to:** `scripts/capability_pipeline/`, `capability_specs/`,
`backend/tools_task_summary.py` (proof #1), and
`backend/project_insight.py` / `backend/tools_project_insight.py`
(proof #2).

This document is the literal, step-by-step process a human (or Claude,
working manually, under human direction) follows to add exactly one new
capability to MootOS. It exists so a future worker can follow the process
without guessing what "human approval to build" or "isolated branch"
concretely mean in this repository.

## 1. What this phase is, and is not

**Is:** tooling and process for a *human* to manually walk one capability
from a stated goal to a merged, installed tool -- proving the pipeline
described in `docs/CAPABILITY_ARCHITECTURE.md` §6 (V0.3E) actually works,
end to end, on a real capability.

**Is not:** an autonomous capability builder. Nothing in this phase gives
MootOS, a model, or any automated process the authority to create a
branch, write a commit, open a PR, merge, register a tool, or deploy.
Every one of those actions in this phase's proof run was performed by a
human decision (even when Claude typed the code) -- see §8.

## 2. Step 1: start from a goal and a Gap Report

The pipeline starts with a natural-language goal and the real, unmodified
V0.3B `backend.gap_reasoning.analyze_goal()` -- not a hand-written
justification invented after the fact.

For the proof capability, the goal was:

> "How many open Tasks do I have right now, broken down by status?"

Run against the registry **as it existed before this capability was
added** (V0.2A reference tools + V0.3C self-inspection, no
`tasks.status_summary`), `analyze_goal()` classified this `capability_gap`
-- no installed capability answers it in one call; the model would have
to call `tasks.list` and count rows itself, which is both more
tool-call/token cost and not a deterministic, auditable count.

The exact script that produced this, reproducibly, is
`scripts/capability_pipeline/build_gap_report_example.py`; its output is
`capability_specs/tasks_status_summary.gap_report.json`. A Gap Report
stays exactly what ADR-030 says it is: advisory and auditable. It never
executes anything and never installs anything -- it is read here purely
as the human's justification for drafting a spec.

## 3. Step 2: convert the gap into a validated capability spec

A `CapabilitySpec` (`scripts/capability_pipeline/spec.py`) is the
smallest useful machine-readable, human-reviewable description of one
proposed capability. It is a flat dataclass, not a DSL, with these
fields:

| Field | Meaning |
| --- | --- |
| `capability_id` | Dotted semantic id, e.g. `tasks.status_insight` (§3 of `docs/CAPABILITY_ARCHITECTURE.md`) |
| `human_readable_goal` | What a person asked for, in plain language |
| `tool_names` | The real, registered tool name(s) this capability will be backed by |
| `resource_or_connector` | What resource is acted on and which connector (if any) is involved |
| `input_contract` | A JSON-Schema-lite object shape, matching `backend/tool_validation.py`'s supported subset |
| `output_contract` | Field name -> one-line description of what the tool returns |
| `side_effects` | Free-text description |
| `has_side_effects` | Explicit boolean -- cross-checked against `risk` (see below) |
| `idempotent` | Explicit boolean |
| `risk` | Must be one of `backend.tool_types.VALID_RISK_LEVELS` |
| `data_exposure` | Must be one of `backend.runs.VALID_DATA_EXPOSURES` |
| `dependencies` | Other tool/capability ids this relies on (may be empty) |
| `limitations` | Required, non-empty -- every real tool has at least one |
| `required_tests` | Non-empty list of test scenarios that must exist before this ships |
| `protected_core_impact` | Paths this change is expected to touch that are protected-core (empty if none) |
| `requires_human_registration_review` | Must be `True` whenever `protected_core_impact` is non-empty (see §6) |
| `registration_requirement` | Free text describing exactly how this gets wired into the registry |
| `rollback_notes` | Free text describing how to remove this capability |

**Validation is fail-closed and cannot be bypassed by construction
choice.** `CapabilitySpec.__post_init__` enforces every rule itself (not
only the dict-loading helper `spec_from_dict`), so constructing the
dataclass directly with bad data still raises `CapabilitySpecError` --
mirroring `backend.tool_types.ToolDefinition`'s own pattern deliberately.
Key rules:

- Any field not in the schema is rejected (`spec_from_dict`,
  `additionalProperties: False` semantics).
- `risk`/`data_exposure` must be real, valid values -- not free text.
- **A `read_only`-classified spec cannot declare `has_side_effects=True`.**
  This is the deterministic check that fulfils "a write-capable spec
  cannot be mislabeled read-only" -- a cross-field rule, not text
  sniffing over the free-text `side_effects` description.
- `protected_core_impact` naming a path without
  `requires_human_registration_review=True` is rejected -- a
  protected-core touch can never be declared away.
- `capability_id`/`tool_names` must be dotted, lowercase identifiers.

The proof capability's spec is embedded in
`capability_specs/tasks_status_summary.json` (see §5). Validate any spec
file with:

```sh
python -m scripts.capability_pipeline.spec capability_specs/tasks_status_summary.json
```

**A human reviews and approves the spec before any implementation
begins.** This is a real step, not a formality -- the spec is where a
reviewer catches a wrong risk classification, a missing rollback plan, or
an undeclared protected-core touch before any code exists.

## 4. Step 3: the lifecycle model

`scripts/capability_pipeline/lifecycle.py` implements the minimum state
model needed to prove this pipeline by hand -- **not** the larger
`proposed -> ... -> installed -> deprecated -> rolled-back` machine
ADR-034 explicitly defers to V0.4A (automated builder). This is smaller,
on purpose:

```text
proposed -> specified -> implemented -> tested -> reviewed -> ready_for_pr -> merged
```

- Every transition is **one step forward only** -- `transition()` rejects
  skipping ahead (e.g. `proposed` straight to `ready_for_pr`), moving
  backward, or repeating a state.
- Every transition requires an explicit, non-empty `actor` and `note` --
  there is no anonymous or automatic transition anywhere in this module.
- `CapabilityRecord` is immutable; every operation returns a new record.
- **Nothing in this module imports, references, or can call
  `backend/tool_registry.py`.** A record reaching `state="merged"`
  records that a human performed a real merge elsewhere (an ordinary Git
  action) -- it does not, and structurally cannot, cause one. See §7 for
  the tests proving this at every state.

A record is a plain JSON file under `capability_specs/` -- ordinary,
version-controlled text, reviewed like any other source file. No database
table, migration, or new storage was introduced for this (per this
phase's explicit "do not introduce storage unless genuinely necessary").

## 5. Step 4-8: isolated branch, implementation, gates, review

The proof capability's actual build, in order:

1. **Isolated branch.** `claude/v0.3e-manual-capability-pipeline`, created
   fresh from `origin/main` (which already includes merged V0.3A-D). No
   other agent edited this working tree concurrently (§8).
2. **Implement only the approved files.** Exactly what the spec named:
   - `backend/tasks.py`: added `count_tasks_by_status()` -- a pure
     aggregate query, additive, no schema change.
   - `backend/tools_task_summary.py` (new): the `tasks.status_summary`
     `ToolDefinition` and `register_v03e_tools()`.
   - `backend/tool_registry.py`: **one line** added to
     `build_default_registry()` calling `register_v03e_tools(registry)`.
     This is the only protected-core touch this capability makes -- see
     §6.
3. **Run V0.3D gates.** See §6.
4. **Run tests/lint.** `tests/test_tools_task_summary.py` (13 tests) plus
   the updated exact-set assertion in `tests/test_tool_registry.py`; full
   existing suite re-run with zero regressions; blocking flake8 clean.
5. **Run advisory reviews, three distinct roles.** See §7.

The record file (`capability_specs/tasks_status_summary.json`) was
advanced through `proposed -> specified -> implemented -> tested ->
reviewed -> ready_for_pr` as each of these steps actually completed, via
`scripts/capability_pipeline/build_proof_record.py` (kept in the
repository so this sequence is reproducible and auditable, not a JSON
file with no visible origin).

**This session did not open a PR and did not merge**, per this phase's
explicit instructions -- so the record correctly stops at `ready_for_pr`,
never `merged`. The final transition is a human action, taken outside
this tooling, only after a real PR is opened and a human actually merges
it.

## 6. Protected-core interaction and the registration approach

`backend/tool_registry.py` is intentionally protected (ADR-031,
`scripts/gates/policy.py`). Adding `register_v03e_tools(registry)` to
`build_default_registry()` touches it, and this diff **correctly fails**
V0.3D's protected-path gate:

```text
protected-path gate: FAIL (1 protected path(s) touched)
  - backend/tool_registry.py
```

This is not a bug to route around. It is the exact mechanical signal
ADR-031 exists to produce: a protected-core change requires explicit,
elevated human review before merge -- automated or not. V0.3E's answer to
"how does a manually-approved capability actually get registered" is:

- **The explicit, human-reviewed registration change is the only path.**
  A human (here, a human directing Claude's manual edit) writes the exact
  one-line addition, by hand, in the same explicit-reference style every
  earlier registration call already uses (`register_reference_tools`,
  `register_v03c_tools`). There is no discovery, no dynamic import, no
  second registry.
- **The protected-path failure is the review signal, not an obstacle to
  bypass.** A human reading the failing gate output knows exactly which
  file changed and why (the spec's `registration_requirement` field
  explains it in advance).
- **No automatic bypass exists or was added.** `scripts/gates/policy.py`
  was not edited by this phase. `backend/tool_registry.py` remains in
  `DENIED_PATHS`, unchanged.

**No narrower registration extension point was designed or built in this
phase.** The instructions for this phase were explicit: if a narrow
registration extension point seems required, stop and document the
design first, rather than implement one. One real registration edit
(a single added line, following the existing pattern exactly) did not
surface a need for one -- the existing explicit-reference pattern already
scales to "one more line per capability" without friction. Whether a
narrower extension point becomes worth building is a question for V0.4A
(automated builder), once a second and third manual proof run exist to
generalize from, not something V0.3E needed to invent.

## 7. Advisory review, three distinct roles

Every review is advisory only, per ADR-032 -- see
`scripts/capability_pipeline/review.py`. Three roles, always distinct:

1. **Correctness + test quality** (`ROLE_CORRECTNESS`) -- is the
   implementation actually correct, and do the tests actually cover the
   required behavior?
2. **Security + permissions** (`ROLE_SECURITY`) -- risk classification,
   data exposure, injection surface, protected-core impact.
3. **Architecture + duplication** (`ROLE_ARCHITECTURE`) -- does this fit
   the Capability/Tool model in `docs/CAPABILITY_ARCHITECTURE.md` §3, and
   does it duplicate existing logic?

An `AdvisoryReview` record has a `role`, `reviewer` (free-text identity --
this module does not care *who* performs a role, only that the three
roles stay distinct, per ADR-032's "distinct roles, never one voice reused
three times"), `summary`, `findings`, and a `verdict` from
`{no_concerns, concerns_noted, blocking_concern}` -- deliberately **not**
`approved`/`rejected`, because a review is not a decision.

**Structurally, not just by convention, a review cannot install
anything.** `attach_review()` appends a review to a `CapabilityRecord` and
returns the state completely unchanged --
`tests/test_capability_lifecycle.py` proves this directly, including for
a maximally positive review (`no_concerns` from all three roles) attached
at `ready_for_pr`. Moving the record forward after reading the reviews is
still a separate, explicit `transition()` call a human makes.

For the proof capability, all three roles were exercised (recorded in
`capability_specs/tasks_status_summary.json`); no blocking concerns were
raised.

## 8. What no autonomous authority exists here

Explicitly not added, anywhere in this phase:

- a model-generated code execution pipeline
- automatic branch creation by MootOS
- automatic commits
- automatic PR creation
- automatic merge
- automatic registration
- automatic deployment
- a Codex bridge (`AGENTS.md`'s existing manual boundaries are untouched)
- a local companion

Every branch, commit, gate run, and review in this phase's proof run was
a human-directed action (a human told Claude what to build and reviewed
the result; Claude did not decide on its own to build anything or merge
anything). MootOS itself has no code path anywhere that creates a branch,
opens a PR, or registers a tool on its own initiative.

## 9. Rollback / removal path

The smallest rollback for `tasks.status_summary`, and the pattern for any
future capability built this way:

1. **Revert the merge commit** (or the specific commits that added
   `backend/tools_task_summary.py` and the `register_v03e_tools()` call
   in `backend/tool_registry.py`) on `main`, through the normal Git/PR
   process -- the same human-controlled path that added it.
2. **No migration to reverse.** This capability added no schema, so
   reverting the code is the entire rollback -- no data-cleanup step
   exists.
3. **No persisted state is specific to this tool.** It only reads
   existing Task rows and writes nothing, so there is no capability-owned
   data left behind after the code is gone.
4. **The capability disappears from the live registry/catalog
   automatically**, the moment the reverted code is deployed --
   `self.state`, the V0.3A generated catalog, and the generated
   manifest are all derived from the live `ToolRegistry` on every call,
   never cached or hand-maintained (ADR-029). There is no second place
   that would need a separate edit to stop advertising it.

`tests/test_capability_lifecycle.py` and
`tests/test_tools_task_summary.py` prove the structural half of this
concretely: a registry built without calling `register_v03e_tools`
(exactly what a revert produces) never contains `tasks.status_summary`,
regardless of what any capability-spec or lifecycle-record file still
says.

## 10. Why `tasks.status_summary` was chosen as the proof capability

`docs/CAPABILITY_ARCHITECTURE.md`'s original ADR-034 recommendation --
live web/current-information search -- was **already implemented and
merged as part of V0.3C** (`web.search`) before this phase began, so it
could no longer serve as this phase's *first* proof run. A different
low-risk capability was needed, and `tasks.status_summary` was chosen
because:

- **Read-only, no configuration gate.** `RISK_READ_ONLY`,
  `DATA_EXPOSURE_LOCAL` -- no external service, no credential, no
  "unconfigured" state to reason about.
- **No filesystem, shell, email/calendar, Dropbox, local-node, Codex, or
  authenticated third-party access** -- every explicitly excluded
  category in this phase's instructions is untouched.
- **A real, demonstrable gap**, not a toy example: running the actual
  V0.3B `analyze_goal()` against the pre-V0.3E registry genuinely
  classified this `capability_gap` (§2) -- the pipeline was proven
  against a real gap, not one invented to fit the tooling.
- **Backed entirely by existing, already-tested machinery.** The new
  aggregate query reuses the exact same `database_connection()` helper
  and table every other `backend/tasks.py` function already uses -- no
  new subsystem, no new dependency.
- **Minimal, well-scoped protected-core touch.** The only protected-path
  edit is the one line every prior tool registration has needed, which
  makes it a clean, honest first test of the "protected-path failure as
  elevated-review signal" flow (§6) without any unrelated protected-core
  risk mixed in.

## 11. Two-pass requirement (ADR-034)

**One proof capability is not sufficient to automate any part of this
pipeline.** ADR-034 requires at least two real capabilities to pass this
pipeline before automation begins. `tasks.status_summary` was the first
(§10); `projects.overview` is the second (§12).

**Both proofs are now complete**, which satisfies ADR-034's two-pass
prerequisite. That does **not** mean V0.4A has started or is approved:
V0.4A remains unimplemented and still requires its own design and review
step before any automation is built. Satisfying a prerequisite removes a
blocker; it does not authorize the next phase.

## 12. Proof #2 — `projects.overview`

**Chosen after inspecting the live registry and the actual domain code.**
Five candidates were considered:

| Candidate | Capability / tool | Why not chosen |
| --- | --- | --- |
| Memory statistics | `memory.insight` / `memory.stats` | Genuine gap, but a counts-by-status shape — nearly the same exercise as proof #1, so it would prove little about generalization |
| Run/audit summary | `self.activity` / `self.activity_summary` | Genuine gap and useful, but arguably inside the existing `self.inspect` capability, risking a manufactured-gap objection |
| Conversation search/listing | `conversations.*` | Rejected on data sensitivity: message content is the most sensitive local data, and `memory.search` already covers cross-chat recall by design |
| Single-memory history | `memory.history` | Rejected: needs a `memory_id` the model would never have, so the input surface is unusable in practice |
| **Per-project activity rollup** | **`projects.insight` / `projects.overview`** | **Chosen** |

`projects.overview` is the stronger proof #2 because:

- **It is a different resource and a genuinely different query shape.**
  Proof #1 was a single-table count grouped by one column. This is a
  cross-table rollup joining projects, memories, tasks, and conversations
  into per-entity rows — so it actually tests whether the pipeline
  generalizes rather than repeating the same exercise.
- **The gap is verifiable rather than asserted.** Running the real V0.3B
  `analyze_goal()` against the pre-proof-#2 registry (exactly what is
  merged on `main`) classified the goal `capability_gap`. The report
  deliberately proposes *two* capabilities, and the deterministic
  resolver independently confirms `projects.view` **is** installed while
  `projects.insight` is **not** — so the gap is a fact about the registry,
  not an artifact of inventing a new dotted string.
- **It has a real input surface worth attacking.** An optional project
  name that must be matched case-insensitively against a
  `UNIQUE COLLATE NOCASE` column, which gives the adversarial tests
  something substantive to probe.
- **Same low-risk profile as proof #1:** read-only, local, no credential,
  no migration, no configuration gate, and none of the excluded
  categories (filesystem, shell, email/calendar, Dropbox, paid APIs,
  local node, Codex, external writes).

## 13. What proof #2 changed about the process

Proof #2 was run against the *unchanged* V0.3E pipeline — no redesign was
needed, which is itself part of what the second pass was meant to test.
Two things did change, both in process hygiene rather than tooling:

**Genuinely independent reviewers.** In proof #1 one model wrote all
three advisory reviews in sequence. For proof #2 each role ran as a
**separate model instance with its own independent context and read-only
tools**, all three reviewing the same immutable commit (`f483ae1`):

| Role | Reviewer | Verdict |
| --- | --- | --- |
| Correctness + test quality | Claude Opus 5 | `concerns_noted` |
| Security + permissions | Claude Sonnet 5 | `concerns_noted` |
| Architecture + duplication | Claude Haiku 4.5 | `no_concerns` |

This is "independent" in a specific and limited sense worth stating
plainly: separate instances, separate contexts, no shared scratchpad, and
no ability to edit — but all three are Claude-family models orchestrated
by the same session. It is not third-party or human review, and it should
not be described as such.

**The review stage actually caught things.** This is the important
result. Two of three reviewers returned `concerns_noted`, and the
concerns were real, reproducible defects — not style opinions:

- the case-insensitive merge **overwrote instead of accumulating**, so
  differently-cased project rows silently evicted each other's counts;
- rows naming a project absent from the `projects` table **vanished from
  both** the per-project entries and `unassigned`, the exact undercount
  `unassigned` exists to prevent;
- `last_activity_at` **did not move when a Task was completed**, despite
  the tool description promising "when it was last touched";
- `last_activity_at` could move **backward** when the newest memory was
  archived;
- the module docstring's stated justification for string-comparing
  timestamps was **factually wrong** (the conclusion held for a different
  reason);
- the diff introduced a **CI regression** that only fails under a
  supported-but-not-default configuration;
- the rollup had **no result bound**, unlike every sibling tool.

All were fixed with regression tests before the `reviewed` transition;
one finding (non-transactional multi-statement reads) was accepted and
documented rather than fixed. **Proof #1's reviews found nothing.**
Whether that is because proof #1 was genuinely cleaner or because one
model reviewing its own work three times is weaker review is not settled
by a single comparison — but it is a strong argument for keeping
independent reviewers in the pipeline, and for treating a
`no_concerns` sweep with suspicion rather than satisfaction.

**Consequence for V0.4A:** the "fixes" stage between review and PR is not
optional decoration. Any future automation of this pipeline must preserve
a real fix-and-re-verify loop, because on the second proof the first
implementation was genuinely wrong in four ways that all tests passed
through.
