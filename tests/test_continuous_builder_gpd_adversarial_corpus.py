"""GP-D9 adversarial / failure-injection corpus tests + GP-B/C bindings."""

from pathlib import Path

import pytest

from backend.continuous_builder.gpb_decomposer import decompose_task_contract
from backend.continuous_builder.gpb_task_contract import create_frozen_task_contract
from backend.continuous_builder.gpc_admission_decision import admit_capabilities
from backend.continuous_builder.gpc_admission_input import create_admission_input
from backend.continuous_builder.gpc_capability_vocabulary import (
    create_capability_request,
)
from backend.continuous_builder.gpd_eval_corpus import (
    CORPUS_VERSION,
    adversarial_cases,
    corpus_digest,
)
from backend.continuous_builder.gpd_failure import classify_failure
from backend.continuous_builder.gpd_job_events import create_job_event
from backend.continuous_builder.gpd_job_header import create_durable_job_header
from backend.continuous_builder.gpd_job_store import JobLedgerStore
from backend.continuous_builder.gpd_recovery import reconstruct_job
from backend.continuous_builder.system_model import build_system_model
from backend.continuous_builder.trusted_policy import (
    AUTHORITY_FLAGS,
    create_trusted_policy_snapshot,
)

BASE = "48233394d4ccce88244adc5c7133efea92df60fb"
TS = "2026-09-06T22:00:00+00:00"
REPO = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def model():
    return build_system_model(REPO, base_sha=BASE)


def test_corpus_nonempty_and_digested():
    cases = adversarial_cases()
    assert len(cases) >= 15
    assert CORPUS_VERSION.startswith("gpd-")
    assert len(corpus_digest()) == 64


def test_failure_taxonomy_reuses_supervisor_vocab():
    info = classify_failure("termination_uncertain")
    assert info["requires_reconcile"] is True
    info2 = classify_failure("stalled")
    assert info2["retryable"] is True


def test_gpb_gpc_binding_into_job_header(model, tmp_path):
    snapshot = create_trusted_policy_snapshot()
    contract = create_frozen_task_contract(
        task_contract_id="tc_gpd_bind_001",
        base_sha=BASE,
        architecture_baseline_sha256="a" * 64,
        taxonomy_class_id="narrow_bug_fix",
        goal="Bind GP-B/C into GP-D header",
        intent_summary="Admission evidence only; no launch",
        allowed_scope=("tests/fixtures/gpa_eval/nb_001/widget_counter.py",),
        forbidden_scope=("backend/continuous_builder/trusted_policy.py",),
        acceptance_criteria=("header binds digests",),
        budget_ceiling_wall_clock_seconds=600,
        budget_ceiling_input_tokens=10000,
        budget_ceiling_output_tokens=10000,
        risk_ceiling_indicators=("none",),
        required_gates=("human_review", "unit_tests"),
    )
    plan = decompose_task_contract(contract, model)
    req = create_capability_request(
        request_id="req_00",
        capability_id="cb.repo.read",
        task_contract_id=contract.task_contract_id,
        contract_sha256=contract.contract_sha256,
        plan_id=plan.plan_id,
        plan_sha256=plan.plan_sha256,
        requested_scope=tuple(contract.allowed_scope),
        budget_wall_clock_seconds=600,
        budget_input_tokens=10000,
        budget_output_tokens=10000,
    )
    admission_input = create_admission_input(
        admission_input_id="ain_gpd_bind_001",
        contract=contract,
        plan=plan,
        capability_requests=(req,),
        system_model_sha256=model.model_sha256,
        system_model_version=model.model_version,
        expected_base_sha=BASE,
    )
    decision, receipt = admit_capabilities(
        admission_input, decision_id="gpc_decision_gpd_bind"
    )
    header = create_durable_job_header(
        job_id="job_gpd_bind",
        repository_identity="mootmoot1/MootOS",
        base_sha=contract.base_sha,
        task_contract_id=contract.task_contract_id,
        task_contract_sha256=contract.contract_sha256,
        execution_plan_id=plan.plan_id,
        execution_plan_sha256=plan.plan_sha256,
        admission_decision_id=decision.decision_id,
        admission_decision_sha256=decision.decision_sha256,
        architecture_baseline_sha256=contract.architecture_baseline_sha256,
        trusted_policy_version=snapshot.policy_version,
        tcb_registry_sha256=snapshot.registry_sha256,
        tcb_snapshot_sha256=snapshot.snapshot_sha256,
        approved_scope_ceiling=tuple(contract.allowed_scope),
        forbidden_scope=tuple(contract.forbidden_scope),
        admitted_capability_ids=("cb.repo.read",),
        budget_ceiling_wall_clock_seconds=600,
        required_gates=tuple(contract.required_gates),
        logical_order=1,
        created_at=TS,
    )
    for name in AUTHORITY_FLAGS:
        assert getattr(header, name) is False
    assert header.execution_authorized is False
    assert "human_review" in header.required_gates

    store = JobLedgerStore(tmp_path / "ledger")
    store.write_header(header)
    e1 = create_job_event(
        event_id="evt_0001", job_id=header.job_id, sequence=1,
        event_kind="job_created", actor_kind="system", actor_id="system_gpd",
        reason_code="create", created_at=TS,
    )
    store.append_event(e1)
    view = reconstruct_job(
        store,
        header.job_id,
        expected_contract_sha256=contract.contract_sha256,
        expected_admission_sha256=decision.decision_sha256,
        expected_tcb_registry_sha256=snapshot.registry_sha256,
        expected_policy_version=snapshot.policy_version,
    )
    assert view.human_gates == header.required_gates
    assert view.header.merge_authorized is False
    assert view.header.main_advancement_authorized is False
