"""GP-F2 -- Authoritative Binding Resolution Before Launch tests."""

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
from backend.continuous_builder.gpd_job_store import JobLedgerStore
from backend.continuous_builder.gpe_protocol import (
    BUDGET_FIELDS,
    create_slice_job_correlation,
    create_worker_request,
)
from backend.continuous_builder.gpf_binding_resolution import (
    BindingResolutionError,
    ResolvedLaunchBindings,
    binding_resolution_grants_no_capability,
    resolve_launch_bindings,
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
        task_contract_id="tc_gpf2",
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
        admission_input_id="ain_gpf2",
        contract=contract,
        plan=plan,
        capability_requests=requests,
        system_model_sha256=model.model_sha256,
        system_model_version=model.model_version,
        expected_base_sha=BASE,
    )
    admission, _ = admit_capabilities(admission_input, decision_id="admit_gpf2")
    header = create_durable_job_header(
        job_id="job_gpf2",
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
        attempt_id="attempt_gpf2_1",
        job_id=header.job_id,
        attempt_number=1,
        owner_id="supervisor",
        started_at=TS,
        status="started",
        header_sha256=header.header_sha256,
    )
    ce_request = seal_context_task_request(
        task_id="context_gpf2",
        base_sha=BASE,
        objective=contract.goal,
        allowed_paths=contract.allowed_scope,
        seed_paths=contract.allowed_scope,
    )
    package, _ = assemble_context_package(repo, ce_request, model)
    correlation = create_slice_job_correlation(
        header=header,
        blueprint_id="blueprint_gpf2",
        blueprint_sha256="b" * 64,
        slice_id="slice_gpf2",
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


def _store(tmp_path, inputs, attempt=None):
    store = JobLedgerStore(tmp_path / "ledger")
    store.write_header(inputs["header"])
    store.append_attempt(attempt or inputs["attempt"])
    return store


def _resolve_kwargs(inputs, store, request):
    return dict(
        store=store,
        job_id=request.job_id,
        attempt_id=request.attempt_id,
        request=request,
        contract=inputs["contract"],
        plan=inputs["plan"],
        admission=inputs["admission"],
        admission_input=inputs["admission_input"],
        package=inputs["package"],
        resolved_at=TS,
    )


def test_resolves_matching_bindings(tmp_path, inputs):
    store = _store(tmp_path, inputs)
    request = create_worker_request(**inputs)
    bindings = resolve_launch_bindings(**_resolve_kwargs(inputs, store, request))
    assert bindings.job_id == request.job_id
    assert bindings.attempt_id == request.attempt_id
    assert bindings.attempt_is_current is True
    assert bindings.attempt_status == "started"
    assert bindings.correlation_present is True
    assert bindings.correlation_checked is False
    assert bindings.correlation_verified is False
    assert bindings.launch_authorized is False


def test_deterministic_digest(tmp_path, inputs):
    store = _store(tmp_path, inputs)
    request = create_worker_request(**inputs)
    kwargs = _resolve_kwargs(inputs, store, request)
    first = resolve_launch_bindings(**kwargs)
    second = resolve_launch_bindings(**kwargs)
    assert first.bindings_sha256 == second.bindings_sha256


def test_correlation_verified_only_when_verifier_confirms(tmp_path, inputs):
    store = _store(tmp_path, inputs)
    request = create_worker_request(**inputs)
    kwargs = _resolve_kwargs(inputs, store, request)
    bindings = resolve_launch_bindings(
        **kwargs, correlation_verifier=lambda correlation: True
    )
    assert bindings.correlation_checked is True
    assert bindings.correlation_verified is True


def test_correlation_verifier_returning_false_is_recorded_honestly(tmp_path, inputs):
    store = _store(tmp_path, inputs)
    request = create_worker_request(**inputs)
    kwargs = _resolve_kwargs(inputs, store, request)
    bindings = resolve_launch_bindings(
        **kwargs, correlation_verifier=lambda correlation: False
    )
    assert bindings.correlation_checked is True
    assert bindings.correlation_verified is False


def test_worker_supplied_header_copy_is_never_trusted(tmp_path, inputs):
    # Reload from the authoritative store must be used even if a caller
    # tries to pass a self-consistent but stale/forged header via the
    # upstream contract/plan/admission objects -- here we simulate the
    # attack by tampering the stored ledger header after the request was
    # built against the original: resolution must reflect the ledger,
    # not whatever the request's own header_sha256 happened to claim.
    store = _store(tmp_path, inputs)
    request = create_worker_request(**inputs)
    # Corrupt the on-disk header file directly.
    header_path = store.root / "jobs" / "job_gpf2" / "header.json"
    original = header_path.read_text(encoding="utf-8")
    tampered = original.replace(inputs["header"].header_sha256, "f" * 64)
    assert tampered != original
    header_path.write_text(tampered, encoding="utf-8")
    with pytest.raises(Exception):
        resolve_launch_bindings(**_resolve_kwargs(inputs, store, request))


def test_missing_attempt_rejected(tmp_path, inputs):
    store = _store(tmp_path, inputs)
    request = create_worker_request(**inputs)
    with pytest.raises(BindingResolutionError, match="attempt not found"):
        resolve_launch_bindings(
            **dict(_resolve_kwargs(inputs, store, request), attempt_id="ghost_attempt")
        )


def test_stale_attempt_rejected_when_newer_attempt_exists(tmp_path, inputs):
    store = _store(tmp_path, inputs)
    request = create_worker_request(**inputs)
    values = inputs["attempt"].to_dict()
    values.pop("attempt_sha256")
    values.update(
        attempt_id="attempt_gpf2_2",
        attempt_number=2,
        prior_attempt_id=inputs["attempt"].attempt_id,
    )
    newer = create_attempt_record(**values)
    store.append_attempt(newer)
    with pytest.raises(BindingResolutionError, match="not the job's current"):
        resolve_launch_bindings(**_resolve_kwargs(inputs, store, request))


def test_finished_attempt_status_rejected(tmp_path, inputs):
    # GP-E's own create_worker_request already refuses to bind a *new*
    # request to a non-"started" attempt, and attempts are append-only
    # (never mutated in place) in the current GP-D ledger. The realistic
    # way this state arises is a request built while the attempt was
    # still "started", resolved after the store's authoritative record
    # for that same attempt_id has since moved on -- resolve_launch_
    # bindings must fail closed on that authoritative mismatch rather
    # than trust the (now stale) request.
    request = create_worker_request(**inputs)
    values = inputs["attempt"].to_dict()
    values.pop("attempt_sha256")
    values["status"] = "failed"
    finished_attempt = create_attempt_record(**values)
    store = _store(tmp_path, inputs, attempt=finished_attempt)
    with pytest.raises(BindingResolutionError, match="does not match"):
        resolve_launch_bindings(**_resolve_kwargs(inputs, store, request))


def test_mismatched_upstream_contract_rejected(tmp_path, inputs):
    store = _store(tmp_path, inputs)
    request = create_worker_request(**inputs)
    other_contract = create_frozen_task_contract(
        task_contract_id="tc_other",
        base_sha=BASE,
        architecture_baseline_sha256="a" * 64,
        taxonomy_class_id="narrow_bug_fix",
        goal="Different goal entirely",
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
    kwargs = dict(_resolve_kwargs(inputs, store, request), contract=other_contract)
    with pytest.raises(BindingResolutionError, match="does not match"):
        resolve_launch_bindings(**kwargs)


def test_invalid_request_type_rejected(tmp_path, inputs):
    store = _store(tmp_path, inputs)
    with pytest.raises(BindingResolutionError, match="request is invalid"):
        resolve_launch_bindings(
            **dict(
                _resolve_kwargs(inputs, store, inputs["attempt"]),
                request="not a worker request",
            )
        )


def test_bindings_cannot_be_constructed_without_trusted_token(tmp_path, inputs):
    store = _store(tmp_path, inputs)
    request = create_worker_request(**inputs)
    bindings = resolve_launch_bindings(**_resolve_kwargs(inputs, store, request))
    forged = _forge(bindings, _token=object())
    with pytest.raises(BindingResolutionError):
        ResolvedLaunchBindings(**_fields(forged))


def test_forged_field_with_stale_digest_rejected(tmp_path, inputs):
    store = _store(tmp_path, inputs)
    request = create_worker_request(**inputs)
    bindings = resolve_launch_bindings(**_resolve_kwargs(inputs, store, request))
    forged = _forge(bindings, attempt_is_current=False)
    with pytest.raises(BindingResolutionError, match="bindings_sha256 mismatch"):
        ResolvedLaunchBindings(**_fields(forged))


def test_cannot_claim_launch_authorized(tmp_path, inputs):
    store = _store(tmp_path, inputs)
    request = create_worker_request(**inputs)
    bindings = resolve_launch_bindings(**_resolve_kwargs(inputs, store, request))
    forged = _forge(bindings, launch_authorized=True)
    with pytest.raises(BindingResolutionError):
        ResolvedLaunchBindings(**_fields(forged))


def test_correlation_verified_without_checked_rejected(tmp_path, inputs):
    store = _store(tmp_path, inputs)
    request = create_worker_request(**inputs)
    bindings = resolve_launch_bindings(**_resolve_kwargs(inputs, store, request))
    forged = _forge(
        bindings, correlation_checked=False, correlation_verified=True,
    )
    with pytest.raises(
        BindingResolutionError, match="verified without being checked"
    ):
        ResolvedLaunchBindings(**_fields(forged))


def test_descriptive_only_helper():
    assert binding_resolution_grants_no_capability() is True
