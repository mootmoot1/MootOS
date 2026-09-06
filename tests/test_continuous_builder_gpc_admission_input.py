"""Focused tests for GP-C2 trusted admission input binding."""

from pathlib import Path

import pytest

from backend.continuous_builder.gpa_eval_schema import AUTHORITY_FLAGS
from backend.continuous_builder.gpb_decomposer import decompose_task_contract
from backend.continuous_builder.gpb_task_contract import create_frozen_task_contract
from backend.continuous_builder.gpc_admission_input import (
    AdmissionInputError,
    admission_input_is_proposal_only,
    create_admission_input,
)
from backend.continuous_builder.gpc_capability_vocabulary import (
    create_capability_request,
    create_gpc_capability_vocabulary_v1,
)
from backend.continuous_builder.system_model import build_system_model
from backend.continuous_builder.trusted_policy import create_mootos_tcb_registry_v1

TRUSTED_BASE = "33f7fe0cf24f1e5871d4b2950086730a6112b99b"
BASELINE = "a" * 64
REPO = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def model():
    return build_system_model(REPO, base_sha=TRUSTED_BASE)


def _contract(**overrides):
    values = dict(
        task_contract_id="tc_gpc_input_001",
        base_sha=TRUSTED_BASE,
        architecture_baseline_sha256=BASELINE,
        taxonomy_class_id="narrow_bug_fix",
        goal="Bounded read/write admission fixture",
        intent_summary="Seal admission input for GP-C",
        allowed_scope=("tests/fixtures/gpa_eval/nb_001/widget_counter.py",),
        forbidden_scope=("backend/continuous_builder/trusted_policy.py",),
        acceptance_criteria=("no TCB mutation",),
        budget_ceiling_wall_clock_seconds=600,
        budget_ceiling_input_tokens=10000,
        risk_ceiling_indicators=("none",),
        required_gates=("unit_tests", "human_review"),
    )
    values.update(overrides)
    return create_frozen_task_contract(**values)


def _requests(contract, plan, *capability_ids):
    out = []
    for idx, cid in enumerate(capability_ids):
        out.append(
            create_capability_request(
                request_id=f"req_gpc_{idx:02d}",
                capability_id=cid,
                task_contract_id=contract.task_contract_id,
                contract_sha256=contract.contract_sha256,
                plan_id=plan.plan_id,
                plan_sha256=plan.plan_sha256,
                requested_scope=tuple(contract.allowed_scope),
            )
        )
    return tuple(out)


def test_binds_contract_plan_tcb_vocabulary(model):
    contract = _contract()
    plan = decompose_task_contract(contract, model)
    registry = create_mootos_tcb_registry_v1()
    vocab = create_gpc_capability_vocabulary_v1()
    inp = create_admission_input(
        admission_input_id="ain_gpc_001",
        contract=contract,
        plan=plan,
        capability_requests=_requests(
            contract, plan, "cb.repo.read", "cb.file.write_bounded"
        ),
        system_model_sha256=model.model_sha256,
        system_model_version=model.model_version,
        expected_base_sha=TRUSTED_BASE,
        expected_tcb_registry_sha256=registry.registry_sha256,
        expected_vocabulary_sha256=vocab.vocabulary_sha256,
    )
    assert inp.contract_sha256 == contract.contract_sha256
    assert inp.plan_sha256 == plan.plan_sha256
    assert inp.tcb_registry_sha256 == registry.registry_sha256
    assert inp.vocabulary_sha256 == vocab.vocabulary_sha256
    assert inp.capability_granted is False
    assert admission_input_is_proposal_only() is True
    for name in AUTHORITY_FLAGS:
        assert getattr(inp, name) is False


def test_rejects_stale_base_sha(model):
    contract = _contract()
    plan = decompose_task_contract(contract, model)
    with pytest.raises(AdmissionInputError, match="base_sha"):
        create_admission_input(
            admission_input_id="ain_stale",
            contract=contract,
            plan=plan,
            capability_requests=_requests(contract, plan, "cb.repo.read"),
            expected_base_sha="0" * 40,
        )


def test_rejects_request_contract_digest_mismatch(model):
    contract = _contract()
    plan = decompose_task_contract(contract, model)
    bad = create_capability_request(
        request_id="req_bad",
        capability_id="cb.repo.read",
        task_contract_id=contract.task_contract_id,
        contract_sha256="f" * 64,
        plan_id=plan.plan_id,
        plan_sha256=plan.plan_sha256,
        requested_scope=tuple(contract.allowed_scope),
    )
    with pytest.raises(AdmissionInputError, match="contract digest"):
        create_admission_input(
            admission_input_id="ain_mismatch",
            contract=contract,
            plan=plan,
            capability_requests=(bad,),
        )


def test_rejects_tcb_registry_drift(model):
    contract = _contract()
    plan = decompose_task_contract(contract, model)
    with pytest.raises(AdmissionInputError, match="tcb_registry"):
        create_admission_input(
            admission_input_id="ain_tcb_drift",
            contract=contract,
            plan=plan,
            capability_requests=_requests(contract, plan, "cb.repo.read"),
            expected_tcb_registry_sha256="0" * 64,
        )
