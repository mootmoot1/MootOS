"""GP-F4 -- human approval receipt + launch preparation tests."""

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
from backend.continuous_builder.gpd_job_events import create_job_event
from backend.continuous_builder.gpd_job_header import create_durable_job_header
from backend.continuous_builder.gpd_attempt_ledger import create_attempt_record
from backend.continuous_builder.gpd_job_store import JobLedgerStore, JobStoreError
from backend.continuous_builder.gpe_protocol import (
    BUDGET_FIELDS,
    create_slice_job_correlation,
    create_worker_request,
)
from backend.continuous_builder.gpf_human_approval_receipt import (
    NON_APPROVABLE_CAPABILITY_IDS,
    HumanApprovalReceipt,
    HumanApprovalReceiptError,
    create_human_approval_receipt,
    human_approval_receipt_grants_no_capability,
    receipt_is_trusted_human_approval,
    receipt_matches_launch_candidate,
    validate_human_approval_receipt,
)
from backend.continuous_builder.gpf_launch_preparation import (
    LAUNCH_READINESS_STATES,
    MISSING_AUTHENTICATED_HUMAN_APPROVAL,
    MISSING_TRUSTED_LAUNCH_AUTHORITY,
    LaunchPreparationDecision,
    LaunchPreparationError,
    evaluate_launch_preparation,
    launch_preparation_grants_no_capability,
    trusted_human_approval_authority_exists,
)

BASE = "c" * 40
TS = "2026-09-06T22:00:00+00:00"
LATER_TS = "2026-09-06T23:00:00+00:00"
EXPIRY_TS = "2026-09-06T22:30:00+00:00"
GATES = ("human_review", "unit_tests")
APPROVER = "darrickdon@gmail.com"


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


def _build_inputs(tmp_path, required_gates=GATES, job_id="job_gpf4"):
    repo = tmp_path / "repo"
    (repo / "backend").mkdir(parents=True)
    (repo / "backend/widget.py").write_text("VALUE = 1\n")
    model = build_system_model(repo, base_sha=BASE)
    contract = create_frozen_task_contract(
        task_contract_id="tc_gpf4",
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
        required_gates=required_gates,
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
        admission_input_id="ain_gpf4",
        contract=contract,
        plan=plan,
        capability_requests=requests,
        system_model_sha256=model.model_sha256,
        system_model_version=model.model_version,
        expected_base_sha=BASE,
    )
    admission, _ = admit_capabilities(admission_input, decision_id="admit_gpf4")
    header = create_durable_job_header(
        job_id=job_id,
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
        attempt_id=f"attempt_{job_id}_1",
        job_id=header.job_id,
        attempt_number=1,
        owner_id="supervisor",
        started_at=TS,
        status="started",
        header_sha256=header.header_sha256,
    )
    ce_request = seal_context_task_request(
        task_id="context_gpf4",
        base_sha=BASE,
        objective=contract.goal,
        allowed_paths=contract.allowed_scope,
        seed_paths=contract.allowed_scope,
    )
    package, _ = assemble_context_package(repo, ce_request, model)
    correlation = create_slice_job_correlation(
        header=header,
        blueprint_id="blueprint_gpf4",
        blueprint_sha256="b" * 64,
        slice_id="slice_gpf4",
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


@pytest.fixture
def inputs(tmp_path):
    return _build_inputs(tmp_path)


@pytest.fixture
def ungated_inputs(tmp_path):
    return _build_inputs(tmp_path / "ungated", required_gates=(), job_id="job_gpf4u")


def _event(seq, kind, job_id, prev=None, **kwargs):
    values = dict(
        event_id=f"evt_{job_id}_{seq:04d}",
        job_id=job_id,
        sequence=seq,
        previous_event_digest=prev,
        event_kind=kind,
        actor_kind="system",
        actor_id="system_gpf4",
        reason_code="unit_test",
        payload={},
        created_at=TS,
    )
    values.update(kwargs)
    return create_job_event(**values)


def _store_with_state(tmp_path, inputs, extra_events=()):
    store = JobLedgerStore(tmp_path / "ledger")
    store.write_header(inputs["header"])
    store.append_attempt(inputs["attempt"])
    job_id = inputs["header"].job_id
    e1 = _event(1, "job_created", job_id)
    e2 = _event(2, "job_admitted", job_id, e1.event_digest)
    e3 = _event(3, "job_ready", job_id, e2.event_digest)
    e4 = _event(
        4, "attempt_started", job_id, e3.event_digest,
        attempt_id=inputs["attempt"].attempt_id,
    )
    e5 = _event(5, "lease_acquired", job_id, e4.event_digest)
    events = [e1, e2, e3, e4, e5]
    prev, seq = e5.event_digest, 5
    for kind, kwargs in extra_events:
        seq += 1
        event = _event(seq, kind, job_id, prev, **kwargs)
        events.append(event)
        prev = event.event_digest
    for event in events:
        store.append_event(event)
    return store


def _prepare(store, inputs, request, **overrides):
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
        correlation_verifier=lambda correlation: True,
        prepared_at=TS,
    )
    kwargs.update(overrides)
    return evaluate_launch_preparation(**kwargs)


