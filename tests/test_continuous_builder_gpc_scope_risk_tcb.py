"""Focused tests for GP-C4 scope / risk / TCB interaction."""

from backend.continuous_builder.gpc_capability_vocabulary import (
    OUTCOME_ALLOW_WITHIN_BOUND,
    OUTCOME_DENY,
    OUTCOME_ESCALATE,
    OUTCOME_REQUIRE_HUMAN_APPROVAL,
)
from backend.continuous_builder.gpc_scope_risk_tcb import evaluate_scope_risk_tcb


def test_out_of_scope_write_denied():
    result = evaluate_scope_risk_tcb(
        capability_id="cb.file.write_bounded",
        requested_scope=("backend/continuous_builder/gpb_task_contract.py",),
        allowed_scope=("tests/fixtures/gpa_eval/nb_001/widget_counter.py",),
        forbidden_scope=(),
        risk_ceiling_indicators=("none",),
        required_gates=("unit_tests",),
        plan_requires_escalation=False,
        plan_escalation_reasons=(),
        base_matrix_outcome=OUTCOME_ALLOW_WITHIN_BOUND,
    )
    assert result.outcome == OUTCOME_DENY
    assert "out_of_scope_path" in result.reason_codes


def test_forbidden_path_denied_even_if_low_risk():
    path = "backend/continuous_builder/trusted_policy.py"
    result = evaluate_scope_risk_tcb(
        capability_id="cb.file.write_bounded",
        requested_scope=(path,),
        allowed_scope=(path,),
        forbidden_scope=(path,),
        risk_ceiling_indicators=("none",),
        required_gates=("unit_tests",),
        plan_requires_escalation=False,
        plan_escalation_reasons=(),
        base_matrix_outcome=OUTCOME_ALLOW_WITHIN_BOUND,
    )
    assert result.outcome == OUTCOME_DENY
    assert "forbidden_scope_touch" in result.reason_codes
    assert "low_risk_does_not_override_deny" in result.reason_codes


def test_tcb_path_not_ordinary_write():
    path = "backend/continuous_builder/trusted_policy.py"
    result = evaluate_scope_risk_tcb(
        capability_id="cb.file.write_bounded",
        requested_scope=(path,),
        allowed_scope=(path,),
        forbidden_scope=(),
        risk_ceiling_indicators=("none",),
        required_gates=("unit_tests",),
        plan_requires_escalation=False,
        plan_escalation_reasons=(),
        base_matrix_outcome=OUTCOME_ALLOW_WITHIN_BOUND,
    )
    assert result.outcome == OUTCOME_REQUIRE_HUMAN_APPROVAL
    assert "tcb_path_touch" in result.reason_codes
    assert path in result.tcb_paths_touched


def test_gpb_escalation_blocks_auto_allow():
    result = evaluate_scope_risk_tcb(
        capability_id="cb.repo.read",
        requested_scope=("tests/fixtures/gpa_eval/nb_001/widget_counter.py",),
        allowed_scope=("tests/fixtures/gpa_eval/nb_001/widget_counter.py",),
        forbidden_scope=(),
        risk_ceiling_indicators=("none",),
        required_gates=("unit_tests",),
        plan_requires_escalation=True,
        plan_escalation_reasons=("tcb_adjacent_scope",),
        base_matrix_outcome=OUTCOME_ALLOW_WITHIN_BOUND,
    )
    assert result.outcome == OUTCOME_ESCALATE
    assert "gpb_escalation_blocks_auto_allow" in result.reason_codes
