"""Tests for GP-B5 deterministic decomposer."""

from pathlib import Path

import pytest

from backend.continuous_builder.gpa_eval_schema import AUTHORITY_FLAGS
from backend.continuous_builder.gpb_decomposer import (
    DECOMPOSER_VERSION,
    decompose_task_contract,
    decomposer_is_planning_only,
    decomposer_uses_no_llm,
)
from backend.continuous_builder.gpb_impact_evidence import collect_impact_evidence
from backend.continuous_builder.gpb_task_contract import create_frozen_task_contract
from backend.continuous_builder.system_model import build_system_model

TRUSTED_BASE = "b448dcaf679861b23cc690186fc96815776a6e3d"
BASELINE = "a" * 64
REPO = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def model():
    return build_system_model(REPO, base_sha=TRUSTED_BASE)


def _contract(**overrides):
    values = dict(
        task_contract_id="tc_decomp_001",
        base_sha=TRUSTED_BASE,
        architecture_baseline_sha256=BASELINE,
        taxonomy_class_id="narrow_bug_fix",
        goal="Fix WidgetCounter.add() clamp bug",
        intent_summary="Narrow localized fix",
        allowed_scope=("tests/fixtures/gpa_eval/nb_001/widget_counter.py",),
        forbidden_scope=("backend/continuous_builder/trusted_policy.py",),
        acceptance_criteria=("count never exceeds capacity",),
        budget_ceiling_wall_clock_seconds=600,
        risk_ceiling_indicators=("none",),
        required_gates=("unit_tests",),
    )
    values.update(overrides)
    return create_frozen_task_contract(**values)


def test_simple_not_over_decomposed(model):
    plan = decompose_task_contract(_contract(), model)
    levels = {n.level for n in plan.nodes}
    # goal + atomic (+ optional verify/investigation) -- no forced 5 slices
    assert "goal" in levels
    assert "atomic" in levels
    slice_nodes = [n for n in plan.nodes if n.level == "slice"]
    assert len(slice_nodes) == 0
    assert plan.approved_to_execute is False
    assert plan.execution_authorized is False
    assert plan.decomposer_version == DECOMPOSER_VERSION


def test_large_not_one_giant_slice(model):
    scope = tuple(
        sorted(
            (
                "tests/fixtures/gpa_eval/nb_001/widget_counter.py",
                "tests/fixtures/gpa_eval/bf_001/feature_module.py",
                "tests/fixtures/gpa_eval/refactor_001/legacy_module.py",
                "backend/continuous_builder/gpa_eval_schema.py",
            )
        )
    )
    c = _contract(
        task_contract_id="tc_decomp_multi",
        taxonomy_class_id="multi_file_feature",
        allowed_scope=scope,
        forbidden_scope=(),
        goal="Multi-component feature spanning several modules",
        intent_summary="Bounded multi-file change",
    )
    plan = decompose_task_contract(c, model)
    atomics = [n for n in plan.nodes if n.level == "atomic"]
    assert len(atomics) >= 2
    # No single node holding entire multi-path scope as only atomic without slices
    # when multi-path: expect slices or multiple atomics
    assert len(plan.nodes) >= 3


def test_tcb_adjacent_escalates(model):
    c = _contract(
        task_contract_id="tc_decomp_tcb",
        taxonomy_class_id="tcb_adjacent_change",
        allowed_scope=("backend/continuous_builder/trusted_policy.py",),
        forbidden_scope=(),
        risk_ceiling_indicators=("tcb_adjacent", "policy_sensitive"),
        goal="Document TCB registry comment only",
        intent_summary="TCB-adjacent descriptive touch",
    )
    plan = decompose_task_contract(c, model)
    assert plan.requires_escalation is True
    assert any("tcb" in r for r in plan.escalation_reasons)
    inv = [n for n in plan.nodes if n.level == "investigation"]
    assert inv


def test_deterministic_plan_digest(model):
    c = _contract()
    a = decompose_task_contract(c, model)
    b = decompose_task_contract(c, model)
    assert a.plan_sha256 == b.plan_sha256
    assert [n.node_id for n in a.nodes] == [n.node_id for n in b.nodes]


def test_binds_contract_identity(model):
    c = _contract()
    plan = decompose_task_contract(c, model)
    assert plan.task_contract_id == c.task_contract_id
    assert plan.contract_sha256 == c.contract_sha256
    assert plan.base_sha == c.base_sha
    assert plan.architecture_baseline_sha256 == c.architecture_baseline_sha256


def test_zero_authority(model):
    plan = decompose_task_contract(_contract(), model)
    for name in AUTHORITY_FLAGS:
        assert getattr(plan, name) is False


def test_helpers():
    assert decomposer_is_planning_only() is True
    assert decomposer_uses_no_llm() is True


def test_feature_with_tests_separates(model):
    scope = tuple(
        sorted(
            (
                "tests/fixtures/gpa_eval/bf_001/feature_module.py",
                "tests/fixtures/gpa_eval/bf_001/acceptance.py",
            )
        )
    )
    c = _contract(
        task_contract_id="tc_decomp_ft",
        taxonomy_class_id="bounded_feature_addition",
        allowed_scope=scope,
        forbidden_scope=(),
        goal="Add feature with tests",
        intent_summary="Feature plus acceptance",
    )
    plan = decompose_task_contract(c, model)
    types = {n.node_type for n in plan.nodes}
    # Should include implement and/or test separation when both present
    assert "decompose" in types or "implement" in types


def test_precomputed_evidence_path(model):
    c = _contract()
    evidence = collect_impact_evidence(model, c.allowed_scope)
    plan = decompose_task_contract(c, impact_evidence=evidence)
    assert plan.impact_evidence_sha256 == evidence.evidence_sha256


def test_rejects_missing_model():
    from backend.continuous_builder.gpb_decomposer import DecomposerError
    with pytest.raises(DecomposerError, match="model"):
        decompose_task_contract(_contract())