def _receipt(request, gate="human_review", **overrides):
    values = dict(
        request=request,
        gate=gate,
        approval_id=f"appr_{gate}",
        supplied_approver_identity=APPROVER,
        approved_capability_ids=("cb.repo.read",),
        approved_scope=("backend/widget.py",),
        created_at=TS,
    )
    values.update(overrides)
    return create_human_approval_receipt(**values)


# ---------------------------------------------------------------- receipt


def test_receipt_binds_the_exact_launch_candidate(inputs):
    request = create_worker_request(**inputs)
    receipt = _receipt(request)
    assert receipt.job_id == request.job_id
    assert receipt.attempt_id == request.attempt_id
    assert receipt.request_id == request.request_id
    assert receipt.request_sha256 == request.digest
    assert receipt.header_sha256 == request.header_sha256
    assert receipt.gate == "human_review"
    assert receipt.approval_id == "appr_human_review"
    assert receipt.supplied_approver_identity == APPROVER
    assert receipt.approved_capability_ids == ("cb.repo.read",)
    assert receipt.approved_scope == ("backend/widget.py",)
    assert receipt.created_at == TS
    assert receipt.schema_version == "gpf-human-approval-receipt-v1"
    assert validate_human_approval_receipt(
        receipt, request=request, gate="human_review", at=TS,
    ) is receipt


def test_receipt_digest_is_deterministic(inputs):
    request = create_worker_request(**inputs)
    assert _receipt(request).receipt_sha256 == _receipt(request).receipt_sha256


def test_receipt_for_one_gate_never_satisfies_another(inputs):
    request = create_worker_request(**inputs)
    receipt = _receipt(request, gate="human_review")
    with pytest.raises(HumanApprovalReceiptError, match="different gate"):
        validate_human_approval_receipt(
            receipt, request=request, gate="unit_tests", at=TS,
        )
    assert not receipt_matches_launch_candidate(
        receipt, request=request, gate="unit_tests", at=TS,
    )


def test_receipt_cannot_be_minted_for_an_unrequired_gate(inputs):
    request = create_worker_request(**inputs)
    with pytest.raises(HumanApprovalReceiptError, match="not a required human gate"):
        _receipt(request, gate="security_review")


def test_receipt_for_a_superseded_attempt_fails_closed(tmp_path, inputs):
    request = create_worker_request(**inputs)
    receipt = _receipt(request)
    retry = create_attempt_record(
        attempt_id="attempt_job_gpf4_2",
        job_id=inputs["header"].job_id,
        attempt_number=2,
        prior_attempt_id=inputs["attempt"].attempt_id,
        owner_id="supervisor",
        started_at=LATER_TS,
        status="started",
        header_sha256=inputs["header"].header_sha256,
    )
    retry_request = create_worker_request(**{**inputs, "attempt": retry})
    assert retry_request.attempt_id != request.attempt_id
    with pytest.raises(HumanApprovalReceiptError, match="does not bind"):
        validate_human_approval_receipt(
            receipt, request=retry_request, gate="human_review", at=LATER_TS,
        )


