"""Tests for deterministic Continuous Builder priority policy."""

from dataclasses import FrozenInstanceError, replace

import pytest

from backend.continuous_builder.blueprint_parser import parse_blueprint
from backend.continuous_builder.conflict_analysis import (
    EligibilityResources,
    analyze_conflicts,
)
from backend.continuous_builder.dependency_analysis import analyze_dependencies
from backend.continuous_builder.priority_policy import (
    POLICY_VERSION,
    PriorityPolicyError,
    rank_eligible_slices,
)
from backend.continuous_builder.queue_proposal import (
    ReadinessInput,
    propose_candidates,
)
from test_continuous_builder_blueprint import make_blueprint, make_slice


def ranked(slices, sequences=None, advisory=()):
    parsed = parse_blueprint(make_blueprint(slices=slices).canonical_bytes())
    readiness = {
        key: ReadinessInput(durable_eligibility_sequence=value)
        for key, value in (sequences or {}).items()
    }
    dependencies = analyze_dependencies(
        parsed, propose_candidates(parsed, readiness)
    )
    capabilities = tuple(sorted({
        capability for item in slices
        for capability in item.requested_capabilities
    }))
    conflicts = analyze_conflicts(
        dependencies, EligibilityResources(capabilities, ())
    )
    return rank_eligible_slices(conflicts, advisory)


def test_priority_class_then_unblocking_then_sequence_then_id():
    slices = (
        make_slice(slice_id="CB-A", priority_class="normal"),
        make_slice(slice_id="CB-B", priority_class="high"),
        make_slice(
            slice_id="CB-C", priority_class="normal",
            hard_dependencies=("CB-A",),
        ),
        make_slice(slice_id="cb-d", priority_class="normal"),
    )
    result = ranked(slices, {"CB-A": 9, "CB-B": 99, "cb-d": 1})
    assert result.ranked_slice_ids == ("CB-B", "CB-A", "cb-d")
    assert result.policy_version == POLICY_VERSION


def test_model_advice_is_recorded_but_cannot_change_ranking():
    slices = (make_slice(slice_id="CB-A"), make_slice(slice_id="CB-B"))
    without = ranked(slices)
    advised = ranked(slices, advisory=("Prefer CB-B",))
    assert without.ranked_slice_ids == advised.ranked_slice_ids
    assert advised.advisory_metadata == ("Prefer CB-B",)
    assert advised.model_advice_applied is False


def test_forged_rank_policy_or_model_authority_fails_closed():
    result = ranked((make_slice(),))
    with pytest.raises(PriorityPolicyError, match="forged"):
        replace(result, entries=(replace(result.entries[0], rank=9),))
    with pytest.raises(PriorityPolicyError, match="policy version"):
        replace(result, policy_version="model-v1")
    with pytest.raises(PriorityPolicyError, match="model advice"):
        replace(result, model_advice_applied=True)


def test_ranking_is_deterministic_immutable_and_bounded():
    slices = (make_slice(slice_id="CB-B"), make_slice(slice_id="CB-A"))
    first = ranked(slices)
    second = ranked(tuple(reversed(slices)))
    assert first.ranked_slice_ids == second.ranked_slice_ids
    assert first.canonical_bytes() == ranked(slices).canonical_bytes()
    with pytest.raises(FrozenInstanceError):
        first.entries = ()
    with pytest.raises(PriorityPolicyError, match="advisory"):
        ranked(slices, advisory=("x" * 513,))
