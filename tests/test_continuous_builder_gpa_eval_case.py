"""GP-A3 -- Frozen Evaluation Case Contract tests."""

import dataclasses

import pytest

from backend.continuous_builder.gpa_eval_case import (
    EVAL_CASE_VERSION,
    EvalCase,
    EvalCaseError,
    EvalCaseEvaluatorView,
    EvalCaseWorkerView,
    create_eval_case,
    eval_case_is_descriptive_only,
    to_worker_visible_dict,
    verify_no_evaluator_leakage,
)
from backend.continuous_builder.gpa_eval_schema import GPAEvalSchemaError

BASE_SHA = "d799c23169332135773e377443779ee9f9544c04"


def _forge(instance, **changes):
    forged = object.__new__(type(instance))
    for item in dataclasses.fields(instance):
        object.__setattr__(
            forged,
            item.name,
            changes.get(item.name, getattr(instance, item.name)),
        )
    return forged


def _fields(instance):
    return {
        item.name: getattr(instance, item.name)
        for item in dataclasses.fields(instance)
    }


def _make_case(**overrides):
    values = dict(
        eval_case_id="case_example_001",
        taxonomy_class_id="narrow_bug_fix",
        base_sha=BASE_SHA,
        goal="Fix the off-by-one in the widget counter.",
        allowed_scope=("backend/widgets/counter.py",),
        required_artifacts=("unified diff",),
        acceptance_criteria=("counter stops at the documented boundary",),
        expected_verification_commands=(
            "pytest tests/test_widgets_counter.py",
        ),
    )
    values.update(overrides)
    return create_eval_case(**values)


def test_deterministic_case_digest():
    first = _make_case()
    second = _make_case()
    assert first.case_sha256 == second.case_sha256
    assert first.to_dict() == second.to_dict()


def test_worker_visible_dict_excludes_evaluator_view():
    case = _make_case()
    payload = to_worker_visible_dict(case)
    assert "evaluator_view" not in payload
    assert verify_no_evaluator_leakage(payload) is True


def test_verify_no_evaluator_leakage_catches_nested_leak():
    case = _make_case()
    payload = to_worker_visible_dict(case)
    leaky = {"wrapper": {"inner": payload, "leak": case.evaluator_view.to_dict()}}
    assert verify_no_evaluator_leakage(leaky) is False


def test_full_dict_contains_both_views():
    case = _make_case()
    full = case.to_dict()
    assert "worker_view" in full
    assert "evaluator_view" in full
    assert full["evaluator_view"]["acceptance_criteria"]


def test_descriptive_only_helper():
    assert eval_case_is_descriptive_only() is True


def test_unknown_taxonomy_class_rejected():
    with pytest.raises(EvalCaseError, match="taxonomy_class_id is unknown"):
        _make_case(taxonomy_class_id="not_a_real_class")


def test_stale_base_sha_format_rejected():
    with pytest.raises(GPAEvalSchemaError):
        _make_case(base_sha="not-a-sha")


def test_malformed_schema_version_rejected():
    case = _make_case()
    forged = _forge(case, schema_version="gpa-eval-case-v99")
    with pytest.raises(EvalCaseError, match="schema_version"):
        EvalCase(**_fields(forged))


def test_forbidden_path_overlapping_allowed_scope_rejected():
    with pytest.raises(EvalCaseError, match="overlap"):
        _make_case(
            allowed_scope=("backend/widgets/counter.py",),
            forbidden_scope=("backend/widgets/counter.py",),
        )


def test_empty_allowed_scope_rejected():
    with pytest.raises(EvalCaseError, match="allowed_scope"):
        _make_case(allowed_scope=())


def test_missing_acceptance_criteria_rejected():
    with pytest.raises(EvalCaseError):
        _make_case(acceptance_criteria=())


def test_absolute_path_in_scope_rejected():
    with pytest.raises(GPAEvalSchemaError):
        _make_case(allowed_scope=("/etc/passwd",))


def test_path_traversal_in_scope_rejected():
    with pytest.raises(GPAEvalSchemaError):
        _make_case(allowed_scope=("../outside/file.py",))


def test_duplicate_eval_case_ids_with_conflicting_content_have_different_digests():
    # Two cases sharing an ID but disagreeing on goal text must not collide;
    # a corpus loader (GP-A5/GP-A6) is expected to reject same-ID entries
    # whose digests differ.
    case_a = _make_case(eval_case_id="dup_case", goal="Fix bug A.")
    case_b = _make_case(eval_case_id="dup_case", goal="Fix bug B.")
    assert case_a.eval_case_id == case_b.eval_case_id
    assert case_a.case_sha256 != case_b.case_sha256


def test_oversized_goal_rejected():
    with pytest.raises(GPAEvalSchemaError):
        _make_case(goal="x" * 100_000)


def test_case_cannot_be_constructed_without_trusted_token():
    case = _make_case()
    forged = _forge(case, _token=object())
    with pytest.raises(EvalCaseError):
        EvalCase(**_fields(forged))


def test_forged_case_field_with_stale_digest_rejected():
    case = _make_case()
    forged = _forge(case, taxonomy_class_id="test_addition")
    with pytest.raises(EvalCaseError, match="case_sha256 mismatch"):
        EvalCase(**_fields(forged))


def test_worker_view_cannot_be_constructed_without_trusted_token():
    case = _make_case()
    forged = _forge(case.worker_view, _token=object())
    with pytest.raises(EvalCaseError):
        EvalCaseWorkerView(**_fields(forged))


def test_evaluator_view_cannot_be_constructed_without_trusted_token():
    case = _make_case()
    forged = _forge(case.evaluator_view, _token=object())
    with pytest.raises(EvalCaseError):
        EvalCaseEvaluatorView(**_fields(forged))


def test_forged_worker_view_scope_change_detected_by_case_digest():
    case = _make_case()
    tampered_view = _forge(
        case.worker_view, allowed_scope=("backend/widgets/counter.py", "backend/secrets.py")
    )
    forged_case = _forge(case, worker_view=tampered_view)
    with pytest.raises(EvalCaseError):
        EvalCase(**_fields(forged_case))


def test_zero_authority():
    case = _make_case()
    for name in (
        "publication_authorized",
        "queue_transition_authorized",
        "github_authorized",
        "merge_authorized",
        "main_advancement_authorized",
        "result_trusted",
        "worker_output_trusted",
    ):
        assert getattr(case, name) is False


def test_schema_version_constant_matches_sealed_case():
    case = _make_case()
    assert case.schema_version == EVAL_CASE_VERSION
