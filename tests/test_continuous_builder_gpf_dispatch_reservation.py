"""GP-F1 -- Durable Dispatch Reservation / Replay Prevention tests."""

import dataclasses

import pytest

from backend.continuous_builder.context_engine import (
    assemble_context_package,
    seal_context_task_request,
)
from backend.continuous_builder.system_model import build_system_model
from backend.continuous_builder.gpb_task_contract import create_frozen_task_contract
from backend.continuous_builder.gpb_decomposer import decompose_task_contract
from backend.continuous_builder.gpc_capability_vocabulary import (
    create_capability_request,
)
from backend.continuous_builder.gpc_admission_input import create_admission_input
from backend.continuous_builder.gpc_admission_decision import admit_capabilities
from backend.continuous_builder.gpd_job_header import create_durable_job_header
from backend.continuous_builder.gpd_attempt_ledger import create_attempt_record
from backend.continuous_builder.gpd_job_store import JobLedgerStore, JobStoreError
from backend.continuous_builder.gpe_protocol import (
    BUDGET_FIELDS,
    create_slice_job_correlation,
    create_worker_request,
)
from backend.continuous_builder.gpf_dispatch_reservation import (
    DispatchReservation,
    DispatchReservationError,
    classify_reservation_attempt,
    create_dispatch_reservation,
    dispatch_reservation_grants_no_capability,
    reseal_dispatch_reservation_from_storage,
)

BASE = "c" * 40
TS = "2026-09-06T22:00:00+00:00"


def _forge(instance, **changes):
    forged = object.__new__(type(instance))
    for item in dataclasses.fields(instance):
        object.__setattr__(
            forged,
            item.name,
            changes.get(item.name, getattr(instance, item.name)),
        )
    return forged


def _fields(instance):
    return {
        item.name: getattr(instance, item.name)
        for item in dataclasses.fields(instance)
    }


@pytest.fixture
def inputs(tmp_path):
    repo = tmp_path / "repo"
    (repo / "backend").mkdir(parents=True)
    (repo / "backend/widget.py").write_text("VALUE = 1\n")
    model = build_system_model(repo, base_sha=BASE)
    contract = create_frozen_task_contract(
        task_contract_id="tc_gpf",
        base_sha=BASE,
        architecture_baseline_sha256="a" * 64,
        taxonomy_class_id="narrow_bug_fix",
        goal="Inspect widget",
        intent_summary="Bounded protocol fixture",
        allowed_scope=("backend/widget.py",),
        forbidden_scope=("data",),
        acceptance_criteria=("Return proposed evidence",),
        budget_ceiling_wall_clock_seconds=600,
        budget_ceiling_input_tokens=10000,
        budget_ceiling_output_tokens=10000,
        required_gates=("human_review", "unit_tests"),
        risk_ceiling_indicators=("none",),
    )
    plan = decompose_task_contract(contract, model)
    requests = tuple(
        create_capability_request(
            request_id="cap_" + str(i),
            capability_id=cap,
            task_contract_id=contract.task_contract_id,
            contract_sha256=contract.contract_sha256,
            plan_id=plan.plan_id,
            plan_sha256=plan.plan_sha256,
            requested_scope=contract.allowed_scope,
            budget_wall_clock_seconds=30,
            budget_input_tokens=100,
            budget_output_tokens=100,
        )
        for i, cap in enumerate(("cb.repo.read", "cb.main.merge"))
    )
    admission_input = create_admission_input(
        admission_input_id="ain_gpf",
        contract=contract,
        plan=plan,
        capability_requests=requests,
        system_model_sha256=model.model_sha256,
        system_model_version=model.model_version,
        expected_base_sha=BASE,
    )
    admission, _ = admit_capabilities(admission_input, decision_id="admit_gpf")
    header = create_durable_job_header(
        job_id="job_gpf",
        repository_identity=contract.repository_identity,
        base_sha=BASE,
        task_contract_id=contract.task_contract_id,
        task_contract_sha256=contract.contract_sha256,
        execution_plan_id=plan.plan_id,
        execution_plan_sha256=plan.plan_sha256,
        admission_decision_id=admission.decision_id,
        admission_decision_sha256=admission.decision_sha256,
        architecture_baseline_sha256=contract.architecture_baseline_sha256,
        trusted_policy_version=admission.trusted_policy_version,
        tcb_registry_sha256=admission.tcb_registry_sha256,
        tcb_snapshot_sha256=admission.tcb_snapshot_sha256,
        approved_scope_ceiling=contract.allowed_scope,
        forbidden_scope=contract.forbidden_scope,
        admitted_capability_ids=admission.admitted_within_bound,
        required_gates=contract.required_gates,
        logical_order=1,
        created_at=TS,
        **{name: getattr(contract, name) for name in BUDGET_FIELDS},
    )
    attempt = create_attempt_record(
        attempt_id="attempt_gpf_1",
        job_id=header.job_id,
        attempt_number=1,
        owner_id="supervisor",
        started_at=TS,
        status="started",
        header_sha256=header.header_sha256,
    )
    ce_request = seal_context_task_request(
        task_id="context_gpf",
        base_sha=BASE,
        objective=contract.goal,
        allowed_paths=contract.allowed_scope,
        seed_paths=contract.allowed_scope,
    )
    package, _ = assemble_context_package(repo, ce_request, model)
    correlation = create_slice_job_correlation(
        header=header,
        blueprint_id="blueprint_gpf",
        blueprint_sha256="b" * 64,
        slice_id="slice_gpf",
    )
    return dict(
        header=header,
        attempt=attempt,
        contract=contract,
        plan=plan,
        admission=admission,
        admission_input=admission_input,
        package=package,
        correlation=correlation,
    )


