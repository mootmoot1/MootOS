"""Tests for GP-B7 decomposition receipt / provenance."""

from pathlib import Path

import pytest

from backend.continuous_builder.gpa_eval_schema import AUTHORITY_FLAGS
from backend.continuous_builder.gpb_decomposer import decompose_task_contract
from backend.continuous_builder.gpb_decomposition_receipt import (
    create_decomposition_receipt,
    decomposition_receipt_is_planning_only,
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


def _contract():
    return create_frozen_task_contract(
        task_contract_id="tc_receipt_001",
        base_sha=TRUSTED_BASE,
        architecture_baseline_sha256=BASELINE,
        taxonomy_class_id="narrow_bug_fix",
        goal="Fix clamp",
        intent_summary="Narrow",
        allowed_scope=("tests/fixtures/gpa_eval/nb_001/widget_counter.py",),
        forbidden_scope=("backend/continuous_builder/trusted_policy.py",),
        acceptance_criteria=("count never exceeds capacity",),
        required_gates=("unit_tests",),
    )


def test_receipt_binds_identities(model):
    c = _contract()
    evidence = collect_impact_evidence(model, c.allowed_scope)
    plan = decompose_task_contract(c, impact_evidence=evidence)
    receipt = create_decomposition_receipt(
        c,
        plan,
        model=model,
        repo_root=REPO,
        uncertainty_count=len(evidence.uncertainties),
    )
    assert receipt.contract_sha256 == c.contract_sha256
    assert receipt.plan_sha256 == plan.plan_sha256
    assert receipt.system_model_sha256 == model.model_sha256
    assert receipt.context_engine_source_sha256 is not None
    assert receipt.node_count == len(plan.nodes)
    assert receipt.edge_count == len(plan.edges)
    assert receipt.approved_to_execute is False
    assert receipt.execution_authorized is False
    for name in AUTHORITY_FLAGS:
        assert getattr(receipt, name) is False


def test_valid_plan_not_approved(model):
    c = _contract()
    plan = decompose_task_contract(c, model)
    receipt = create_decomposition_receipt(c, plan, model=model, repo_root=REPO)
    assert receipt.approved_to_execute is False


def test_deterministic_receipt(model):
    c = _contract()
    plan = decompose_task_contract(c, model)
    a = create_decomposition_receipt(c, plan, model=model, repo_root=REPO)
    b = create_decomposition_receipt(c, plan, model=model, repo_root=REPO)
    assert a.receipt_sha256 == b.receipt_sha256


def test_mismatch_plan_contract_rejected(model):
    from backend.continuous_builder.gpb_decomposition_receipt import (
        DecompositionReceiptError,
    )
    c = _contract()
    plan = decompose_task_contract(c, model)
    other = create_frozen_task_contract(
        task_contract_id="tc_receipt_other",
        base_sha=TRUSTED_BASE,
        architecture_baseline_sha256=BASELINE,
        taxonomy_class_id="narrow_bug_fix",
        goal="Other",
        intent_summary="Other",
        allowed_scope=("tests/fixtures/gpa_eval/nb_001/widget_counter.py",),
        acceptance_criteria=("count never exceeds capacity",),
    )
    with pytest.raises(DecompositionReceiptError, match="digest mismatch"):
        create_decomposition_receipt(other, plan, model=model)


def test_helper():
    assert decomposition_receipt_is_planning_only() is True