def test_receipt_for_a_different_request_packet_fails_closed(inputs):
    request = create_worker_request(**inputs)
    receipt = _receipt(request)
    other_correlation = create_slice_job_correlation(
        header=inputs["header"],
        blueprint_id="blueprint_gpf4",
        blueprint_sha256="b" * 64,
        slice_id="slice_gpf4_other",
    )
    other = create_worker_request(
        **{**inputs, "correlation": other_correlation}
    )
    assert other.digest != request.digest
    with pytest.raises(HumanApprovalReceiptError, match="does not bind"):
        validate_human_approval_receipt(
            receipt, request=other, gate="human_review", at=TS,
        )


def test_forged_receipt_is_rejected_at_consumption(inputs):
    request = create_worker_request(**inputs)
    receipt = _receipt(request)
    forged = _forge(receipt, supplied_approver_identity="someone-else")
    with pytest.raises(HumanApprovalReceiptError, match="receipt_sha256 mismatch"):
        validate_human_approval_receipt(
            forged, request=request, gate="human_review", at=TS,
        )


def test_receipt_cannot_claim_its_approver_was_authenticated(inputs):
    request = create_worker_request(**inputs)
    receipt = _receipt(request)
    forged = _forge(receipt, approver_authenticated=True)
    with pytest.raises(HumanApprovalReceiptError):
        validate_human_approval_receipt(
            forged, request=request, gate="human_review", at=TS,
        )
    with pytest.raises(HumanApprovalReceiptError, match="authentication is absent"):
        HumanApprovalReceipt(**{**_fields(receipt), "approver_authenticated": True})


def test_receipt_is_never_trusted_human_approval(inputs):
    request = create_worker_request(**inputs)
    receipt = _receipt(request)
    # Structurally valid ...
    assert receipt_matches_launch_candidate(
        receipt, request=request, gate="human_review", at=TS,
    )
    # ... and still not proof an authorized human approved anything.
    assert receipt_is_trusted_human_approval(receipt) is False
    assert receipt.approver_authenticated is False
    assert human_approval_receipt_grants_no_capability() is True


@pytest.mark.parametrize("capability", sorted(NON_APPROVABLE_CAPABILITY_IDS))
def test_receipt_can_never_approve_merge_publication_or_deploy(inputs, capability):
    request = create_worker_request(**inputs)
    with pytest.raises(HumanApprovalReceiptError, match="can never approve"):
        _receipt(request, approved_capability_ids=(capability,))


def test_receipt_cannot_expand_scope_or_capability(inputs):
    request = create_worker_request(**inputs)
    with pytest.raises(HumanApprovalReceiptError, match="narrow, never expand"):
        _receipt(request, approved_scope=("backend/other.py",))
    with pytest.raises(HumanApprovalReceiptError, match="already be admitted"):
        _receipt(request, approved_capability_ids=("cb.test.exec",))


def test_expired_receipt_fails_closed(inputs):
    request = create_worker_request(**inputs)
    receipt = _receipt(request, valid_until=EXPIRY_TS)
    assert receipt_matches_launch_candidate(
        receipt, request=request, gate="human_review", at=TS,
    )
    with pytest.raises(HumanApprovalReceiptError, match="expired"):
        validate_human_approval_receipt(
            receipt, request=request, gate="human_review", at=LATER_TS,
        )


def test_valid_until_must_follow_created_at(inputs):
    request = create_worker_request(**inputs)
    with pytest.raises(HumanApprovalReceiptError, match="must be after created_at"):
        _receipt(request, valid_until=TS)


def test_receipt_claims_no_authority(inputs):
    request = create_worker_request(**inputs)
    body = _receipt(request).to_dict()
    for name in (
        "launch_authorized", "dispatch_authorized", "publication_authorized",
        "queue_transition_authorized", "github_authorized", "merge_authorized",
        "main_advancement_authorized", "result_trusted",
        "worker_output_trusted", "approver_authenticated",
    ):
        assert body[name] is False


def test_receipt_requires_trusted_construction(inputs):
    request = create_worker_request(**inputs)
    untokened = {
        name: value
        for name, value in _fields(_receipt(request)).items()
        if name != "_token"
    }
    with pytest.raises(HumanApprovalReceiptError, match="trusted construction"):
        HumanApprovalReceipt(**untokened)


