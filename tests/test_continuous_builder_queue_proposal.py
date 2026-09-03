"""Tests for pure Continuous Builder queue proposals."""

from dataclasses import FrozenInstanceError, replace

import pytest

from backend.continuous_builder.blueprint_parser import parse_blueprint
from backend.continuous_builder.queue_proposal import (
    CandidateSliceProposal,
    QueueProposalError,
    ReadinessInput,
    TransitionProposal,
    propose_candidates,
)
from test_continuous_builder_blueprint import make_blueprint


def parsed_blueprint():
    return parse_blueprint(make_blueprint().canonical_bytes())


def test_candidates_bind_exact_blueprint_and_remain_proposed():
    parsed = parsed_blueprint()
    candidates = propose_candidates(parsed, {
        "CB-001": ReadinessInput(
            available_capabilities=("planning",), conflict_free=True,
            resource_budget_available=True, durable_eligibility_sequence=7,
        ),
    })
    assert candidates[0].blueprint_digest == parsed.content_sha256
    assert candidates[0].declared_state == "proposed"
    assert candidates[0].readiness_input.durable_eligibility_sequence == 7


def test_transition_is_deterministic_immutable_and_never_applied():
    candidate = propose_candidates(parsed_blueprint())[0]
    proposal = TransitionProposal(candidate, "no_change", ("not_evaluated",))
    assert proposal.canonical_bytes() == proposal.canonical_bytes()
    assert proposal.persisted is False
    assert proposal.queue_state_changed is False
    with pytest.raises(FrozenInstanceError):
        proposal.intent = "propose_ready"


def test_forged_mutation_or_persistence_claim_is_rejected():
    candidate = propose_candidates(parsed_blueprint())[0]
    proposal = TransitionProposal(candidate, "no_change", ("not_evaluated",))
    with pytest.raises(QueueProposalError, match="mutate or persist"):
        replace(proposal, persisted=True)
    with pytest.raises(QueueProposalError, match="mutate or persist"):
        replace(proposal, queue_state_changed=True)


def test_invalid_states_intents_and_readiness_fail_closed():
    candidate = propose_candidates(parsed_blueprint())[0]
    with pytest.raises(QueueProposalError, match="candidate state"):
        replace(candidate, declared_state="running")
    with pytest.raises(QueueProposalError, match="transition intent"):
        TransitionProposal(candidate, "execute", ("bad",))
    with pytest.raises(QueueProposalError, match="unknown slice"):
        propose_candidates(parsed_blueprint(), {"missing": ReadinessInput()})


def test_nested_inputs_are_frozen_and_have_no_runtime_objects():
    readiness = ReadinessInput(available_capabilities=["planning"])
    assert readiness.available_capabilities == ("planning",)
    candidate = CandidateSliceProposal(
        "a" * 64, "CB-001", "1", "evaluate", "proposed", readiness,
    )
    assert set(candidate.to_dict()) == {
        "blueprint_digest", "declared_state", "lifecycle_intent",
        "readiness_input", "slice_id", "slice_version",
    }
