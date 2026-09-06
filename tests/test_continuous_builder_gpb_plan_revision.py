"""Tests for GP-B6 plan revision without contract drift."""

from pathlib import Path

import pytest

from backend.continuous_builder.gpb_decomposer import decompose_task_contract
from backend.continuous_builder.gpb_decomposition_node import create_decomposition_node
from backend.continuous_builder.gpb_plan_revision import (
    make_revision_op,
    plan_revision_is_planning_only,
    revise_execution_plan,
)
from backend.continuous_builder.gpb_task_contract import create_frozen_task_contract
from backend.continuous_builder.system_model import build_system_model

TRUSTED_BASE = "b448dcaf679861b23cc690186fc96815776a6e3d"
BASELINE = "a" * 64
REPO = Path(__file__).resolve().parents[1]
SCOPE = ("tests/fixtures/gpa_eval/nb_001/widget_counter.py",)
FORBIDDEN = ("backend/continuous_builder/trusted_policy.py",)


@pytest.fixture(scope="module")
def model():
    return build_system_model(REPO, base_sha=TRUSTED_BASE)


def _contract(**overrides):
    values = dict(
        task_contract_id="tc_rev_001",
        base_sha=TRUSTED_BASE,
        architecture_baseline_sha256=BASELINE,
        taxonomy_class_id="narrow_bug_fix",
        goal="Fix clamp",
        intent_summary="Narrow fix",
        allowed_scope=SCOPE,
        forbidden_scope=FORBIDDEN,
        acceptance_criteria=("count never exceeds capacity",),
        required_gates=("unit_tests",),
    )
    values.update(overrides)
    return create_frozen_task_contract(**values)


def test_insert_investigation_preserves_contract(model):
    c = _contract()
    plan = decompose_task_contract(c, model)
    inv = create_decomposition_node(
        node_id="n_invest_added",
        parent_id=plan.root_node_id,
        level="investigation",
        node_type="investigate",
        title="Extra investigation",
        objective="Clarify helper ownership",
        rationale="Inserted prerequisite",
        candidate_allowed_scope=SCOPE,
        inherited_forbidden_scope=FORBIDDEN,
        acceptance_checkpoint=("ownership documented",),
        complexity_estimate="small",
        children=(),
    )
    op = make_revision_op(
        op="insert_investigation",
        new_node=inv,
        note="add investigation",
    )
    result = revise_execution_plan(c, plan, (op,))
    assert result.applied is True
    assert result.preserved_contract is True
    assert result.requires_escalation is False
    assert result.revised_plan is not None
    assert result.revised_plan.contract_sha256 == c.contract_sha256
    assert result.revised_plan.approved_to_execute is False
    assert any(n.node_id == "n_invest_added" for n in result.revised_plan.nodes)


def test_malicious_scope_widen_escalates(model):
    c = _contract()
    plan = decompose_task_contract(c, model)
    evil = create_decomposition_node(
        node_id="n_evil",
        parent_id=plan.root_node_id,
        level="atomic",
        node_type="implement",
        title="Widen",
        objective="Touch policy",
        rationale="malicious",
        candidate_allowed_scope=SCOPE
        + ("backend/continuous_builder/worker_request.py",),
        inherited_forbidden_scope=FORBIDDEN,
        acceptance_checkpoint=("count never exceeds capacity",),
        complexity_estimate="small",
        children=(),
    )
    op = make_revision_op(op="insert_prerequisite", new_node=evil, note="widen")
    result = revise_execution_plan(c, plan, (op,))
    assert result.applied is False
    assert result.requires_escalation is True
    assert result.revised_plan is None
    assert any("new_path" in r or "outside" in r for r in result.escalation_reasons) or result.escalation_reasons


def test_silent_contract_mismatch_escalates(model):
    c = _contract()
    plan = decompose_task_contract(c, model)
    other = _contract(task_contract_id="tc_rev_other", goal="Different goal text")
    result = revise_execution_plan(other, plan, ())
    assert result.applied is False
    assert result.requires_escalation is True
    assert "plan_contract_digest_mismatch" in result.escalation_reasons


def test_reorder_allowed(model):
    c = _contract()
    plan = decompose_task_contract(c, model)
    atomics = [n for n in plan.nodes if n.level == "atomic"]
    assert atomics
    target = atomics[0]
    op = make_revision_op(
        op="reorder",
        target_node_id=target.node_id,
        depends_on=target.depends_on,
        note="noop reorder",
    )
    result = revise_execution_plan(c, plan, (op,))
    assert result.applied is True
    assert result.preserved_contract is True


def test_replace_strategy_cannot_widen(model):
    c = _contract()
    plan = decompose_task_contract(c, model)
    target = next(n for n in plan.nodes if n.level == "atomic")
    widened = create_decomposition_node(
        node_id=target.node_id,
        parent_id=target.parent_id,
        level=target.level,
        node_type=target.node_type,
        title=target.title,
        objective=target.objective,
        rationale="replace widen",
        depends_on=target.depends_on,
        affected_components=target.affected_components,
        candidate_allowed_scope=SCOPE
        + ("backend/continuous_builder/gpa_eval_schema.py",),
        inherited_forbidden_scope=target.inherited_forbidden_scope,
        acceptance_checkpoint=target.acceptance_checkpoint,
        complexity_estimate=target.complexity_estimate,
        children=(),
    )
    op = make_revision_op(
        op="replace_strategy",
        target_node_id=target.node_id,
        new_node=widened,
        note="evil replace",
    )
    result = revise_execution_plan(c, plan, (op,))
    assert result.applied is False
    assert "replace_widens_scope" in result.escalation_reasons


def test_planning_only_helper():
    assert plan_revision_is_planning_only() is True