def test_receipt_survives_restart_through_the_ledger(tmp_path, inputs):
    store = _store_with_state(tmp_path, inputs)
    request = create_worker_request(**inputs)
    receipt = _receipt(request)
    store.append_human_approval_receipt(receipt)
    reloaded = JobLedgerStore(tmp_path / "ledger").load_human_approval_receipts(
        request.job_id, request.attempt_id,
    )
    assert [item.to_dict() for item in reloaded] == [receipt.to_dict()]


def test_tampered_stored_receipt_is_rejected_on_load(tmp_path, inputs):
    store = _store_with_state(tmp_path, inputs)
    request = create_worker_request(**inputs)
    store.append_human_approval_receipt(_receipt(request))
    path = store._human_approval_receipt_path(
        request.job_id, request.attempt_id,
    )
    path.write_text(path.read_text().replace(APPROVER, "attacker@example.com"))
    with pytest.raises(JobStoreError, match="digest drift"):
        store.load_human_approval_receipts(request.job_id, request.attempt_id)


# ------------------------------------------------------- launch preparation


def test_required_gates_without_receipts_are_never_satisfied(tmp_path, inputs):
    store = _store_with_state(tmp_path, inputs)
    request = create_worker_request(**inputs)
    decision = _prepare(store, inputs, request)
    assert decision.control_state == "launch_pending"
    assert decision.launch_readiness == "awaiting_human_gate"
    assert decision.required_gates == GATES
    assert decision.satisfied_gates == ()
    assert decision.unsatisfied_gates == GATES
    assert decision.receipt_digests == ()
    assert decision.launch_authorized is False
    assert decision.missing_trusted_mechanism == (
        MISSING_AUTHENTICATED_HUMAN_APPROVAL
    )


def test_partially_satisfied_gates_still_await_the_missing_one(tmp_path, inputs):
    store = _store_with_state(tmp_path, inputs)
    request = create_worker_request(**inputs)
    decision = _prepare(
        store, inputs, request, approval_receipts=(_receipt(request),),
    )
    assert decision.launch_readiness == "awaiting_human_gate"
    assert decision.satisfied_gates == ("human_review",)
    assert decision.unsatisfied_gates == ("unit_tests",)
    assert decision.launch_authorized is False


def test_all_gates_structurally_satisfied_is_still_not_authorized(tmp_path, inputs):
    store = _store_with_state(tmp_path, inputs)
    request = create_worker_request(**inputs)
    receipts = tuple(_receipt(request, gate=gate) for gate in GATES)
    decision = _prepare(store, inputs, request, approval_receipts=receipts)
    assert decision.launch_readiness == "awaiting_trusted_approval_authority"
    assert decision.satisfied_gates == GATES
    assert decision.unsatisfied_gates == ()
    assert decision.receipt_digests == tuple(
        sorted(item.receipt_sha256 for item in receipts)
    )
    # The whole point of GP-F4: structurally complete, still unauthorized.
    assert decision.launch_authorized is False
    assert decision.trusted_human_authority is False
    assert decision.missing_trusted_mechanism == (
        MISSING_AUTHENTICATED_HUMAN_APPROVAL
    )
    assert trusted_human_approval_authority_exists() is False


def test_ungated_job_is_prepared_but_still_unauthorized(tmp_path, ungated_inputs):
    store = _store_with_state(tmp_path, ungated_inputs)
    request = create_worker_request(**ungated_inputs)
    decision = _prepare(store, ungated_inputs, request)
    assert decision.required_gates == ()
    assert decision.launch_readiness == "prepared_pending_launch_authority"
    assert decision.launch_authorized is False
    assert decision.missing_trusted_mechanism == MISSING_TRUSTED_LAUNCH_AUTHORITY


def test_conflicting_receipts_for_one_gate_block(tmp_path, inputs):
    store = _store_with_state(tmp_path, inputs)
    request = create_worker_request(**inputs)
    first = _receipt(request, approval_id="appr_a")
    second = _receipt(request, approval_id="appr_b")
    assert first.receipt_sha256 != second.receipt_sha256
    decision = _prepare(
        store, inputs, request, approval_receipts=(first, second),
    )
    assert decision.launch_readiness == "blocked"
    assert decision.blocked_reason == "human_approval_receipt_conflict"
    assert decision.satisfied_gates == ()


