"""GP-A5 -- Representative Evaluation Corpus v1.

16 frozen eval cases spanning all 12 GP-A2 taxonomy classes, bound to
``CORPUS_BASE_SHA`` -- the exact trusted Main commit GP-A was built
against (CB-029 Context Engine v1 merged).

Three cases (``nb_001``, ``bf_001``, ``refactor_001``) are fixture-backed:
each points at a small, disposable, synthetic module under
``tests/fixtures/gpa_eval/<case_id>/`` with a real, independently
runnable acceptance check (see :data:`FIXTURE_BACKED_CASES`), so GP-A6's
offline harness can verify a submission against real, deterministic,
resettable evidence instead of trusting a worker's claim. These fixtures
are wholly synthetic and disposable -- never real production code, never
destructively modified in place (the harness only ever writes into a
temporary copy).

The remaining 13 cases are structural-only: they bind to real,
already-shipped repository paths (as read-only reference points a future
worker would need to reason about) but the offline harness in this phase
cannot independently execute their acceptance criteria -- it can only
check scope/artifact compliance for them. Their ``expected_verification_
commands`` describe what a *human or a future provider-execution phase*
would run; GP-A6 records that limitation as ``verifier_result="unknown"``
rather than trusting a worker's self-report.

Read-only. No network. No model call. Zero authority.
"""

from .gpa_eval_case import create_eval_case, EvalCaseError

CORPUS_VERSION = "gpa-eval-corpus-v1"

# The exact trusted Main commit this corpus is frozen against (CB-029
# Context Engine v1 merged via PR #93). Every case below binds to this
# SHA; GP-A6 rejects evaluating a case against a mismatched architecture
# baseline rather than silently proceeding.
CORPUS_BASE_SHA = "d799c23169332135773e377443779ee9f9544c04"

# Cases with a real, disposable, offline-runnable acceptance fixture.
# ``fixture_dir`` is repo-relative; ``acceptance_file`` is relative to it.
# GP-A6's harness copies ``fixture_dir`` into a temporary directory,
# overlays the submission's claimed file changes, and runs
# ``acceptance_file`` there with a ``python_files`` override (the file is
# deliberately not named ``test_*.py`` so the repository's own pytest run
# never auto-collects it).
FIXTURE_BACKED_CASES = {
    "nb_001": {
        "fixture_dir": "tests/fixtures/gpa_eval/nb_001",
        "acceptance_file": "acceptance.py",
    },
    "bf_001": {
        "fixture_dir": "tests/fixtures/gpa_eval/bf_001",
        "acceptance_file": "acceptance.py",
    },
    "refactor_001": {
        "fixture_dir": "tests/fixtures/gpa_eval/refactor_001",
        "acceptance_file": "acceptance.py",
    },
}


