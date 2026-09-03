"""Cross-cutting explicit bounds for pure Continuous Builder models."""

import pytest

from backend.continuous_builder.blueprint_parser import parse_blueprint
from backend.continuous_builder.conflict_analysis import (
    ConflictAnalysisError,
    EligibilityResources,
    analyze_conflicts,
)
from backend.continuous_builder.dependency_analysis import (
    DependencyAnalysisError,
    DependencyReceipt,
    analyze_dependencies,
)
from backend.continuous_builder.priority_policy import rank_eligible_slices
from backend.continuous_builder.queue_proposal import (
    QueueProposalError,
    ReadinessInput,
    propose_candidates,
)
from test_continuous_builder_blueprint import make_blueprint


def analysis_chain():
    parsed = parse_blueprint(make_blueprint().canonical_bytes())
    dependencies = analyze_dependencies(parsed, propose_candidates(parsed))
    conflicts = analyze_conflicts(
        dependencies, EligibilityResources(("planning",), ())
    )
    return dependencies, conflicts, rank_eligible_slices(conflicts)


def test_queue_metadata_enforces_utf8_byte_bound_and_digest_shape():
    with pytest.raises(QueueProposalError, match="malformed or excessive"):
        ReadinessInput(available_capabilities=("é" * 129,))
    parsed = parse_blueprint(make_blueprint().canonical_bytes())
    candidate = propose_candidates(parsed)[0]
    with pytest.raises(QueueProposalError, match="digest is malformed"):
        type(candidate)(
            "invalid", candidate.slice_id, candidate.slice_version,
            candidate.lifecycle_intent, candidate.declared_state,
            candidate.readiness_input,
        )


def test_dependency_receipt_identity_has_explicit_byte_bound():
    with pytest.raises(DependencyAnalysisError, match="identity"):
        DependencyReceipt("é" * 129, "CB-001", "1", True, True)


def test_resource_metadata_has_explicit_byte_bound():
    with pytest.raises(ConflictAnalysisError, match="malformed or excessive"):
        EligibilityResources(("é" * 129,), ())


def test_each_derived_serializer_is_deterministic_and_bounded():
    dependencies, conflicts, priority = analysis_chain()
    for result in (dependencies, conflicts, priority):
        first = result.canonical_bytes()
        assert first == result.canonical_bytes()
        assert len(first) <= 256 * 1024
