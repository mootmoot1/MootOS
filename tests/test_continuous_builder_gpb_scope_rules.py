"""Adversarial tests for GP-B3 Scope Preservation Rules."""

import pytest

from backend.continuous_builder.gpa_eval_schema import AUTHORITY_FLAGS
from backend.continuous_builder.gpb_decomposition_node import (
    create_decomposition_node,
)
from backend.continuous_builder.gpb_scope_rules import (
    check_contract_identity_preserved,
    check_node_against_contract,
    check_plan_nodes_against_contract,
    scope_rules_are_planning_only,
)
from backend.continuous_builder.gpb_task_contract import create_frozen_task_contract

TRUSTED_BASE = "b448dcaf679861b23cc690186fc96815776a6e3d"
BASELINE = "a" * 64
SCOPE = ("tests/fixtures/gpa_eval/nb_001/widget_counter.py",)
FORBIDDEN = ("backend/continuous_builder/trusted_policy.py",)


def _contract(**overrides):
    values = dict(
        task_contract_id="tc_scope_001",
        base_sha=TRUSTED_BASE,
        architecture_baseline_sha256=BASELINE,
        taxonomy_class_id="narrow_bug_fix",
        goal="Fix clamp",
        intent_summary="Narrow fix",
        allowed_scope=SCOPE,
        forbidden_scope=FORBIDDEN,
        acceptance_criteria=("count never exceeds capacity",),
        budget_ceiling_wall_clock_seconds=600,
        risk_ceiling_indicators=("none",),
        required_gates=("unit_tests", "human_review"),
    )
    values.update(overrides)
    return create_frozen_task_contract(**values)


def _atomic(**overrides):
    values = dict(
        node_id="n_atomic_001",
        parent_id="n_goal_001",
        level="atomic",
        node_type="implement",
        title="Implement clamp",
        objective="Clamp add()",
        rationale="Direct fix",
        candidate_allowed_scope=SCOPE,
        inherited_forbidden_scope=FORBIDDEN,
        acceptance_checkpoint=("count never exceeds capacity",),
        complexity_estimate="small",
        children=(),
    )
    values.update(overrides)
    return create_decomposition_node(**values)


def test_preserving_node_passes():
    result = check_node_against_contract(_contract(), _atomic())
    assert result.preserved is True
    assert result.requires_escalation is False
    assert result.violations == ()
    assert result.execution_authorized is False
    assert result.scope_expansion_authorized is False


def test_child_broadens_scope_escalates():
    node = _atomic(
        candidate_allowed_scope=SCOPE
        + ("backend/continuous_builder/worker_request.py",)
    )
    result = check_node_against_contract(_contract(), node)
    assert result.preserved is False
    codes = {v.code for v in result.violations}
    assert "new_path_outside_envelope" in codes


def test_forbidden_inclusion_escalates():
    # Dropping inherited forbidden paths is an envelope violation.
    node = _atomic(inherited_forbidden_scope=())
    result = check_node_against_contract(_contract(), node)
    assert result.preserved is False
    assert any(v.code == "forbidden_path_inclusion" for v in result.violations)


def test_forbidden_path_in_candidate_rejected_at_node_seal():
    from backend.continuous_builder.gpb_decomposition_node import (
        DecompositionNodeError,
    )
    with pytest.raises(DecompositionNodeError, match="intersects"):
        _atomic(
            candidate_allowed_scope=SCOPE + FORBIDDEN,
            inherited_forbidden_scope=FORBIDDEN,
        )


def test_relaxed_acceptance_escalates():
    node = _atomic(acceptance_checkpoint=("totally different criterion",))
    result = check_node_against_contract(_contract(), node)
    assert result.preserved is False
    assert any(v.code == "relaxed_acceptance" for v in result.violations)


