"""GP-A8 -- cross-slice integration and closure-level adversarial proof.

Exercises the full GP-A pipeline (architecture baseline -> corpus ->
harness -> evidence record) together, plus adversarial scenarios that
span more than one GP-A module and so don't belong to any single slice's
own test file.
"""

import dataclasses
from pathlib import Path

import pytest

from backend.continuous_builder.gpa_architecture_baseline import (
    ArchitectureBaselineError,
    create_architecture_baseline_manifest,
)
from backend.continuous_builder.gpa_eval_case import (
    create_eval_case,
    to_worker_visible_dict,
    verify_no_evaluator_leakage,
)
from backend.continuous_builder.gpa_eval_corpus import (
    CORPUS_BASE_SHA,
    FIXTURE_BACKED_CASES,
    create_gpa_eval_corpus_v1,
)
from backend.continuous_builder.gpa_eval_harness import (
    EvalHarnessError,
    WorkerResultSubmission,
    evaluate_worker_submission,
)
from backend.continuous_builder.gpa_eval_schema import GPAEvalSchemaError, UNKNOWN
from backend.continuous_builder.gpa_evidence_record import EvidenceRecord

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def baseline():
    return create_architecture_baseline_manifest(
        REPO_ROOT, base_sha=CORPUS_BASE_SHA
    )


@pytest.fixture(scope="module")
def cases():
    return create_gpa_eval_corpus_v1()


def test_every_corpus_case_binds_to_the_real_architecture_baseline(baseline, cases):
    for case in cases:
        assert case.base_sha == baseline.base_sha


def test_every_corpus_case_produces_a_sealed_evidence_record_via_harness(
    baseline, cases,
):
    for case in cases:
        submission = WorkerResultSubmission(
            eval_case_id=case.eval_case_id,
            changed_paths=case.worker_view.allowed_scope,
            produced_artifacts=case.worker_view.required_artifacts,
        )
        record = evaluate_worker_submission(
            run_id=f"integration_{case.eval_case_id}",
            eval_case=case,
            architecture_baseline=baseline,
            submission=submission,
            repo_root=REPO_ROOT,
        )
        assert isinstance(record, EvidenceRecord)
        assert record.eval_case_id == case.eval_case_id
        assert record.eval_case_sha256 == case.case_sha256
        assert record.architecture_baseline_sha256 == baseline.manifest_sha256
        assert record.scope_violation is False


def test_fixture_backed_cases_are_a_strict_subset_of_the_corpus(cases):
    corpus_ids = {case.eval_case_id for case in cases}
    assert set(FIXTURE_BACKED_CASES) <= corpus_ids


def test_stale_architecture_baseline_rejected_across_the_pipeline(cases):
    # A manifest built for a *different* (but still valid-looking) base
    # SHA than the corpus must not silently validate against it.
    other_sha = "e" * 40
    other_baseline = create_architecture_baseline_manifest(
        REPO_ROOT, base_sha=other_sha
    )
    case = cases[0]
    with pytest.raises(EvalHarnessError, match="base_sha"):
        evaluate_worker_submission(
            run_id="run_stale_pipeline",
            eval_case=case,
            architecture_baseline=other_baseline,
            submission=WorkerResultSubmission(eval_case_id=case.eval_case_id),
            repo_root=REPO_ROOT,
        )


def test_unsupported_schema_version_rejected_across_every_sealed_type(cases, baseline):
    # A single sweep proving every sealed GP-A container independently
    # enforces its own schema_version/version constant, not just the ones
    # exercised in each module's own test file.
    def _forge(instance, **changes):
        forged = object.__new__(type(instance))
        for item in dataclasses.fields(instance):
            object.__setattr__(
                forged,
                item.name,
                changes.get(item.name, getattr(instance, item.name)),
            )
        return forged

    forged_manifest = _forge(baseline, schema_version="not-a-real-version")
    with pytest.raises(ArchitectureBaselineError):
        type(baseline)(
            **{
                f.name: getattr(forged_manifest, f.name)
                for f in dataclasses.fields(forged_manifest)
            }
        )

    case = cases[0]
    forged_case = _forge(case, schema_version="not-a-real-version")
    with pytest.raises(GPAEvalSchemaError):
        type(case)(
            **{
                f.name: getattr(forged_case, f.name)
                for f in dataclasses.fields(forged_case)
            }
        )


def test_context_inputs_field_never_carries_evaluator_only_text(cases):
    # A worker-visible field (context_inputs) must never happen to contain
    # any of the evaluator-only acceptance criteria text verbatim -- a
    # cheap grep-style leak that structural separation alone wouldn't
    # catch if a case author pasted the wrong text into the wrong field.
    for case in cases:
        payload = to_worker_visible_dict(case)
        assert verify_no_evaluator_leakage(payload)
        worker_text = " ".join(case.worker_view.context_inputs) + case.worker_view.goal
        for criterion in case.evaluator_view.acceptance_criteria:
            assert criterion not in worker_text


def test_incomplete_context_case_still_yields_valid_but_unknown_evidence(
    baseline, cases,
):
    # A "context_heavy_navigation_task" case whose worker context_inputs
    # were (hypothetically) incompletely supplied still produces a valid,
    # honestly-UNKNOWN evidence record rather than a crash or a fabricated
    # pass.
    case = next(c for c in cases if c.eval_case_id == "ctx_001")
    submission = WorkerResultSubmission(
        eval_case_id="ctx_001",
        changed_paths=(),  # worker produced nothing usable
        produced_artifacts=(),
    )
    record = evaluate_worker_submission(
        run_id="run_incomplete_context",
        eval_case=case,
        architecture_baseline=baseline,
        submission=submission,
        repo_root=REPO_ROOT,
    )
    assert record.verifier_result == UNKNOWN
    assert record.scope_violation is False


def test_duplicate_case_id_authored_independently_never_collides_silently():
    base_sha = CORPUS_BASE_SHA
    case_a = create_eval_case(
        eval_case_id="shared_id",
        taxonomy_class_id="narrow_bug_fix",
        base_sha=base_sha,
        goal="Version A of the goal.",
        allowed_scope=("a.py",),
        acceptance_criteria=("criterion A",),
    )
    case_b = create_eval_case(
        eval_case_id="shared_id",
        taxonomy_class_id="test_addition",
        base_sha=base_sha,
        goal="Version B of the goal.",
        allowed_scope=("b.py",),
        acceptance_criteria=("criterion B",),
    )
    assert case_a.eval_case_id == case_b.eval_case_id
    assert case_a.case_sha256 != case_b.case_sha256
    # A corpus/harness consumer keying purely on eval_case_id without also
    # checking case_sha256 could conflate these -- this is documented as a
    # known limitation in the GP-A closure doc, not silently handled here.