def test_duplicate_identical_receipts_are_not_a_conflict(tmp_path, inputs):
    store = _store_with_state(tmp_path, inputs)
    request = create_worker_request(**inputs)
    receipt = _receipt(request)
    decision = _prepare(
        store, inputs, request, approval_receipts=(receipt, receipt),
    )
    assert decision.launch_readiness == "awaiting_human_gate"
    assert decision.satisfied_gates == ("human_review",)
    assert decision.receipt_digests == (receipt.receipt_sha256,)


def test_receipt_for_an_unrequired_gate_blocks(tmp_path, inputs, ungated_inputs):
    store = _store_with_state(tmp_path, ungated_inputs)
    gated_request = create_worker_request(**inputs)
    stray = _receipt(gated_request, gate="human_review")
    ungated_request = create_worker_request(**ungated_inputs)
    decision = _prepare(
        store, ungated_inputs, ungated_request, approval_receipts=(stray,),
    )
    assert decision.launch_readiness == "blocked"
    assert decision.blocked_reason == "human_approval_receipt_invalid"


def test_stale_attempt_receipt_blocks_rather_than_being_ignored(tmp_path, inputs):
    store = _store_with_state(tmp_path, inputs)
    request = create_worker_request(**inputs)
    stale = _forge(_receipt(request), attempt_id="attempt_job_gpf4_0")
    decision = _prepare(store, inputs, request, approval_receipts=(stale,))
    assert decision.launch_readiness == "blocked"
    assert decision.blocked_reason == "human_approval_receipt_invalid"
    assert decision.satisfied_gates == ()


def test_expired_receipt_blocks_launch_preparation(tmp_path, inputs):
    store = _store_with_state(tmp_path, inputs)
    request = create_worker_request(**inputs)
    receipts = tuple(
        _receipt(request, gate=gate, valid_until=EXPIRY_TS) for gate in GATES
    )
    decision = _prepare(
        store, inputs, request, approval_receipts=receipts, prepared_at=LATER_TS,
    )
    assert decision.launch_readiness == "blocked"
    assert decision.blocked_reason == "human_approval_receipt_invalid"


def test_unverified_correlation_blocks_before_gates_are_even_considered(
    tmp_path, inputs,
):
    store = _store_with_state(tmp_path, inputs)
    request = create_worker_request(**inputs)
    receipts = tuple(_receipt(request, gate=gate) for gate in GATES)
    decision = _prepare(
        store, inputs, request,
        approval_receipts=receipts,
        correlation_verifier=None,
    )
    assert decision.launch_readiness == "blocked"
    assert decision.blocked_reason == "correlation_required_but_unverified"
    assert decision.satisfied_gates == ()


def test_cancelled_job_blocks_despite_complete_receipts(tmp_path, inputs):
    store = _store_with_state(
        tmp_path, inputs, extra_events=(("cancelled", {}),),
    )
    request = create_worker_request(**inputs)
    receipts = tuple(_receipt(request, gate=gate) for gate in GATES)
    decision = _prepare(store, inputs, request, approval_receipts=receipts)
    assert decision.control_state == "cancelled"
    assert decision.launch_readiness == "blocked"
    assert decision.blocked_reason == "supervisor_control_not_launch_ready"
    assert decision.satisfied_gates == ()
    assert decision.launch_authorized is False


def test_gp_d_terminal_state_never_implies_human_approval(tmp_path, inputs):
    """A GP-D terminal state is execution truth, never gate satisfaction."""
    store = _store_with_state(
        tmp_path, inputs, extra_events=(("running_marked", {}), ("failed", {})),
    )
    request = create_worker_request(**inputs)
    decision = _prepare(store, inputs, request)
    assert decision.launch_readiness == "blocked"
    assert decision.satisfied_gates == ()
    assert decision.unsatisfied_gates == GATES