def _case_specs():
    return (
        # -- fixture-backed ------------------------------------------------
        dict(
            eval_case_id="nb_001",
            taxonomy_class_id="narrow_bug_fix",
            goal=(
                "WidgetCounter.add() must never let count exceed capacity. "
                "Extra units should be dropped, and add() should return "
                "the post-clamp count."
            ),
            allowed_scope=("tests/fixtures/gpa_eval/nb_001/widget_counter.py",),
            context_inputs=("tests/fixtures/gpa_eval/nb_001/widget_counter.py",),
            required_artifacts=("unified diff to widget_counter.py",),
            max_wall_clock_seconds=600,
            acceptance_criteria=(
                "WidgetCounter.add() never returns a count greater than "
                "capacity",
                "existing below-capacity behavior is unchanged",
            ),
            expected_verification_commands=(
                "pytest -o python_files=acceptance.py "
                "tests/fixtures/gpa_eval/nb_001/acceptance.py",
            ),
            ground_truth_notes=(
                "Fix: clamp self.count to self.capacity inside add()."
            ),
        ),
        dict(
            eval_case_id="bf_001",
            taxonomy_class_id="bounded_feature_addition",
            goal=(
                "Add a remaining() method to InventoryCounter that returns "
                "capacity minus the current count, without changing add()."
            ),
            allowed_scope=(
                "tests/fixtures/gpa_eval/bf_001/inventory_counter.py",
            ),
            context_inputs=(
                "tests/fixtures/gpa_eval/bf_001/inventory_counter.py",
            ),
            required_artifacts=("unified diff to inventory_counter.py",),
            max_wall_clock_seconds=600,
            acceptance_criteria=(
                "remaining() returns capacity - count",
                "add()'s existing capacity-exceeded ValueError is unchanged",
            ),
            expected_verification_commands=(
                "pytest -o python_files=acceptance.py "
                "tests/fixtures/gpa_eval/bf_001/acceptance.py",
            ),
            ground_truth_notes=(
                "Add: def remaining(self): return self.capacity - self.count"
            ),
        ),
        dict(
            eval_case_id="refactor_001",
            taxonomy_class_id="behavior_preserving_refactor",
            goal=(
                "quote_standard and quote_bulk in pricing.py duplicate "
                "identical discount-then-tax arithmetic. Remove the "
                "duplication without changing either function's return "
                "value for any input."
            ),
            allowed_scope=("tests/fixtures/gpa_eval/refactor_001/pricing.py",),
            context_inputs=("tests/fixtures/gpa_eval/refactor_001/pricing.py",),
            required_artifacts=("unified diff to pricing.py",),
            max_wall_clock_seconds=600,
            acceptance_criteria=(
                "quote_standard and quote_bulk still return identical "
                "values to the frozen 'before' state across the fixed "
                "input table",
                "the duplicated arithmetic block no longer appears twice",
            ),
            expected_verification_commands=(
                "pytest -o python_files=acceptance.py "
                "tests/fixtures/gpa_eval/refactor_001/acceptance.py",
            ),
            ground_truth_notes=(
                "The automated check only proves behavior-equivalence, not "
                "that duplication was removed; that half of acceptance "
                "requires human/verifier review."
            ),
            known_uncertainties=(
                "automated check cannot detect a worker who left the "
                "duplication in place while otherwise passing",
            ),
        ),
        # -- structural-only (real repo paths, no fixture execution) -------
        dict(
            eval_case_id="ta_001",
            taxonomy_class_id="test_addition",
            goal=(
                "backend/continuous_builder/paths.py's "
                "canonicalize_repo_path lacks direct test coverage for "
                "mixed '.' and '..' segments in one path (e.g. "
                "'a/./b/../c'). Add regression tests; do not change "
                "production code."
            ),
            allowed_scope=("tests/test_continuous_builder_paths.py",),
            context_inputs=("backend/continuous_builder/paths.py",),
            required_artifacts=("new or extended pytest test function(s)",),
            acceptance_criteria=(
                "new tests exercise at least one mixed '.'/'..' path",
                "no production file is modified",
            ),
            expected_verification_commands=(
                "pytest tests/test_continuous_builder_paths.py",
            ),
        ),
        dict(
            eval_case_id="ta_002",
            taxonomy_class_id="test_addition",
            goal=(
                "backend/continuous_builder/leases.py's lease-expiry path "
                "is not covered by a test that expires a lease and asserts "
                "the record becomes reclaimable. Add such a test."
            ),
            allowed_scope=("tests/test_continuous_builder_leases.py",),
            context_inputs=("backend/continuous_builder/leases.py",),
            required_artifacts=("new pytest test function(s)",),
            acceptance_criteria=(
                "a new test drives a lease past its expiry and asserts "
                "reclaimability",
            ),
            expected_verification_commands=(
                "pytest tests/test_continuous_builder_leases.py",
            ),
        ),
        dict(
            eval_case_id="docs_001",
            taxonomy_class_id="docs_spec_sync",
            goal=(
                "docs/future/CONTINUOUS_BUILDER_IMPLEMENTATION_PROGRAM.md's "
                "phase table lists CB-029 as 'F2P/P2P, lint, gates, and "
                "environment evidence', but the branch actually merged as "
                "CB-029 is 'Context Engine v1'. Reconcile the table with "
                "what actually shipped."
            ),
            allowed_scope=(
                "docs/future/CONTINUOUS_BUILDER_IMPLEMENTATION_PROGRAM.md",
            ),
            context_inputs=(
                "docs/future/CONTINUOUS_BUILDER_IMPLEMENTATION_PROGRAM.md",
                "docs/future/CONTINUOUS_BUILDER_CB029_CONTEXT_ENGINE_V1.md",
            ),
            required_artifacts=("updated phase table row(s)",),
            acceptance_criteria=(
                "the CB-029 table row matches the phase that actually "
                "merged",
                "no other row's claim is invalidated by the edit",
            ),
            expected_verification_commands=(
                "manual review: table row matches merged PR history",
            ),
            known_uncertainties=(
                "renumbering downstream phases, if any, is out of scope "
                "for this case",
            ),
        ),
        dict(
            eval_case_id="docs_002",
            taxonomy_class_id="docs_spec_sync",
            goal=(
                "ADR-042 describes the worker-containment verifier; confirm "
                "its 'Status' section still matches "
                "backend/continuous_builder/verifier_core.py's current "
                "public surface, and correct it if not."
            ),
            allowed_scope=(
                "docs/future/adrs/"
                "ADR-042-continuous-builder-worker-containment-verifier.md",
            ),
            context_inputs=("backend/continuous_builder/verifier_core.py",),
            required_artifacts=("updated ADR status section, if needed",),
            acceptance_criteria=(
                "ADR-042 status claims are consistent with the current "
                "module",
            ),
            expected_verification_commands=(
                "manual review: ADR claims cross-checked against module",
            ),
        ),
        dict(
            eval_case_id="multi_001",
            taxonomy_class_id="multi_file_feature",
            goal=(
                "Add an optional lease-renewal audit note: when "
                "leases.py renews a lease, record a short reason code "
                "that queue_store.py can surface on the queue projection."
            ),
            allowed_scope=(
                "backend/continuous_builder/leases.py",
                "backend/continuous_builder/queue_store.py",
                "tests/test_continuous_builder_leases.py",
                "tests/test_continuous_builder_queue_store.py",
            ),
            context_inputs=(
                "backend/continuous_builder/leases.py",
                "backend/continuous_builder/queue_store.py",
                "backend/continuous_builder/queue_projection.py",
            ),
            required_artifacts=("unified diff", "new/updated tests"),
            acceptance_criteria=(
                "a renewed lease's reason code round-trips through to the "
                "queue projection",
                "existing lease/queue tests still pass",
            ),
            expected_verification_commands=(
                "pytest tests/test_continuous_builder_leases.py "
                "tests/test_continuous_builder_queue_store.py",
            ),
            known_uncertainties=(
                "exact reason-code vocabulary is left to the worker's "
                "judgement",
            ),
        ),
        dict(
            eval_case_id="sec_001",
            taxonomy_class_id="security_sensitive_change",
            goal=(
                "text_safety.py's secret-pattern detection should also "
                "flag AWS-style access key IDs (AKIA-prefixed), not just "
                "the patterns it currently recognizes."
            ),
            allowed_scope=(
                "backend/continuous_builder/text_safety.py",
                "tests/test_continuous_builder_text_safety.py",
            ),
            context_inputs=("backend/continuous_builder/text_safety.py",),
            required_artifacts=("unified diff", "new tests"),
            acceptance_criteria=(
                "an AKIA-prefixed string is flagged as a probable secret",
                "no existing accepted-safe string starts being flagged "
                "(no regression in false-positive rate on existing tests)",
            ),
            expected_verification_commands=(
                "pytest tests/test_continuous_builder_text_safety.py "
                "(worker-authored; file does not exist yet)",
            ),
            known_uncertainties=(
                "exact detection pattern/threshold is a judgement call "
                "reviewed by a human, not purely mechanical",
            ),
        ),
        dict(
            eval_case_id="tcb_001",
            taxonomy_class_id="tcb_adjacent_change",
            goal=(
                "worker_planning.py should reject a plan whose declared "
                "scope includes any path the canonical TCB registry "
                "protects, citing the offending path in the rejection "
                "reason."
            ),
            allowed_scope=("backend/continuous_builder/worker_planning.py",),
            forbidden_scope=(
                "backend/continuous_builder/trusted_policy.py",
                "backend/continuous_builder/trusted_policy_enforcement.py",
            ),
            context_inputs=(
                "backend/continuous_builder/worker_planning.py",
                "backend/continuous_builder/trusted_policy.py",
            ),
            required_artifacts=("unified diff",),
            acceptance_criteria=(
                "a plan naming a TCB-protected path is rejected with a "
                "reason that names the path",
                "trusted_policy.py itself is not modified",
            ),
            expected_verification_commands=(
                "pytest tests/test_continuous_builder_worker_planning.py",
            ),
            known_uncertainties=(
                "whether this belongs in worker_planning.py versus a "
                "dedicated policy-check module is a design judgement",
            ),
        ),
        dict(
            eval_case_id="migration_001",
            taxonomy_class_id="migration_schema_change",
            goal=(
                "backend/migrations.py needs a new, additive migration "
                "step; it must be a no-op on a database that already has "
                "the target column, and must not alter or drop any "
                "existing column."
            ),
            allowed_scope=("backend/migrations.py",),
            context_inputs=("backend/migrations.py",),
            required_artifacts=("unified diff", "migration test"),
            acceptance_criteria=(
                "running the migration twice in a row produces no error "
                "and no duplicate column",
                "no existing column is dropped or renamed",
            ),
            expected_verification_commands=(
                "pytest tests/test_continuous_builder_migration_"
                "constraints.py",
            ),
            known_uncertainties=(
                "irreversible in place on a real database; must be tested "
                "against a disposable copy, never a live one",
            ),
        ),
        dict(
            eval_case_id="dep_001",
            taxonomy_class_id="dependency_api_boundary_change",
            goal=(
                "worker_provider.py's public provider-selection function "
                "signature is called from more than one site; add a new "
                "optional parameter without breaking any existing caller."
            ),
            allowed_scope=("backend/continuous_builder/worker_provider.py",),
            context_inputs=("backend/continuous_builder/worker_provider.py",),
            required_artifacts=("unified diff",),
            acceptance_criteria=(
                "every existing caller continues to work unmodified",
                "the new parameter has a backward-compatible default",
            ),
            expected_verification_commands=(
                "pytest tests/test_continuous_builder_worker_provider.py",
            ),
            known_uncertainties=(
                "full caller enumeration requires a repo-wide reference "
                "search the worker must perform itself",
            ),
        ),
        dict(
            eval_case_id="ctx_001",
            taxonomy_class_id="context_heavy_navigation_task",
            goal=(
                "Explain, referencing the actual call path, how a "
                "blueprint approved by chief_builder.py eventually reaches "
                "check_runner.py for verification. Produce a short written "
                "trace, not a code change."
            ),
            allowed_scope=("docs/future/CB_CHIEF_BUILDER_TRACE_NOTE.md",),
            context_inputs=(
                "backend/continuous_builder/chief_builder.py",
                "backend/continuous_builder/check_runner.py",
                "backend/continuous_builder/worker_authorization.py",
            ),
            required_artifacts=("written trace document",),
            acceptance_criteria=(
                "every hop named in the trace corresponds to a real call "
                "in the current code",
                "no hop is invented or guessed",
            ),
            expected_verification_commands=(
                "manual review: each cited call site actually exists",
            ),
            known_uncertainties=(
                "correctness of the trace can only be checked by a human "
                "or a future automated call-graph tool; this phase has "
                "neither wired in",
            ),
        ),
        dict(
            eval_case_id="verifier_001",
            taxonomy_class_id="verifier_policy_sensitive_task",
            goal=(
                "candidate_verifier.py should reject a candidate whose "
                "structural verification receipt claims success but whose "
                "recorded tree digest does not match the frozen base "
                "tree's digest."
            ),
            allowed_scope=("backend/continuous_builder/candidate_verifier.py",),
            forbidden_scope=(
                "backend/continuous_builder/verifier_core.py",
                "backend/continuous_builder/adversarial_verifier.py",
            ),
            context_inputs=(
                "backend/continuous_builder/candidate_verifier.py",
                "backend/continuous_builder/verifier_core.py",
            ),
            required_artifacts=("unified diff",),
            acceptance_criteria=(
                "a digest-mismatched, claimed-success candidate is "
                "rejected",
                "a digest-matched, claimed-success candidate is unaffected",
            ),
            expected_verification_commands=(
                "pytest tests/test_continuous_builder_candidate_verifier.py "
                "(worker-authored; file does not exist yet)",
            ),
        ),
        dict(
            eval_case_id="nb_002",
            taxonomy_class_id="narrow_bug_fix",
            goal=(
                "worker_provider.py's retry-count guard should compare "
                "with '>=' against its documented maximum, not '>' -- as "
                "written it permits one extra retry beyond the documented "
                "limit."
            ),
            allowed_scope=("backend/continuous_builder/worker_provider.py",),
            context_inputs=("backend/continuous_builder/worker_provider.py",),
            required_artifacts=("unified diff",),
            acceptance_criteria=(
                "the documented maximum retry count is never exceeded",
            ),
            expected_verification_commands=(
                "pytest tests/test_continuous_builder_worker_provider.py",
            ),
        ),
        dict(
            eval_case_id="bf_002",
            taxonomy_class_id="bounded_feature_addition",
            goal=(
                "Add a read-only helper to queue_projection.py that "
                "returns the count of queue entries currently in a given "
                "state, without changing any existing projection "
                "behavior."
            ),
            allowed_scope=("backend/continuous_builder/queue_projection.py",),
            context_inputs=("backend/continuous_builder/queue_projection.py",),
            required_artifacts=("unified diff", "new test"),
            acceptance_criteria=(
                "the new helper returns an accurate count for at least "
                "one non-trivial fixture",
                "no existing projection test's behavior changes",
            ),
            expected_verification_commands=(
                "pytest tests/test_continuous_builder_queue_projection.py",
            ),
        ),
    )


def create_gpa_eval_corpus_v1():
    """Build the 16 frozen GP-A5 eval cases. Deterministic; no I/O."""
    cases = []
    for spec in _case_specs():
        spec = dict(spec)
        spec.setdefault("base_sha", CORPUS_BASE_SHA)
        cases.append(create_eval_case(**spec))
    return tuple(sorted(cases, key=lambda item: item.eval_case_id))


def eval_case_by_id(cases, eval_case_id):
    for case in cases:
        if case.eval_case_id == eval_case_id:
            return case
    return None


def corpus_class_distribution(cases):
    """Return {taxonomy_class_id: count} across ``cases``."""
    counts = {}
    for case in cases:
        counts[case.taxonomy_class_id] = counts.get(case.taxonomy_class_id, 0) + 1
    return counts


def eval_corpus_is_descriptive_only():
    """TRUST REVIEW helper: True -- the corpus grants no capability."""
    return True


__all__ = [
    "CORPUS_VERSION",
    "CORPUS_BASE_SHA",
    "FIXTURE_BACKED_CASES",
    "EvalCaseError",
    "create_gpa_eval_corpus_v1",
    "eval_case_by_id",
    "corpus_class_distribution",
    "eval_corpus_is_descriptive_only",
]
