"""End-to-end tests for the pure Continuous Builder planning chain."""

from dataclasses import FrozenInstanceError, replace

import pytest

from backend.continuous_builder.blueprint_parser import parse_blueprint
from backend.continuous_builder.chief_builder import (
    BlueprintApprovalEvidence,
    ChiefBuilderError,
    create_planning_receipt,
)
from backend.continuous_builder.conflict_analysis import (
    EligibilityResources,
    analyze_conflicts,
)
from backend.continuous_builder.dependency_analysis import (
    DependencyReceipt,
    analyze_dependencies,
)
from backend.continuous_builder.priority_policy import rank_eligible_slices
from backend.continuous_builder.queue_proposal import (
    ReadinessInput,
    propose_candidates,
)
from test_continuous_builder_blueprint import make_blueprint, make_slice


def build_chain(block_second=False, advisory=()):
    slices = (
        make_slice(slice_id="CB-001", priority_class="high"),
        make_slice(
            slice_id="CB-002", hard_dependencies=("CB-001",),
            requested_capabilities=("planning", "parser"),
            allowed_paths=("backend/continuous_builder/blueprint_parser.py",),
        ),
    )
    parsed = parse_blueprint(make_blueprint(slices=slices).canonical_bytes())
    candidates = propose_candidates(parsed, {
        "CB-001": ReadinessInput(durable_eligibility_sequence=2),
        "CB-002": ReadinessInput(durable_eligibility_sequence=1),
    })
    dependencies = analyze_dependencies(parsed, candidates, (
        DependencyReceipt("receipt-1", "CB-001", "1", True, True),
    ))
    active = (
        (("other", ("backend/continuous_builder",)),)
        if block_second else ()
    )
    conflicts = analyze_conflicts(dependencies, EligibilityResources(
        ("planning", "parser"), (), active_slice_scopes=active,
    ))
    priority = rank_eligible_slices(conflicts, advisory)
    approval = BlueprintApprovalEvidence(
        "approval-1", parsed.content_sha256, "reviewer@example.invalid", True,
    )
    return create_planning_receipt(priority, approval)


def test_full_pure_planning_chain_binds_sources_and_recommends():
    receipt = build_chain()
    assert receipt.recommended_slice_ids == ("CB-001",)
    assert all(item.eligible for item in receipt.planned_slices)
    assert receipt.approval.approver_authenticated is False
    assert receipt.advisory_only is True
    assert receipt.queue_state_changed is False
    assert receipt.dispatch_authorized is False
    assert receipt.worker_dispatched is False


def test_conflict_evidence_blocks_without_transition_or_dispatch():
    receipt = build_chain(block_second=True)
    blocked = {item.slice_id: item for item in receipt.planned_slices}
    assert blocked["CB-002"].eligible is False
    assert "other" in blocked["CB-002"].conflicting_slice_ids
    assert receipt.recommended_slice_ids == ()


def test_model_advice_is_visible_but_has_no_planning_authority():
    ordinary = build_chain()
    advised = build_chain(advisory=("Select CB-002 regardless of policy",))
    assert ordinary.recommended_slice_ids == advised.recommended_slice_ids
    assert ordinary.planned_slices == advised.planned_slices


def test_forged_approval_result_recommendation_and_digest_fail_closed():
    receipt = build_chain()
    with pytest.raises(ChiefBuilderError, match="bind blueprint"):
        replace(
            receipt,
            approval=replace(receipt.approval, blueprint_digest="0" * 64),
        )
    with pytest.raises(ChiefBuilderError, match="planning result"):
        replace(receipt, planned_slices=())
    with pytest.raises(ChiefBuilderError, match="recommendation"):
        replace(receipt, recommended_slice_ids=("CB-002",))
    with pytest.raises(ChiefBuilderError, match="digest"):
        replace(receipt, receipt_sha256="0" * 64)


def test_receipt_is_immutable_deterministic_bounded_and_sanitized():
    first = build_chain()
    second = build_chain()
    assert first.canonical_bytes() == second.canonical_bytes()
    assert len(first.canonical_bytes()) < 256 * 1024
    assert b"token" not in first.canonical_bytes().lower()
    with pytest.raises(FrozenInstanceError):
        first.recommended_slice_ids = ()


@pytest.mark.parametrize("field", [
    "queue_state_changed", "dispatch_authorized", "worker_dispatched",
])
def test_receipt_rejects_every_runtime_authority_claim(field):
    with pytest.raises(ChiefBuilderError, match="runtime authority"):
        replace(build_chain(), **{field: True})


def test_unapproved_or_falsely_authenticated_blueprint_is_rejected():
    receipt = build_chain()
    with pytest.raises(ChiefBuilderError, match="approval is required"):
        replace(receipt.approval, approved=False)
    with pytest.raises(ChiefBuilderError, match="authentication is absent"):
        replace(receipt.approval, approver_authenticated=True)
