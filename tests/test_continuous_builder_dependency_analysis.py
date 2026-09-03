"""Tests for deterministic Continuous Builder dependency analysis."""

from dataclasses import FrozenInstanceError, replace

import pytest

from backend.continuous_builder.blueprint_parser import parse_blueprint
from backend.continuous_builder.dependency_analysis import (
    DependencyAnalysisError,
    DependencyReceipt,
    analyze_dependencies,
)
from backend.continuous_builder.queue_proposal import propose_candidates
from test_continuous_builder_blueprint import make_blueprint, make_slice


def parsed_with(slices):
    return parse_blueprint(make_blueprint(slices=slices).canonical_bytes())


def test_ready_is_mechanically_derived_from_exact_hard_receipt():
    slices = (make_slice(), make_slice(
        slice_id="CB-002", version="2", hard_dependencies=("CB-001",),
    ))
    parsed = parsed_with(slices)
    receipt = DependencyReceipt("receipt-1", "CB-001", "1", True, True)
    analysis = analyze_dependencies(
        parsed, propose_candidates(parsed), (receipt,)
    )
    assert analysis.results[0].eligible is True
    assert analysis.results[1].eligible is True
    assert analysis.dispatch_authorized is False


@pytest.mark.parametrize("receipt,reason", [
    (None, "missing_receipt"),
    (DependencyReceipt("r", "CB-001", "9", True, True), "version_mismatch"),
    (DependencyReceipt("r", "CB-001", "1", False, True), "dependency_failed"),
    (DependencyReceipt("r", "CB-001", "1", True, False), "not_authoritative"),
])
def test_missing_mismatched_or_failed_hard_dependency_blocks(receipt, reason):
    parsed = parsed_with((
        make_slice(),
        make_slice(slice_id="CB-002", hard_dependencies=("CB-001",)),
    ))
    receipts = () if receipt is None else (receipt,)
    result = analyze_dependencies(parsed, propose_candidates(parsed), receipts)
    assert result.results[1].eligible is False
    assert reason in result.results[1].blocked_reasons[0]


def test_soft_dependency_is_evidence_but_does_not_block():
    parsed = parsed_with((
        make_slice(),
        make_slice(slice_id="CB-002", soft_dependencies=("CB-001",)),
    ))
    result = analyze_dependencies(parsed, propose_candidates(parsed))
    assert result.results[1].eligible is True
    assert result.results[1].soft_dependencies_satisfied == ()


def test_missing_dependency_and_cycles_fail_closed():
    missing = parsed_with((make_slice(hard_dependencies=("CB-999",)),))
    with pytest.raises(DependencyAnalysisError, match="missing dependencies"):
        analyze_dependencies(missing, propose_candidates(missing))
    cyclic = parsed_with((
        make_slice(hard_dependencies=("CB-002",)),
        make_slice(slice_id="CB-002", hard_dependencies=("CB-001",)),
    ))
    with pytest.raises(DependencyAnalysisError, match="cycle"):
        analyze_dependencies(cyclic, propose_candidates(cyclic))


def test_forged_result_and_source_binding_are_rejected():
    parsed = parsed_with((make_slice(),))
    analysis = analyze_dependencies(parsed, propose_candidates(parsed))
    forged = replace(analysis.results[0], eligible=False)
    with pytest.raises(DependencyAnalysisError, match="forged"):
        replace(analysis, results=(forged,))
    candidate = replace(analysis.candidates[0], blueprint_digest="0" * 64)
    with pytest.raises(DependencyAnalysisError, match="binding"):
        analyze_dependencies(parsed, (candidate,))


def test_analysis_is_deterministic_immutable_and_non_executing():
    parsed = parsed_with((make_slice(),))
    first = analyze_dependencies(parsed, propose_candidates(parsed))
    second = analyze_dependencies(parsed, propose_candidates(parsed))
    assert first.canonical_bytes() == second.canonical_bytes()
    with pytest.raises(FrozenInstanceError):
        first.results = ()
    with pytest.raises(DependencyAnalysisError, match="authorize dispatch"):
        replace(first, dispatch_authorized=True)
