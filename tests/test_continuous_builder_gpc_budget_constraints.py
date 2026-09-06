"""Focused tests for GP-C5 budget / constraint checks."""

from backend.continuous_builder.gpc_budget_constraints import (
    evaluate_budget_constraints,
)
from backend.continuous_builder.gpc_capability_vocabulary import (
    OUTCOME_ALLOW_WITHIN_BOUND,
    OUTCOME_DENY,
    OUTCOME_REQUIRE_HUMAN_APPROVAL,
    create_capability_request,
)


def _req(**overrides):
    values = dict(
        request_id="req_budget_001",
        capability_id="cb.file.write_bounded",
        task_contract_id="tc_budget_001",
        contract_sha256="a" * 64,
        plan_id="plan_budget_001",
        plan_sha256="b" * 64,
        requested_scope=("tests/fixtures/gpa_eval/nb_001/widget_counter.py",),
        budget_wall_clock_seconds=100,
        budget_input_tokens=1000,
        budget_output_tokens=1000,
    )
    values.update(overrides)
    return create_capability_request(**values)


def test_within_ceiling_passthrough():
    result = evaluate_budget_constraints(
        request=_req(),
        budget_ceiling_wall_clock_seconds=600,
        budget_ceiling_input_tokens=10000,
        budget_ceiling_output_tokens=10000,
        budget_ceiling_cost_usd_cents=None,
        base_outcome=OUTCOME_ALLOW_WITHIN_BOUND,
    )
    assert result.outcome == OUTCOME_ALLOW_WITHIN_BOUND
    assert "budget_within_ceiling" in result.reason_codes


def test_exceeds_ceiling_denied():
    result = evaluate_budget_constraints(
        request=_req(budget_wall_clock_seconds=9999),
        budget_ceiling_wall_clock_seconds=600,
        budget_ceiling_input_tokens=10000,
        budget_ceiling_output_tokens=10000,
        budget_ceiling_cost_usd_cents=None,
        base_outcome=OUTCOME_ALLOW_WITHIN_BOUND,
    )
    assert result.outcome == OUTCOME_DENY
    assert "exceeds_ceiling_budget_wall_clock_seconds" in result.reason_codes


def test_explicit_budget_increase_marker_denied():
    result = evaluate_budget_constraints(
        request=_req(evidence_refs=("budget_increase:wall_clock",)),
        budget_ceiling_wall_clock_seconds=600,
        budget_ceiling_input_tokens=None,
        budget_ceiling_output_tokens=None,
        budget_ceiling_cost_usd_cents=None,
        base_outcome=OUTCOME_ALLOW_WITHIN_BOUND,
    )
    assert result.outcome == OUTCOME_DENY
    assert "explicit_budget_increase_request" in result.reason_codes


def test_missing_request_budget_human_gates_allow():
    result = evaluate_budget_constraints(
        request=_req(budget_wall_clock_seconds=None),
        budget_ceiling_wall_clock_seconds=600,
        budget_ceiling_input_tokens=None,
        budget_ceiling_output_tokens=None,
        budget_ceiling_cost_usd_cents=None,
        base_outcome=OUTCOME_ALLOW_WITHIN_BOUND,
    )
    assert result.outcome == OUTCOME_REQUIRE_HUMAN_APPROVAL
