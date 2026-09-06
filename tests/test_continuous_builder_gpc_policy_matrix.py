"""Focused tests for GP-C3 deterministic policy matrix."""

from backend.continuous_builder.gpa_eval_schema import AUTHORITY_FLAGS
from backend.continuous_builder.gpc_capability_vocabulary import (
    OUTCOME_ALLOW_WITHIN_BOUND,
    OUTCOME_INSUFFICIENT_EVIDENCE,
    OUTCOME_REQUIRE_HUMAN_APPROVAL,
)
from backend.continuous_builder.gpc_policy_matrix import (
    create_gpc_policy_matrix_v1,
    lookup_matrix_outcome,
    policy_matrix_is_default_deny,
)


def test_matrix_sealed_zero_authority_stable():
    a = create_gpc_policy_matrix_v1()
    b = create_gpc_policy_matrix_v1()
    assert a.matrix_sha256 == b.matrix_sha256
    for name in AUTHORITY_FLAGS:
        assert getattr(a, name) is False
    assert a.execution_authorized is False
    assert policy_matrix_is_default_deny() is True


def test_unknown_never_allow():
    matrix = create_gpc_policy_matrix_v1()
    outcome, reason, human, rule_id = lookup_matrix_outcome(
        matrix, "cb.invented.superuser"
    )
    assert outcome == OUTCOME_INSUFFICIENT_EVIDENCE
    assert "unknown" in reason
    assert human is True
    assert rule_id


def test_main_merge_human_gated():
    matrix = create_gpc_policy_matrix_v1()
    outcome, _, human, _ = lookup_matrix_outcome(matrix, "cb.main.merge")
    assert outcome == OUTCOME_REQUIRE_HUMAN_APPROVAL
    assert human is True


def test_bounded_read_default_allow():
    matrix = create_gpc_policy_matrix_v1()
    outcome, _, human, _ = lookup_matrix_outcome(matrix, "cb.repo.read")
    assert outcome == OUTCOME_ALLOW_WITHIN_BOUND
    assert human is False
