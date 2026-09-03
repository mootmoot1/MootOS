"""Tests for pure Continuous Builder conflict eligibility."""

from dataclasses import FrozenInstanceError, replace

import pytest

from backend.continuous_builder.blueprint_parser import parse_blueprint
from backend.continuous_builder.conflict_analysis import (
    ConflictAnalysisError,
    EligibilityResources,
    analyze_conflicts,
)
from backend.continuous_builder.dependency_analysis import analyze_dependencies
from backend.continuous_builder.queue_proposal import propose_candidates
from test_continuous_builder_blueprint import make_blueprint, make_slice


def dependency_analysis(slice_value=None):
    blueprint = make_blueprint(slices=(slice_value or make_slice(),))
    parsed = parse_blueprint(blueprint.canonical_bytes())
    return analyze_dependencies(parsed, propose_candidates(parsed))


def resources(**changes):
    values = dict(
        available_capabilities=("planning",),
        available_authority_classes=(), resource_available=True,
        budget_available=True,
    )
    values.update(changes)
    return EligibilityResources(**values)


def test_all_mechanical_inputs_are_required_for_eligibility():
    result = analyze_conflicts(dependency_analysis(), resources())
    assert result.results[0].eligible is True
    assert result.lease_created is False
    assert result.worker_dispatched is False


@pytest.mark.parametrize("changes,reason", [
    ({"available_capabilities": ()}, "capability_unavailable"),
    ({"resource_available": False}, "resource_unavailable"),
    ({"budget_available": False}, "budget_unavailable"),
    ({"active_slice_scopes": (("other", ("backend/continuous_builder",)),)},
     "active_scope_conflict"),
])
def test_missing_capability_resource_budget_or_scope_blocks(changes, reason):
    result = analyze_conflicts(dependency_analysis(), resources(**changes))
    assert result.results[0].eligible is False
    assert any(
        value.startswith(reason)
        for value in result.results[0].blocked_reasons
    )


def test_authority_and_self_forbidden_path_conflicts_block():
    item = make_slice(
        authority_classes=("contained_process",),
        forbidden_paths=("backend/continuous_builder",),
    )
    result = analyze_conflicts(dependency_analysis(item), resources())
    assert (
        "authority_unavailable:contained_process"
        in result.results[0].blocked_reasons
    )
    assert "self_scope_conflict" in result.results[0].blocked_reasons


def test_forged_result_and_runtime_claims_are_rejected():
    result = analyze_conflicts(dependency_analysis(), resources())
    forged = replace(result.results[0], eligible=False)
    with pytest.raises(ConflictAnalysisError, match="forged"):
        replace(result, results=(forged,))
    with pytest.raises(ConflictAnalysisError, match="lease or dispatch"):
        replace(result, worker_dispatched=True)


def test_result_is_deterministic_immutable_and_nested_inputs_are_frozen():
    first = analyze_conflicts(dependency_analysis(), resources())
    second = analyze_conflicts(dependency_analysis(), resources())
    assert first.canonical_bytes() == second.canonical_bytes()
    with pytest.raises(FrozenInstanceError):
        first.results = ()
    value = resources(available_capabilities=["planning"])
    assert value.available_capabilities == ("planning",)
