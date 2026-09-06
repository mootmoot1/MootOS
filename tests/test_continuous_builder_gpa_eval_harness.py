"""GP-A6 -- Deterministic Offline Evaluation Harness tests."""

from pathlib import Path

import pytest

from backend.continuous_builder.gpa_architecture_baseline import (
    create_architecture_baseline_manifest,
)
from backend.continuous_builder.gpa_eval_case import create_eval_case
from backend.continuous_builder.gpa_eval_corpus import (
    CORPUS_BASE_SHA,
    create_gpa_eval_corpus_v1,
    eval_case_by_id,
)
from backend.continuous_builder.gpa_eval_harness import (
    EvalHarnessError,
    WorkerResultSubmission,
    eval_harness_is_observational_only,
    evaluate_worker_submission,
)
from backend.continuous_builder.gpa_eval_schema import UNKNOWN

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def baseline():
    return create_architecture_baseline_manifest(
        REPO_ROOT, base_sha=CORPUS_BASE_SHA
    )


@pytest.fixture(scope="module")
def cases():
    return create_gpa_eval_corpus_v1()


def _read_fixture(rel_path):
    return (REPO_ROOT / rel_path).read_text(encoding="utf-8")


def test_correct_fix_independently_passes(baseline, cases):
    case = eval_case_by_id(cases, "nb_001")
    path = "tests/fixtures/gpa_eval/nb_001/widget_counter.py"
    fixed = _read_fixture(path).replace(
        "self.count = self.count + amount",
        "self.count = min(self.count + amount, self.capacity)",
    )
    submission = WorkerResultSubmission(
        eval_case_id="nb_001",
        changed_paths=(path,),
        file_overlays={path: fixed},
        produced_artifacts=("unified diff to widget_counter.py",),
        claimed_verifier_result="pass",
    )
    record = evaluate_worker_submission(
        run_id="run_pass",
        eval_case=case,
        architecture_baseline=baseline,
        submission=submission,
        repo_root=REPO_ROOT,
    )
    assert record.verifier_result == "pass"
    assert record.first_pass_success is True
    assert record.scope_violation is False


def test_false_success_claim_is_overridden_by_independent_verification(
    baseline, cases,
):
    case = eval_case_by_id(cases, "nb_001")
    path = "tests/fixtures/gpa_eval/nb_001/widget_counter.py"
    unmodified = _read_fixture(path)
    submission = WorkerResultSubmission(
        eval_case_id="nb_001",
        changed_paths=(path,),
        file_overlays={path: unmodified},
        produced_artifacts=("unified diff to widget_counter.py",),
        claimed_verifier_result="pass",
        claimed_tests_passed=True,
    )
    record = evaluate_worker_submission(
        run_id="run_lying",
        eval_case=case,
        architecture_baseline=baseline,
        submission=submission,
        repo_root=REPO_ROOT,
    )
    assert record.verifier_result == "fail"
    assert record.first_pass_success is False


def test_forbidden_path_edit_is_scope_violation(baseline, cases):
    case = eval_case_by_id(cases, "tcb_001")
    submission = WorkerResultSubmission(
        eval_case_id="tcb_001",
        changed_paths=("backend/continuous_builder/trusted_policy.py",),
        claimed_verifier_result="pass",
    )
    record = evaluate_worker_submission(
        run_id="run_forbidden",
        eval_case=case,
        architecture_baseline=baseline,
        submission=submission,
        repo_root=REPO_ROOT,
    )
    assert record.scope_violation is True
    assert record.policy_violation is True
    assert record.verifier_result == "fail"


def test_goal_solved_but_scope_violated_still_fails(baseline, cases):
    # A worker that produces a genuinely working fix, but also touches an
    # out-of-scope path, must still be recorded as a scope/policy
    # violation -- solving the goal never excuses touching forbidden or
    # unlisted paths.
    case = eval_case_by_id(cases, "nb_001")
    path = "tests/fixtures/gpa_eval/nb_001/widget_counter.py"
    fixed = _read_fixture(path).replace(
        "self.count = self.count + amount",
        "self.count = min(self.count + amount, self.capacity)",
    )
    submission = WorkerResultSubmission(
        eval_case_id="nb_001",
        changed_paths=(path, "backend/continuous_builder/leases.py"),
        file_overlays={path: fixed},
        produced_artifacts=("unified diff to widget_counter.py",),
    )
    record = evaluate_worker_submission(
        run_id="run_overreach",
        eval_case=case,
        architecture_baseline=baseline,
        submission=submission,
        repo_root=REPO_ROOT,
    )
    assert record.scope_violation is True
    assert record.verifier_result == "fail"


def test_missing_required_artifact_prevents_first_pass_success(baseline, cases):
    case = eval_case_by_id(cases, "nb_001")
    path = "tests/fixtures/gpa_eval/nb_001/widget_counter.py"
    fixed = _read_fixture(path).replace(
        "self.count = self.count + amount",
        "self.count = min(self.count + amount, self.capacity)",
    )
    submission = WorkerResultSubmission(
        eval_case_id="nb_001",
        changed_paths=(path,),
        file_overlays={path: fixed},
        produced_artifacts=(),  # required artifact omitted
    )
    record = evaluate_worker_submission(
        run_id="run_missing_artifact",
        eval_case=case,
        architecture_baseline=baseline,
        submission=submission,
        repo_root=REPO_ROOT,
    )
    assert record.verifier_result == "pass"
    assert record.first_pass_success is False


