"""GP-F3 -- Single-Worker Supervisor / Control Layer tests."""

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
from backend.continuous_builder.gpd_heartbeat_lease import create_lease_record
from backend.continuous_builder.gpd_job_events import create_job_event
from backend.continuous_builder.gpd_job_header import create_durable_job_header
from backend.continuous_builder.gpd_attempt_ledger import create_attempt_record
from backend.continuous_builder.gpd_job_store import JobLedgerStore
from backend.continuous_builder.gpe_protocol import (
    BUDGET_FIELDS,
    create_slice_job_correlation,
    create_worker_request,
)
from backend.continuous_builder.gpf_dispatch_reservation import (
    create_dispatch_reservation,
)
from backend.continuous_builder.gpf_supervisor import (
    CONTROL_STATES,
    SupervisorControlDecision,
    SupervisorError,
    evaluate_supervisor_control,
    supervisor_grants_no_capability,
)

BASE = "c" * 40
TS = "2026-09-06T22:00:00+00:00"
LEASE_EXPIRES_TS = "2026-09-06T22:30:00+00:00"
LATER_TS = "2026-09-06T23:00:00+00:00"


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
        task_contract_id="tc_gpf3",
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
        admission_input_id="ain_gpf3",
        contract=contract,
        plan=plan,
        capability_requests=requests,
        system_model_sha256=model.model_sha256,
        system_model_version=model.model_version,
        expected_base_sha=BASE,
    )
    admission, _ = admit_capabilities(admission_input, decision_id="admit_gpf3")
    header = create_durable_job_header(
        job_id="job_gpf3",
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
        attempt_id="attempt_gpf3_1",
        job_id=header.job_id,
        attempt_number=1,
        owner_id="supervisor",
        started_at=TS,
        status="started",
        header_sha256=header.header_sha256,
    )
    ce_request = seal_context_task_request(
        task_id="context_gpf3",
        base_sha=BASE,
        objective=contract.goal,
        allowed_paths=contract.allowed_scope,
        seed_paths=contract.allowed_scope,
    )
    package, _ = assemble_context_package(repo, ce_request, model)
    correlation = create_slice_job_correlation(
        header=header,
        blueprint_id="blueprint_gpf3",
        blueprint_sha256="b" * 64,
        slice_id="slice_gpf3",
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


def _event(seq, kind, job_id, prev=None, **kwargs):
    values = dict(
        event_id=f"evt_{job_id}_{seq:04d}",
        job_id=job_id,
        sequence=seq,
        previous_event_digest=prev,
        event_kind=kind,
        actor_kind="system",
        actor_id="system_gpf3",
        reason_code="unit_test",
        payload={},
        created_at=TS,
    )
    values.update(kwargs)
    return create_job_event(**values)


def _leased_events(job_id, attempt_id):
    """job_created -> admitted -> ready -> leased, with attempt_started."""
    e1 = _event(1, "job_created", job_id)
    e2 = _event(2, "job_admitted", job_id, e1.event_digest)
    e3 = _event(3, "job_ready", job_id, e2.event_digest)
    e4 = _event(
        4, "attempt_started", job_id, e3.event_digest, attempt_id=attempt_id,
    )
    e5 = _event(5, "lease_acquired", job_id, e4.event_digest)
    return [e1, e2, e3, e4, e5]


def _store_with_state(tmp_path, inputs, extra_events=()):
    store = JobLedgerStore(tmp_path / "ledger")
    store.write_header(inputs["header"])
    store.append_attempt(inputs["attempt"])
    events = _leased_events(inputs["header"].job_id, inputs["attempt"].attempt_id)
    prev = events[-1].event_digest
    seq = events[-1].sequence
    for kind, kwargs in extra_events:
        seq += 1
        event = _event(seq, kind, inputs["header"].job_id, prev, **kwargs)
        events.append(event)
        prev = event.event_digest
    for event in events:
        store.append_event(event)
    return store


def _evaluate(store, inputs, request, **overrides):
    kwargs = dict(
        store=store,
        job_id=request.job_id,
        attempt_id=request.attempt_id,
        request=request,
        contract=inputs["contract"],
        plan=inputs["plan"],
        admission=inputs["admission"],
        admission_input=inputs["admission_input"],
        package=inputs["package"],
        evaluated_at=TS,
    )
    kwargs.update(overrides)
    return evaluate_supervisor_control(**kwargs)


def test_clean_leased_state_with_no_reservation_is_launch_pending(tmp_path, inputs):
    store = _store_with_state(tmp_path, inputs)
    request = create_worker_request(**inputs)
    decision = _evaluate(
        store, inputs, request, correlation_verifier=lambda c: True,
    )
    assert decision.control_state == "launch_pending"
    assert decision.reservation_sha256 is None
    assert decision.launch_authorized is False


def test_reservation_alone_does_not_imply_launch(tmp_path, inputs):
    # Crash window A: reservation written, worker never actually launched
    # (GP-D job state never advances past "leased"). control_state must
    # be "dispatch_reserved", never a post-launch state.
    store = _store_with_state(tmp_path, inputs)
    request = create_worker_request(**inputs)
    reservation = create_dispatch_reservation(request=request, reserved_at=TS)
    store.write_dispatch_reservation(reservation)
    decision = _evaluate(
        store, inputs, request, correlation_verifier=lambda c: True,
    )
    assert decision.control_state == "dispatch_reserved"
    assert decision.control_state not in (
        "running", "result_received", "proposed_success",
    )
    assert decision.reservation_sha256 == reservation.reservation_sha256


def test_conflicting_reservation_on_disk_is_blocked(tmp_path, inputs):
    # A realistic conflict: the reservation on disk was minted from an
    # earlier, independently-valid WorkerRequest for this exact attempt
    # (e.g. built against an earlier Context Engine package); the request
    # now being evaluated is a *different*, also independently-valid
    # WorkerRequest for the very same (job_id, attempt_id) -- both are
    # individually well-formed, so this can only be caught by comparing
    # the reservation's bound digest against the request actually in
    # hand, never by trusting either side alone.
    store = _store_with_state(tmp_path, inputs)
    first_request = create_worker_request(**inputs)
    reservation = create_dispatch_reservation(request=first_request, reserved_at=TS)
    store.write_dispatch_reservation(reservation)

    other_repo = tmp_path / "repo_alt"
    (other_repo / "backend").mkdir(parents=True)
    (other_repo / "backend/widget.py").write_text("VALUE = 1\n")
    other_model = build_system_model(other_repo, base_sha=BASE)
    other_ce_request = seal_context_task_request(
        task_id="context_gpf3_alt",
        base_sha=BASE,
        objective="A materially different objective text.",
        allowed_paths=inputs["contract"].allowed_scope,
        seed_paths=inputs["contract"].allowed_scope,
    )
    other_package, _ = assemble_context_package(
        other_repo, other_ce_request, other_model,
    )
    second_request = create_worker_request(
        **dict(inputs, package=other_package)
    )
    assert second_request.digest != first_request.digest

    decision = evaluate_supervisor_control(
        store=store,
        job_id=second_request.job_id,
        attempt_id=second_request.attempt_id,
        request=second_request,
        contract=inputs["contract"],
        plan=inputs["plan"],
        admission=inputs["admission"],
        admission_input=inputs["admission_input"],
        package=other_package,
        correlation_verifier=lambda c: True,
        evaluated_at=TS,
    )
    assert decision.control_state == "blocked"
    assert decision.blocked_reason == "dispatch_reservation_conflict"


def test_superseded_attempt_is_blocked(tmp_path, inputs):
    store = _store_with_state(tmp_path, inputs)
    request = create_worker_request(**inputs)
    values = inputs["attempt"].to_dict()
    values.pop("attempt_sha256")
    values.update(
        attempt_id="attempt_gpf3_2",
        attempt_number=2,
        prior_attempt_id=inputs["attempt"].attempt_id,
    )
    newer_attempt = create_attempt_record(**values)
    store.append_attempt(newer_attempt)
    decision = _evaluate(
        store, inputs, request, correlation_verifier=lambda c: True,
    )
    assert decision.control_state == "blocked"
    assert decision.blocked_reason == "binding_resolution_failed"


def test_stale_upstream_contract_is_blocked(tmp_path, inputs):
    store = _store_with_state(tmp_path, inputs)
    request = create_worker_request(**inputs)
    other_contract = create_frozen_task_contract(
        task_contract_id="tc_other",
        base_sha=BASE,
        architecture_baseline_sha256="a" * 64,
        taxonomy_class_id="narrow_bug_fix",
        goal="Different",
        intent_summary="Different",
        allowed_scope=("backend/widget.py",),
        forbidden_scope=("data",),
        acceptance_criteria=("Different",),
        budget_ceiling_wall_clock_seconds=600,
        budget_ceiling_input_tokens=10000,
        budget_ceiling_output_tokens=10000,
        required_gates=("human_review", "unit_tests"),
        risk_ceiling_indicators=("none",),
    )
    decision = _evaluate(store, inputs, request, contract=other_contract)
    assert decision.control_state == "blocked"
    assert decision.blocked_reason == "binding_resolution_failed"


@pytest.mark.parametrize(
    "extra_kind,expected_state",
    [
        ("cancelled", "cancelled"),
        ("execution_unknown_declared", "execution_unknown"),
    ],
)
def test_gpd_blocking_states_are_reused_verbatim(
    tmp_path, inputs, extra_kind, expected_state,
):
    store = _store_with_state(
        tmp_path, inputs, extra_events=[(extra_kind, {})],
    )
    request = create_worker_request(**inputs)
    decision = _evaluate(store, inputs, request)
    assert decision.control_state == expected_state
    assert decision.blocked_reason is None


def test_cancellation_requested_without_full_cancel_is_reported(tmp_path, inputs):
    store = _store_with_state(
        tmp_path, inputs, extra_events=[("cancellation_requested", {})],
    )
    request = create_worker_request(**inputs)
    decision = _evaluate(store, inputs, request)
    assert decision.control_state == "cancellation_requested"


def test_reconciling_state_is_reused_not_renamed(tmp_path, inputs):
    store = _store_with_state(
        tmp_path,
        inputs,
        extra_events=[
            ("execution_unknown_declared", {}),
            ("reconciliation_recorded", {}),
        ],
    )
    request = create_worker_request(**inputs)
    decision = _evaluate(store, inputs, request)
    assert decision.control_state == "reconciling"


def test_expired_unreleased_lease_blocks_even_though_otherwise_clean(
    tmp_path, inputs,
):
    store = _store_with_state(tmp_path, inputs)
    lease = create_lease_record(
        lease_id="lease_gpf3_1",
        job_id=inputs["header"].job_id,
        attempt_id=inputs["attempt"].attempt_id,
        owner_id="supervisor",
        acquired_at=TS,
        expires_at=LEASE_EXPIRES_TS,
    )
    store.append_lease(lease)
    request = create_worker_request(**inputs)
    decision = _evaluate(
        store, inputs, request,
        correlation_verifier=lambda c: True,
        evaluated_at=LATER_TS,
    )
    assert decision.control_state == "blocked"
    assert decision.blocked_reason == "lease_expired_unreconciled"


def test_unverified_correlation_blocks_by_default(tmp_path, inputs):
    store = _store_with_state(tmp_path, inputs)
    request = create_worker_request(**inputs)
    decision = _evaluate(store, inputs, request)  # no correlation_verifier
    assert decision.control_state == "blocked"
    assert decision.blocked_reason == "correlation_required_but_unverified"


def test_unverified_correlation_allowed_when_not_required(tmp_path, inputs):
    store = _store_with_state(tmp_path, inputs)
    request = create_worker_request(**inputs)
    decision = _evaluate(
        store, inputs, request, require_verified_correlation=False,
    )
    assert decision.control_state == "launch_pending"


def test_verified_correlation_never_claimed_when_verifier_says_false(
    tmp_path, inputs,
):
    store = _store_with_state(tmp_path, inputs)
    request = create_worker_request(**inputs)
    decision = _evaluate(
        store, inputs, request, correlation_verifier=lambda c: False,
    )
    assert decision.control_state == "blocked"
    assert decision.blocked_reason == "correlation_required_but_unverified"


def test_no_control_state_ever_reaches_post_launch_domain(tmp_path, inputs):
    # Nothing about this module's inputs includes a worker/result channel
    # -- a worker's completion claim cannot influence this decision at
    # all. Sweep every scenario above and confirm none escape the
    # pre-launch vocabulary.
    scenarios = []
    store = _store_with_state(tmp_path, inputs)
    request = create_worker_request(**inputs)
    scenarios.append(_evaluate(store, inputs, request))
    scenarios.append(
        _evaluate(store, inputs, request, correlation_verifier=lambda c: True)
    )
    reservation = create_dispatch_reservation(request=request, reserved_at=TS)
    store.write_dispatch_reservation(reservation)
    scenarios.append(
        _evaluate(store, inputs, request, correlation_verifier=lambda c: True)
    )
    post_launch = CONTROL_STATES - {
        "dispatch_reserved", "launch_pending", "blocked",
        "cancellation_requested", "cancelled", "stalled", "timed_out",
        "execution_unknown", "reconciling", "failed",
    }
    for decision in scenarios:
        assert decision.control_state not in post_launch


def test_zero_authority(tmp_path, inputs):
    store = _store_with_state(tmp_path, inputs)
    request = create_worker_request(**inputs)
    decision = _evaluate(
        store, inputs, request, correlation_verifier=lambda c: True,
    )
    for name in (
        "launch_authorized",
        "dispatch_authorized",
        "worker_invoked",
        "publication_authorized",
        "queue_transition_authorized",
        "github_authorized",
        "merge_authorized",
        "main_advancement_authorized",
        "result_trusted",
        "worker_output_trusted",
    ):
        assert getattr(decision, name) is False


def test_restart_reconstructs_persisted_decisions(tmp_path, inputs):
    root = tmp_path / "ledger"
    store = JobLedgerStore(root)
    store.write_header(inputs["header"])
    store.append_attempt(inputs["attempt"])
    for event in _leased_events(
        inputs["header"].job_id, inputs["attempt"].attempt_id,
    ):
        store.append_event(event)
    request = create_worker_request(**inputs)
    decision = _evaluate(
        store, inputs, request, correlation_verifier=lambda c: True,
    )
    store.append_supervisor_decision(decision)

    restarted = JobLedgerStore(root)
    reloaded = restarted.load_supervisor_decisions(
        request.job_id, request.attempt_id
    )
    assert len(reloaded) == 1
    assert reloaded[0] == decision


def test_decision_cannot_be_constructed_without_trusted_token(tmp_path, inputs):
    store = _store_with_state(tmp_path, inputs)
    request = create_worker_request(**inputs)
    decision = _evaluate(
        store, inputs, request, correlation_verifier=lambda c: True,
    )
    forged = _forge(decision, _token=object())
    with pytest.raises(SupervisorError):
        SupervisorControlDecision(**_fields(forged))


def test_forged_field_with_stale_digest_rejected(tmp_path, inputs):
    store = _store_with_state(tmp_path, inputs)
    request = create_worker_request(**inputs)
    reservation = create_dispatch_reservation(request=request, reserved_at=TS)
    store.write_dispatch_reservation(reservation)
    decision = _evaluate(
        store, inputs, request, correlation_verifier=lambda c: True,
    )
    assert decision.control_state == "dispatch_reserved"
    forged = _forge(decision, control_state="launch_pending")
    with pytest.raises(SupervisorError, match="decision_sha256 mismatch"):
        SupervisorControlDecision(**_fields(forged))


def test_cannot_claim_launch_or_dispatch_authority_or_worker_invoked(
    tmp_path, inputs,
):
    store = _store_with_state(tmp_path, inputs)
    request = create_worker_request(**inputs)
    decision = _evaluate(
        store, inputs, request, correlation_verifier=lambda c: True,
    )
    for field_name in (
        "launch_authorized", "dispatch_authorized", "worker_invoked",
    ):
        forged = _forge(decision, **{field_name: True})
        with pytest.raises(SupervisorError):
            SupervisorControlDecision(**_fields(forged))


def test_blocked_requires_a_blocked_reason(tmp_path, inputs):
    store = _store_with_state(tmp_path, inputs)
    request = create_worker_request(**inputs)
    decision = _evaluate(store, inputs, request)  # blocked: unverified correlation
    forged = _forge(decision, blocked_reason=None)
    with pytest.raises(SupervisorError, match="requires a blocked_reason"):
        SupervisorControlDecision(**_fields(forged))


def test_blocked_reason_only_valid_when_control_state_is_blocked(tmp_path, inputs):
    store = _store_with_state(tmp_path, inputs)
    request = create_worker_request(**inputs)
    decision = _evaluate(
        store, inputs, request, correlation_verifier=lambda c: True,
    )
    forged = _forge(decision, blocked_reason="lease_conflict")
    with pytest.raises(SupervisorError, match="only be set"):
        SupervisorControlDecision(**_fields(forged))


def test_module_imports_no_network_or_process_execution_primitives():
    import backend.continuous_builder.gpf_supervisor as module

    source = open(module.__file__, encoding="utf-8").read()
    for forbidden in ("socket", "subprocess", "urllib", "requests", "httpx"):
        assert forbidden not in source


def test_descriptive_only_helper():
    assert supervisor_grants_no_capability() is True