def _second_attempt(inputs):
    """A retry: a brand new GP-D attempt identity for the same job."""
    values = inputs["attempt"].to_dict()
    values.pop("attempt_sha256")
    values.update(
        attempt_id="attempt_gpf_2",
        attempt_number=2,
        prior_attempt_id=inputs["attempt"].attempt_id,
    )
    return create_attempt_record(**values)


def test_reservation_deterministic_and_digest_bound(inputs):
    request = create_worker_request(**inputs)
    first = create_dispatch_reservation(request=request, reserved_at=TS)
    second = create_dispatch_reservation(request=request, reserved_at=TS)
    assert first.reservation_sha256 == second.reservation_sha256
    assert first.to_dict() == second.to_dict()
    assert first.job_id == request.job_id
    assert first.attempt_id == request.attempt_id
    assert first.request_id == request.request_id
    assert first.request_sha256 == request.digest


def test_reservation_zero_authority(inputs):
    request = create_worker_request(**inputs)
    reservation = create_dispatch_reservation(request=request, reserved_at=TS)
    for name in (
        "dispatch_authorized",
        "publication_authorized",
        "queue_transition_authorized",
        "github_authorized",
        "merge_authorized",
        "main_advancement_authorized",
        "result_trusted",
        "worker_output_trusted",
    ):
        assert getattr(reservation, name) is False


def test_new_write_then_identical_write_is_replay(tmp_path, inputs):
    store = JobLedgerStore(tmp_path / "ledger")
    store.write_header(inputs["header"])
    store.append_attempt(inputs["attempt"])
    request = create_worker_request(**inputs)
    reservation = create_dispatch_reservation(request=request, reserved_at=TS)

    first, outcome_1 = store.write_dispatch_reservation(reservation)
    assert outcome_1 == "new"
    second, outcome_2 = store.write_dispatch_reservation(reservation)
    assert outcome_2 == "replay"
    assert first.reservation_sha256 == second.reservation_sha256


def test_conflicting_packet_same_attempt_fails_closed(tmp_path, inputs):
    store = JobLedgerStore(tmp_path / "ledger")
    store.write_header(inputs["header"])
    store.append_attempt(inputs["attempt"])
    request = create_worker_request(**inputs)
    reservation = create_dispatch_reservation(request=request, reserved_at=TS)
    store.write_dispatch_reservation(reservation)

    conflicting = _forge(reservation, request_sha256="f" * 64)
    raw = {
        k: v for k, v in _fields(conflicting).items()
        if k not in ("_token", "reservation_sha256")
    }
    conflicting = reseal_dispatch_reservation_from_storage(**raw)
    with pytest.raises(JobStoreError, match="conflicting"):
        store.write_dispatch_reservation(conflicting)


