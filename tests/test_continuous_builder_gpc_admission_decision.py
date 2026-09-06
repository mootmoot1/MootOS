"""Focused tests for GP-C6 admission decision / receipt + C7 tamper checks."""

from pathlib import Path

import pytest

from backend.continuous_builder.gpa_eval_schema import AUTHORITY_FLAGS
from backend.continuous_builder.gpb_decomposer import decompose_task_contract
from backend.continuous_builder.gpb_task_contract import create_frozen_task_contract
from backend.continuous_builder.gpc_admission_decision import (
    AdmissionDecisionError,
    admission_decision_cannot_execute,
    admission_never_auto_approves_main_merge,
    admit_capabilities,
)
from backend.continuous_builder.gpc_admission_input import create_admission_input
from backend.continuous_builder.gpc_capability_vocabulary import (
    OUTCOME_ALLOW_WITHIN_BOUND,
    OUTCOME_DENY,
    OUTCOME_ESCALATE,
    OUTCOME_INSUFFICIENT_EVIDENCE,
    OUTCOME_REQUIRE_HUMAN_APPROVAL,
    create_capability_request,
)
from backend.continuous_builder.system_model import build_system_model

TRUSTED_BASE = "33f7fe0cf24f1e5871d4b2950086730a6112b99b"
BASELINE = "a" * 64
REPO = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def model():
    return build_system_model(REPO, base_sha=TRUSTED_BASE)


def _contract(**overrides):
    values = dict(
        task_contract_id="tc_gpc_dec_001",
        base_sha=TRUSTED_BASE,
        architecture_baseline_sha256=BASELINE,
        taxonomy_class_id="narrow_bug_fix",
        goal="Admission decision fixture",
        intent_summary="Decide capabilities without executing",
        allowed_scope=("tests/fixtures/gpa_eval/nb_001/widget_counter.py",),
        forbidden_scope=("backend/continuous_builder/trusted_policy.py",),
        acceptance_criteria=("decision cannot execute",),
        budget_ceiling_wall_clock_seconds=600,
        budget_ceiling_input_tokens=10000,
        budget_ceiling_output_tokens=10000,
        risk_ceiling_indicators=("none",),
        required_gates=("unit_tests", "human_review"),
    )
    values.update(overrides)
    return create_frozen_task_contract(**values)


def _admit(model, contract, requests, decision_id="gpc_decision_test"):
    plan = decompose_task_contract(contract, model)
    # Rebind requests to live plan digests.
    rebound = []
    for idx, req in enumerate(requests):
        rebound.append(
            create_capability_request(
                request_id=req.request_id or f"req_{idx:02d}",
                capability_id=req.capability_id,
                task_contract_id=contract.task_contract_id,
                contract_sha256=contract.contract_sha256,
                plan_id=plan.plan_id,
                plan_sha256=plan.plan_sha256,
                requested_scope=tuple(req.requested_scope)
                or tuple(contract.allowed_scope),
                budget_wall_clock_seconds=req.budget_wall_clock_seconds,
                budget_input_tokens=req.budget_input_tokens,
                budget_output_tokens=req.budget_output_tokens,
                evidence_refs=tuple(req.evidence_refs),
                worker_safe_claim=req.worker_safe_claim,
                provider_id=req.provider_id,
                model_id=req.model_id,
                benchmark_score=req.benchmark_score,
            )
        )
    inp = create_admission_input(
        admission_input_id="ain_dec_001",
        contract=contract,
        plan=plan,
        capability_requests=tuple(rebound),
        system_model_sha256=model.model_sha256,
        system_model_version=model.model_version,
        expected_base_sha=TRUSTED_BASE,
    )
    return admit_capabilities(inp, decision_id=decision_id)


def _proto(**overrides):
    values = dict(
        request_id="req_proto_001",
        capability_id="cb.repo.read",
        task_contract_id="tc_gpc_dec_001",
        contract_sha256="a" * 64,
        plan_id="plan_tmp",
        plan_sha256="b" * 64,
        requested_scope=("tests/fixtures/gpa_eval/nb_001/widget_counter.py",),
        budget_wall_clock_seconds=100,
        budget_input_tokens=100,
        budget_output_tokens=100,
    )
    values.update(overrides)
    return create_capability_request(**values)


def test_read_only_admitted_within_bound(model):
    decision, receipt = _admit(model, _contract(), [_proto()])
    assert "cb.repo.read" in decision.admitted_within_bound
    assert decision.overall_outcome == OUTCOME_ALLOW_WITHIN_BOUND
    assert decision.execution_authorized is False
    assert decision.approved_to_execute is False
    assert decision.capability_runtime_granted is False
    assert receipt.approved_to_execute is False
    assert admission_decision_cannot_execute() is True
    for name in AUTHORITY_FLAGS:
        assert getattr(decision, name) is False