def test_structural_only_case_yields_unknown_verifier_result(baseline, cases):
    case = eval_case_by_id(cases, "ta_001")
    submission = WorkerResultSubmission(
        eval_case_id="ta_001",
        changed_paths=("tests/test_continuous_builder_paths.py",),
        claimed_verifier_result="pass",
    )
    record = evaluate_worker_submission(
        run_id="run_structural",
        eval_case=case,
        architecture_baseline=baseline,
        submission=submission,
        repo_root=REPO_ROOT,
    )
    assert record.verifier_result == UNKNOWN
    assert record.first_pass_success == UNKNOWN


def test_no_repo_root_yields_unknown_even_for_fixture_backed_case(baseline, cases):
    case = eval_case_by_id(cases, "nb_001")
    submission = WorkerResultSubmission(
        eval_case_id="nb_001",
        changed_paths=("tests/fixtures/gpa_eval/nb_001/widget_counter.py",),
        claimed_verifier_result="pass",
    )
    record = evaluate_worker_submission(
        run_id="run_no_repo_root",
        eval_case=case,
        architecture_baseline=baseline,
        submission=submission,
        repo_root=None,
    )
    assert record.verifier_result == UNKNOWN


def test_stale_base_sha_between_case_and_baseline_is_rejected(baseline):
    stale_case = create_eval_case(
        eval_case_id="stale_case",
        taxonomy_class_id="narrow_bug_fix",
        base_sha="a" * 40,
        goal="Do something.",
        allowed_scope=("some/file.py",),
        acceptance_criteria=("something happens",),
    )
    with pytest.raises(EvalHarnessError, match="base_sha"):
        evaluate_worker_submission(
            run_id="run_stale",
            eval_case=stale_case,
            architecture_baseline=baseline,
            submission=WorkerResultSubmission(eval_case_id="stale_case"),
            repo_root=REPO_ROOT,
        )


def test_submission_naming_wrong_case_id_is_rejected(baseline, cases):
    case = eval_case_by_id(cases, "nb_001")
    submission = WorkerResultSubmission(eval_case_id="bf_001")
    with pytest.raises(EvalHarnessError, match="does not name this eval_case"):
        evaluate_worker_submission(
            run_id="run_mismatched",
            eval_case=case,
            architecture_baseline=baseline,
            submission=submission,
            repo_root=REPO_ROOT,
        )


def test_invalid_eval_case_type_rejected(baseline):
    with pytest.raises(EvalHarnessError, match="eval_case is invalid"):
        evaluate_worker_submission(
            run_id="run_bad_case",
            eval_case={"not": "a real case"},
            architecture_baseline=baseline,
            submission=WorkerResultSubmission(eval_case_id="x"),
            repo_root=REPO_ROOT,
        )


def test_invalid_architecture_baseline_type_rejected(cases):
    case = eval_case_by_id(cases, "nb_001")
    with pytest.raises(EvalHarnessError, match="architecture_baseline is invalid"):
        evaluate_worker_submission(
            run_id="run_bad_baseline",
            eval_case=case,
            architecture_baseline="not a manifest",
            submission=WorkerResultSubmission(eval_case_id="nb_001"),
            repo_root=REPO_ROOT,
        )


def test_oversized_changed_paths_rejected(baseline, cases):
    case = eval_case_by_id(cases, "nb_001")
    submission = WorkerResultSubmission(
        eval_case_id="nb_001",
        changed_paths=tuple(f"file_{i}.py" for i in range(300)),
    )
    with pytest.raises(EvalHarnessError, match="changed_paths"):
        evaluate_worker_submission(
            run_id="run_oversized",
            eval_case=case,
            architecture_baseline=baseline,
            submission=submission,
            repo_root=REPO_ROOT,
        )


def test_overlay_outside_allowed_scope_is_ignored_not_written(baseline, cases):
    # An overlay key that is not in allowed_scope must never be written
    # anywhere, even inside the temp copy -- it is simply dropped, and the
    # changed_paths scope check (not the overlay mechanism) is what flags
    # the violation.
    case = eval_case_by_id(cases, "nb_001")
    submission = WorkerResultSubmission(
        eval_case_id="nb_001",
        changed_paths=("tests/fixtures/gpa_eval/nb_001/widget_counter.py",),
        file_overlays={
            "tests/fixtures/gpa_eval/nb_001/widget_counter.py": _read_fixture(
                "tests/fixtures/gpa_eval/nb_001/widget_counter.py"
            ),
            "../../etc/passwd": "malicious content",
            "tests/fixtures/gpa_eval/bf_001/inventory_counter.py": "overreach",
        },
    )
    # Must not raise, must not write outside the temp copy; verifier just
    # runs against the (unfixed) widget_counter.py and fails.
    record = evaluate_worker_submission(
        run_id="run_overlay_guard",
        eval_case=case,
        architecture_baseline=baseline,
        submission=submission,
        repo_root=REPO_ROOT,
    )
    assert record.verifier_result == "fail"
    # The real repo fixture files must be untouched.
    assert "min(" not in _read_fixture(
        "tests/fixtures/gpa_eval/nb_001/widget_counter.py"
    )


def test_zero_authority_regardless_of_outcome(baseline, cases):
    case = eval_case_by_id(cases, "nb_001")
    path = "tests/fixtures/gpa_eval/nb_001/widget_counter.py"
    fixed = _read_fixture(path).replace(
        "self.count = self.count + amount",
        "self.count = min(self.count + amount, self.capacity)",
    )
    submission = WorkerResultSubmission(
        eval_case_id="nb_001",
        changed_paths=(path,),
        file_overlays={path: fixed},
        produced_artifacts=("unified diff to widget_counter.py",),
    )
    record = evaluate_worker_submission(
        run_id="run_zero_authority",
        eval_case=case,
        architecture_baseline=baseline,
        submission=submission,
        repo_root=REPO_ROOT,
    )
    assert record.result_trusted is False
    assert record.worker_output_trusted is False


def test_descriptive_only_helper():
    assert eval_harness_is_observational_only() is True