def test_parent_envelope_exceeded():
    wide_scope = tuple(sorted(SCOPE + (
        "tests/fixtures/gpa_eval/bf_001/feature_module.py",
    )))
    c = _contract(allowed_scope=wide_scope)
    parent = create_decomposition_node(
        node_id="n_goal_001",
        parent_id=None,
        level="goal",
        node_type="decompose",
        title="Goal",
        objective="o",
        rationale="r",
        candidate_allowed_scope=SCOPE,
        inherited_forbidden_scope=FORBIDDEN,
        children=("n_atomic_001",),
        complexity_estimate="medium",
    )
    child = _atomic(
        candidate_allowed_scope=(
            "tests/fixtures/gpa_eval/bf_001/feature_module.py",
        ),
        acceptance_checkpoint=("count never exceeds capacity",),
    )
    result = check_node_against_contract(c, child, parent_node=parent)
    assert result.preserved is False
    assert any(v.code == "parent_envelope_exceeded" for v in result.violations)


def test_cycle_detected():
    a = _atomic(node_id="n_a", parent_id=None, depends_on=("n_b",), children=())
    b = _atomic(node_id="n_b", parent_id=None, depends_on=("n_a",), children=())
    result = check_plan_nodes_against_contract(_contract(), (a, b))
    assert result.preserved is False
    assert any(v.code == "cycle_detected" for v in result.violations)


def test_duplicate_node_ids():
    a = _atomic(node_id="n_dup", parent_id=None, children=())
    b = _atomic(node_id="n_dup", parent_id=None, children=(), title="other")
    result = check_plan_nodes_against_contract(_contract(), (a, b))
    assert result.preserved is False
    assert any(v.code == "duplicate_node_id" for v in result.violations)


def test_out_of_scope_dependency():
    node = _atomic(depends_on=("n_missing",), parent_id=None, children=())
    result = check_plan_nodes_against_contract(_contract(), (node,))
    assert result.preserved is False
    assert any(v.code == "out_of_scope_dependency" for v in result.violations)


def test_changed_base_sha_escalates():
    original = _contract()
    candidate = _contract(
        base_sha="cccccccccccccccccccccccccccccccccccccccc"
    )
    result = check_contract_identity_preserved(original, candidate)
    assert result.preserved is False
    assert any(v.code == "changed_base_sha" for v in result.violations)


def test_changed_intent_escalates():
    original = _contract()
    candidate = _contract(goal="Completely different goal text here")
    result = check_contract_identity_preserved(original, candidate)
    assert result.preserved is False
    assert any(v.code == "changed_intent" for v in result.violations)


def test_removed_gate_escalates():
    original = _contract()
    candidate = _contract(required_gates=("unit_tests",))
    result = check_contract_identity_preserved(original, candidate)
    assert result.preserved is False
    assert any(v.code == "removed_gate" for v in result.violations)


def test_increased_budget_escalates():
    original = _contract()
    candidate = _contract(budget_ceiling_wall_clock_seconds=9999)
    result = check_contract_identity_preserved(original, candidate)
    assert result.preserved is False
    assert any(v.code == "increased_budget" for v in result.violations)


def test_increased_risk_ceiling_escalates():
    original = _contract()
    candidate = _contract(
        risk_ceiling_indicators=("none", "tcb_adjacent"),
        taxonomy_class_id="narrow_bug_fix",
    )
    result = check_contract_identity_preserved(original, candidate)
    assert result.preserved is False
    assert any(v.code == "increased_risk_ceiling" for v in result.violations)


def test_changed_baseline_escalates():
    original = _contract()
    candidate = _contract(architecture_baseline_sha256="b" * 64)
    result = check_contract_identity_preserved(original, candidate)
    assert result.preserved is False
    assert any(
        v.code == "changed_architecture_baseline" for v in result.violations
    )


def test_identical_contract_preserved():
    c = _contract()
    result = check_contract_identity_preserved(c, c)
    assert result.preserved is True


def test_zero_authority_on_result():
    result = check_node_against_contract(_contract(), _atomic())
    for name in AUTHORITY_FLAGS:
        assert getattr(result, name) is False


def test_planning_only_helper():
    assert scope_rules_are_planning_only() is True


def test_result_digest_deterministic():
    a = check_node_against_contract(_contract(), _atomic())
    b = check_node_against_contract(_contract(), _atomic())
    assert a.result_sha256 == b.result_sha256