def test_bounded_write_within_scope(model):
    decision, _ = _admit(
        model,
        _contract(),
        [_proto(capability_id="cb.file.write_bounded", request_id="req_w")],
    )
    assert "cb.file.write_bounded" in decision.admitted_within_bound


def test_oos_write_denied(model):
    decision, _ = _admit(
        model,
        _contract(),
        [
            _proto(
                request_id="req_oos",
                capability_id="cb.file.write_bounded",
                requested_scope=(
                    "backend/continuous_builder/gpb_task_contract.py",
                ),
            )
        ],
    )
    assert "cb.file.write_bounded" in decision.denied
    assert decision.overall_outcome == OUTCOME_DENY


def test_tcb_adjacent_write_human_gated(model):
    path = "backend/continuous_builder/trusted_policy.py"
    decision, _ = _admit(
        model,
        _contract(
            allowed_scope=(path,),
            forbidden_scope=(),
            risk_ceiling_indicators=("tcb_adjacent",),
            taxonomy_class_id="tcb_adjacent_change",
        ),
        [
            _proto(
                request_id="req_tcb",
                capability_id="cb.file.write_bounded",
                requested_scope=(path,),
            )
        ],
    )
    assert "cb.file.write_bounded" not in decision.admitted_within_bound
    assert decision.overall_outcome in (
        OUTCOME_REQUIRE_HUMAN_APPROVAL,
        OUTCOME_ESCALATE,
        OUTCOME_DENY,
    )


def test_main_merge_never_auto_admitted(model):
    decision, _ = _admit(
        model,
        _contract(),
        [
            _proto(
                request_id="req_merge",
                capability_id="cb.main.merge",
                requested_scope=(),
            )
        ],
    )
    assert "cb.main.merge" not in decision.admitted_within_bound
    assert "cb.main.merge" in decision.human_gated or decision.overall_outcome == (
        OUTCOME_REQUIRE_HUMAN_APPROVAL
    )
    assert decision.main_merge_auto_approved is False
    assert admission_never_auto_approves_main_merge() is True


def test_unknown_capability_insufficient(model):
    decision, _ = _admit(
        model,
        _contract(),
        [
            _proto(
                request_id="req_unk",
                capability_id="cb.invented.superuser",
                operation="unknown",
                resource_class="unknown",
            )
        ],
    )
    assert decision.overall_outcome == OUTCOME_INSUFFICIENT_EVIDENCE
    assert "cb.invented.superuser" in decision.insufficient_evidence


def test_worker_provider_benchmark_never_grant(model):
    decision, _ = _admit(
        model,
        _contract(),
        [
            _proto(
                request_id="req_claim",
                capability_id="cb.credentials",
                worker_safe_claim=True,
                provider_id="claude",
                model_id="opus",
                benchmark_score=99.5,
            )
        ],
    )
    assert "cb.credentials" not in decision.admitted_within_bound
    row = decision.per_capability[0]
    assert "worker_safe_claim_ignored" in row.reason_codes
    assert "provider_identity_ignored" in row.reason_codes
    assert "benchmark_score_ignored" in row.reason_codes


def test_budget_increase_denied(model):
    decision, _ = _admit(
        model,
        _contract(),
        [
            _proto(
                request_id="req_budg",
                capability_id="cb.file.write_bounded",
                budget_wall_clock_seconds=99999,
            )
        ],
    )
    assert "cb.file.write_bounded" in decision.denied


def test_gate_removed_marker_denied(model):
    decision, _ = _admit(
        model,
        _contract(),
        [
            _proto(
                request_id="req_gate",
                capability_id="cb.file.write_bounded",
                evidence_refs=("gate_removed",),
            )
        ],
    )
    assert "cb.file.write_bounded" in decision.denied


def test_deterministic_decision_digest(model):
    a, _ = _admit(model, _contract(), [_proto()], decision_id="gpc_decision_det")
    b, _ = _admit(model, _contract(), [_proto()], decision_id="gpc_decision_det")
    assert a.decision_sha256 == b.decision_sha256


def test_forged_decision_digest_rejected(model):
    import dataclasses

    decision, _ = _admit(model, _contract(), [_proto()])
    with pytest.raises(AdmissionDecisionError, match="decision_sha256"):
        type(decision)(
            **{
                f.name: (
                    "0" * 64
                    if f.name == "decision_sha256"
                    else getattr(decision, f.name)
                )
                for f in dataclasses.fields(decision)
                if f.name != "_token"
            },
            _token=decision._token,
        )