def test_restart_preserves_reservation(tmp_path, inputs):
    root = tmp_path / "ledger"
    store = JobLedgerStore(root)
    store.write_header(inputs["header"])
    store.append_attempt(inputs["attempt"])
    request = create_worker_request(**inputs)
    reservation = create_dispatch_reservation(request=request, reserved_at=TS)
    store.write_dispatch_reservation(reservation)

    # Simulate a process restart: a brand new store object over the same
    # durable root must see the same reservation.
    restarted = JobLedgerStore(root)
    reloaded = restarted.load_dispatch_reservation(
        reservation.job_id, reservation.attempt_id
    )
    assert reloaded == reservation


def test_missing_reservation_loads_as_none(tmp_path, inputs):
    store = JobLedgerStore(tmp_path / "ledger")
    store.write_header(inputs["header"])
    assert store.load_dispatch_reservation("job_gpf", "no_such_attempt") is None


def test_retry_uses_new_attempt_and_independent_reservation_slot(tmp_path, inputs):
    store = JobLedgerStore(tmp_path / "ledger")
    store.write_header(inputs["header"])
    store.append_attempt(inputs["attempt"])
    request_1 = create_worker_request(**inputs)
    reservation_1 = create_dispatch_reservation(request=request_1, reserved_at=TS)
    store.write_dispatch_reservation(reservation_1)

    attempt_2 = _second_attempt(inputs)
    store.append_attempt(attempt_2)
    request_2 = create_worker_request(**dict(inputs, attempt=attempt_2))
    reservation_2 = create_dispatch_reservation(request=request_2, reserved_at=TS)
    new_reservation, outcome = store.write_dispatch_reservation(reservation_2)
    assert outcome == "new"
    assert new_reservation.attempt_id != reservation_1.attempt_id

    # Both slots remain independently readable -- the retry never touched
    # attempt 1's reservation.
    assert store.load_dispatch_reservation(
        "job_gpf", reservation_1.attempt_id
    ) == reservation_1
    assert store.load_dispatch_reservation(
        "job_gpf", reservation_2.attempt_id
    ) == reservation_2


def test_tampered_on_disk_reservation_detected(tmp_path, inputs):
    store = JobLedgerStore(tmp_path / "ledger")
    store.write_header(inputs["header"])
    store.append_attempt(inputs["attempt"])
    request = create_worker_request(**inputs)
    reservation = create_dispatch_reservation(request=request, reserved_at=TS)
    store.write_dispatch_reservation(reservation)

    path = store._dispatch_reservation_path(
        reservation.job_id, reservation.attempt_id
    )
    raw = path.read_text(encoding="utf-8")
    tampered = raw.replace(reservation.request_sha256, "f" * 64)
    assert tampered != raw
    path.write_text(tampered, encoding="utf-8")

    with pytest.raises(JobStoreError, match="digest drift"):
        store.load_dispatch_reservation(reservation.job_id, reservation.attempt_id)


def test_wrong_request_type_rejected():
    with pytest.raises(DispatchReservationError, match="request is invalid"):
        create_dispatch_reservation(request={"not": "a worker request"})


def test_reservation_cannot_be_constructed_without_trusted_token(inputs):
    request = create_worker_request(**inputs)
    reservation = create_dispatch_reservation(request=request, reserved_at=TS)
    forged = _forge(reservation, _token=object())
    with pytest.raises(DispatchReservationError):
        DispatchReservation(**_fields(forged))


def test_forged_field_with_stale_digest_rejected(inputs):
    request = create_worker_request(**inputs)
    reservation = create_dispatch_reservation(request=request, reserved_at=TS)
    forged = _forge(reservation, request_sha256="e" * 64)
    with pytest.raises(DispatchReservationError, match="reservation_sha256 mismatch"):
        DispatchReservation(**_fields(forged))


def test_reservation_cannot_claim_dispatch_authority(inputs):
    request = create_worker_request(**inputs)
    reservation = create_dispatch_reservation(request=request, reserved_at=TS)
    forged = _forge(reservation, dispatch_authorized=True)
    with pytest.raises(DispatchReservationError):
        DispatchReservation(**_fields(forged))


def test_classify_reservation_attempt_rejects_different_slots(inputs):
    request = create_worker_request(**inputs)
    reservation = create_dispatch_reservation(request=request, reserved_at=TS)
    other = _forge(reservation, job_id="different_job")
    with pytest.raises(DispatchReservationError, match="same job/attempt"):
        classify_reservation_attempt(reservation, other)


def test_descriptive_only_helper():
    assert dispatch_reservation_grants_no_capability() is True