def test_required_gates_are_read_from_the_authoritative_header(tmp_path, inputs):
    """Never from request.human_gates, which the caller supplies."""
    store = _store_with_state(tmp_path, inputs)
    request = create_worker_request(**inputs)
    assert _prepare(store, inputs, request).required_gates == GATES
    # A request that claims it needs no human gates cannot launder its way
    # past them: required_gates is reloaded from the durable header, so the
    # forged claim changes nothing about what must be satisfied.
    forged = _forge(request, human_gates=())
    decision = _prepare(store, inputs, forged)
    assert decision.required_gates == GATES
    assert decision.unsatisfied_gates == GATES
    # GP-E's own validation (run inside GP-F2, inside GP-F3) rejects the
    # mismatch before gate evaluation is even reached, so the forgery
    # blocks rather than merely failing to help.
    assert decision.launch_readiness == "blocked"
    assert decision.blocked_reason == "binding_resolution_failed"
    assert decision.launch_authorized is False


def test_preparation_binds_the_supervisor_decision(tmp_path, inputs):
    store = _store_with_state(tmp_path, inputs)
    request = create_worker_request(**inputs)
    decision = _prepare(store, inputs, request)
    from backend.continuous_builder.gpf_supervisor import (
        evaluate_supervisor_control,
    )

    control = evaluate_supervisor_control(
        store=store,
        job_id=request.job_id,
        attempt_id=request.attempt_id,
        request=request,
        contract=inputs["contract"],
        plan=inputs["plan"],
        admission=inputs["admission"],
        admission_input=inputs["admission_input"],
        package=inputs["package"],
        correlation_verifier=lambda correlation: True,
        evaluated_at=TS,
    )
    assert decision.supervisor_decision_sha256 == control.decision_sha256


def test_preparation_is_deterministic(tmp_path, inputs):
    store = _store_with_state(tmp_path, inputs)
    request = create_worker_request(**inputs)
    first = _prepare(store, inputs, request)
    second = _prepare(store, inputs, request)
    assert first.preparation_sha256 == second.preparation_sha256


def test_preparation_can_never_authorize_launch(tmp_path, inputs):
    store = _store_with_state(tmp_path, inputs)
    request = create_worker_request(**inputs)
    decision = _prepare(store, inputs, request)
    fields = _fields(decision)
    for name in (
        "launch_authorized", "dispatch_authorized", "worker_invoked",
        "trusted_human_authority",
    ):
        with pytest.raises(LaunchPreparationError):
            LaunchPreparationDecision(**{**fields, name: True})
    body = decision.to_dict()
    for name in (
        "launch_authorized", "dispatch_authorized", "worker_invoked",
        "trusted_human_authority", "publication_authorized",
        "queue_transition_authorized", "github_authorized", "merge_authorized",
        "main_advancement_authorized", "result_trusted",
        "worker_output_trusted",
    ):
        assert body[name] is False
    assert launch_preparation_grants_no_capability() is True


def test_every_reachable_readiness_state_is_declared(tmp_path, inputs, ungated_inputs):
    seen = set()
    store = _store_with_state(tmp_path, inputs)
    request = create_worker_request(**inputs)
    seen.add(_prepare(store, inputs, request).launch_readiness)
    seen.add(
        _prepare(
            store, inputs, request,
            approval_receipts=tuple(_receipt(request, gate=g) for g in GATES),
        ).launch_readiness
    )
    seen.add(
        _prepare(
            store, inputs, request, correlation_verifier=None,
        ).launch_readiness
    )
    ungated_store = _store_with_state(tmp_path / "u", ungated_inputs)
    ungated_request = create_worker_request(**ungated_inputs)
    seen.add(
        _prepare(ungated_store, ungated_inputs, ungated_request).launch_readiness
    )
    assert seen == LAUNCH_READINESS_STATES


def test_no_network_or_subprocess_surface_in_gpf4_modules():
    import pathlib

    root = pathlib.Path(
        "backend/continuous_builder"
    )
    for name in (
        "gpf_human_approval_receipt.py", "gpf_launch_preparation.py",
    ):
        source = (root / name).read_text()
        for banned in (
            "import socket", "import subprocess", "import requests",
            "import urllib", "import http",
        ):
            assert banned not in source
