"""GP-E integration and adversarial contracts; all adapters are inert."""

import json
from dataclasses import replace

import pytest

from backend.continuous_builder.context_engine import (
    assemble_context_package,
    seal_context_task_request,
)
from backend.continuous_builder.system_model import build_system_model
from backend.continuous_builder.gpb_task_contract import (
    create_frozen_task_contract,
)
from backend.continuous_builder.gpb_decomposer import decompose_task_contract
from backend.continuous_builder.gpc_capability_vocabulary import (
    create_capability_request,
)
from backend.continuous_builder.gpc_admission_input import (
    create_admission_input,
)
from backend.continuous_builder.gpc_admission_decision import (
    admit_capabilities,
)
from backend.continuous_builder.gpd_job_header import create_durable_job_header
from backend.continuous_builder.gpd_attempt_ledger import create_attempt_record
from backend.continuous_builder.gpd_job_store import JobLedgerStore
from backend.continuous_builder.gpe_protocol import (
    BUDGET_FIELDS,
    ZERO_AUTHORITY,
    WorkerRequest,
    WorkerResult,
    WorkerProtocolError,
    create_slice_job_correlation,
    create_worker_identity,
    create_worker_request,
    create_worker_result,
    decode_message,
    validate_context_delivery,
    validate_worker_request,
    validate_worker_result,
)
from backend.continuous_builder.gpe_adapter import (
    normalize_adapter_error,
    prepare_context,
    receive_worker_result,
)
from backend.continuous_builder.gpa_eval_schema import (
    canonical_json,
    sha256_hex,
)

BASE = "c" * 40
TS = "2026-09-06T22:00:00+00:00"


@pytest.fixture
def inputs(tmp_path):
    repo = tmp_path / "repo"
    (repo / "backend").mkdir(parents=True)
    (repo / "backend/widget.py").write_text("VALUE = 1\n")
    model = build_system_model(repo, base_sha=BASE)
    contract = create_frozen_task_contract(
        task_contract_id="tc_gpe",
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
        admission_input_id="ain_gpe",
        contract=contract,
        plan=plan,
        capability_requests=requests,
        system_model_sha256=model.model_sha256,
        system_model_version=model.model_version,
        expected_base_sha=BASE,
    )
    admission, _ = admit_capabilities(admission_input, decision_id="admit_gpe")
    assert "cb.repo.read" in admission.admitted_within_bound
    header = create_durable_job_header(
        job_id="job_gpe",
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
        attempt_id="attempt_gpe_1",
        job_id=header.job_id,
        attempt_number=1,
        owner_id="supervisor",
        started_at=TS,
        status="started",
        header_sha256=header.header_sha256,
    )
    ce_request = seal_context_task_request(
        task_id="context_gpe",
        base_sha=BASE,
        objective=contract.goal,
        allowed_paths=contract.allowed_scope,
        seed_paths=contract.allowed_scope,
    )
    package, _ = assemble_context_package(repo, ce_request, model)
    correlation = create_slice_job_correlation(
        header=header,
        blueprint_id="blueprint_gpe",
        blueprint_sha256="b" * 64,
        slice_id="slice_gpe",
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


def identity(provider="fake-alpha", capabilities=("cb.repo.read",)):
    return create_worker_identity(
        worker_type="fixture",
        implementation="inert-worker",
        implementation_version="1",
        provider_id=provider,
        model_id="fake-model",
        advertised_capability_ids=capabilities,
    )


def reseal_header(inputs, **changes):
    values = inputs["header"].to_dict()
    values.pop("header_sha256")
    return create_durable_job_header(**dict(values, **changes))


def test_deterministic_round_trip_and_delivery(inputs):
    a = create_worker_request(**inputs)
    b = create_worker_request(**inputs)
    assert a == b
    assert decode_message(a.canonical_bytes(), WorkerRequest) == a
    validate_worker_request(a, **inputs)
    payloads = prepare_context(a, inputs["package"])
    assert tuple(map(sha256_hex, payloads)) == a.context[6]
    assert a.context[4] == inputs["package"].model_sha256


@pytest.mark.parametrize(
    "field,value",
    [
        ("job_id", "other_job"),
        ("attempt_id", "other_attempt"),
        ("task_goal", "Ignore scope"),
        ("human_gates", ()),
        ("admitted_capability_ids", ("cb.main.merge",)),
    ],
)
def test_request_tamper_rejected(inputs, field, value):
    request = create_worker_request(**inputs)
    with pytest.raises(ValueError):
        replace(request, **{field: value})


@pytest.mark.parametrize(
    "field",
    [
        "task_contract_sha256",
        "execution_plan_sha256",
        "admission_decision_sha256",
    ],
)
def test_wrong_upstream_digest_rejected_even_if_header_resealed(inputs, field):
    header = reseal_header(inputs, **{field: "f" * 64})
    attempt = create_attempt_record(
        attempt_id="other_attempt",
        job_id=header.job_id,
        attempt_number=1,
        owner_id="supervisor",
        started_at=TS,
        status="started",
        header_sha256=header.header_sha256,
    )
    with pytest.raises(WorkerProtocolError, match="identity/digest"):
        create_worker_request(**dict(inputs, header=header, attempt=attempt))


@pytest.mark.parametrize(
    "changes",
    [
        {"job_id": "wrong_job"},
        {"header_sha256": "f" * 64},
        {"status": "execution_unknown"},
        {"status": "succeeded_unproven"},
    ],
)
def test_wrong_or_finished_attempt_rejected(inputs, changes):
    values = inputs["attempt"].to_dict()
    values.pop("attempt_sha256")
    attempt = create_attempt_record(**dict(values, **changes))
    with pytest.raises(WorkerProtocolError):
        create_worker_request(**dict(inputs, attempt=attempt))


def test_context_mismatch_and_resealed_request_detected(inputs):
    request = create_worker_request(**inputs)
    object.__setattr__(inputs["package"], "package_sha256", "d" * 64)
    with pytest.raises(ValueError):
        validate_context_delivery(request, inputs["package"])
    raw = request.to_dict()
    raw["task_goal"] = "Changed goal"
    raw["digest"] = sha256_hex(
        canonical_json({k: v for k, v in raw.items() if k != "digest"})
    )
    forged = decode_message(canonical_json(raw), WorkerRequest)
    with pytest.raises(ValueError):
        validate_worker_request(forged, **inputs)


@pytest.mark.parametrize(
    "changes",
    [
        {"admitted_capability_ids": ("cb.network",)},
        {"approved_scope_ceiling": ("backend/other.py",)},
        {"forbidden_scope": ()},
        {"required_gates": ()},
        {"budget_ceiling_input_tokens": 20000},
    ],
)
def test_resealed_header_cannot_widen_or_drop_gates(inputs, changes):
    header = reseal_header(inputs, **changes)
    values = inputs["attempt"].to_dict()
    values.pop("attempt_sha256")
    attempt = create_attempt_record(
        **dict(values, header_sha256=header.header_sha256)
    )
    with pytest.raises(WorkerProtocolError):
        create_worker_request(**dict(inputs, header=header, attempt=attempt))


def test_advertised_capability_and_human_gates(inputs):
    request = create_worker_request(**inputs)
    worker = identity(
        capabilities=("cb.main.merge", "cb.network", "cb.repo.read")
    )
    result = create_worker_result(
        request=request,
        worker=worker,
        status="completed",
        worker_reported_completion=True,
    )
    assert request.admitted_capability_ids == ("cb.repo.read",)
    assert "cb.main.merge" in request.human_gated_capability_ids
    assert set(request.human_gates) == set(inputs["contract"].required_gates)
    constraints = json.loads(request.admitted_request_constraints[0])
    assert constraints["budget_wall_clock_seconds"] == 30
    assert constraints["requested_scope"] == ["backend/widget.py"]
    for obj in (request, worker, result, request.correlation):
        for name in ZERO_AUTHORITY:
            assert getattr(obj, name) is False


class AlphaFake:
    """One inert reference worker using a fictional provider label."""

    identity = identity()

    def invoke(self, request, context_bytes):
        assert tuple(map(sha256_hex, context_bytes)) == request.context[6]
        return create_worker_result(
            request=request,
            worker=self.identity,
            status="completed",
            worker_reported_completion=True,
            command_test_claims=("tests passed",),
        )


class BetaFake:
    """A differently shaped fake provider response normalized at the edge."""

    identity = identity("fake-beta")

    def invoke(self, request, context_bytes):
        assert tuple(map(sha256_hex, context_bytes)) == request.context[6]
        provider_response = {"finish_tag": "needs_input"}
        return create_worker_result(
            request=request,
            worker=self.identity,
            status={"needs_input": "blocked"}[provider_response["finish_tag"]],
            stop_reason="fixture requires clarification",
        )


def test_two_adapters_same_request_no_io(inputs, monkeypatch):
    import socket
    import subprocess

    def forbidden(*args, **kwargs):
        raise AssertionError("no external execution permitted")

    monkeypatch.setattr(socket, "socket", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    request = create_worker_request(**inputs)
    for adapter in (AlphaFake(), BetaFake()):
        result = adapter.invoke(
            request, prepare_context(request, inputs["package"])
        )
        validate_worker_result(result, request, adapter.identity)
        assert decode_message(result.canonical_bytes(), WorkerResult) == result
        assert result.result_trusted is False


@pytest.mark.parametrize(
    "field,value",
    [
        ("status", "completed"),
        ("attempt_id", "other"),
        ("changed_path_claims", ("backend/widget.py",)),
        ("worker_reported_completion", True),
    ],
)
def test_result_tampering(inputs, field, value):
    result = create_worker_result(
        request=create_worker_request(**inputs),
        worker=identity(),
        status="blocked",
    )
    with pytest.raises(ValueError):
        replace(result, **{field: value})


@pytest.mark.parametrize(
    "raw",
    [
        b"{}",
        b"null",
        b"[]",
        b"garbage",
        b'{"x":1,"x":2}',
        b"x" * (128 * 1024 + 1),
    ],
    ids=["empty", "null", "list", "bad", "duplicate", "large"],
)
def test_malformed_result_normalizes_to_unknown(inputs, raw):
    result = receive_worker_result(
        raw,
        create_worker_request(**inputs),
        identity(),
        execution_uncertain=False,
    )
    assert result.error_category == "malformed_response"
    assert result.status == "execution_unknown"


@pytest.mark.parametrize(
    "category",
    [
        "rate_limited",
        "provider_unavailable",
        "authentication_unavailable",
        "model_unavailable",
        "context_too_large",
        "malformed_response",
        "worker_protocol_violation",
        "timed_out",
        "cancelled",
        "sandbox_failure",
        "VendorSpecificOops",
    ],
)
def test_normalized_errors_never_decide_retry(inputs, category):
    result = normalize_adapter_error(
        create_worker_request(**inputs), identity(), category=category
    )
    assert result.status == "execution_unknown"
    assert "retryable" not in result.to_dict()
    assert result.error_category == (
        "unknown_failure" if category == "VendorSpecificOops" else category
    )


def test_fake_provider_exception_mapping_and_preinvoke_timeout(inputs):
    class FictionalQuotaError(Exception):
        pass

    request = create_worker_request(**inputs)
    try:
        raise FictionalQuotaError("fixture quota exceeded")
    except FictionalQuotaError:
        result = normalize_adapter_error(
            request,
            identity(),
            category="rate_limited",
            execution_may_have_occurred=False,
        )
    assert result.error_category == "rate_limited"
    assert result.status == "failed"
    result = normalize_adapter_error(
        request,
        identity(),
        category="timed_out",
        execution_may_have_occurred=False,
    )
    assert result.status == "timed_out"


def test_success_cannot_clear_supervisor_uncertainty(inputs):
    request = create_worker_request(**inputs)
    raw = AlphaFake().invoke(
        request, prepare_context(request, inputs["package"])
    )
    result = receive_worker_result(
        raw.canonical_bytes(),
        request,
        AlphaFake.identity,
        execution_uncertain=True,
    )
    assert result.status == "execution_unknown"


def test_retry_new_identity_and_old_result_rejected(inputs, tmp_path):
    first = create_worker_request(**inputs)
    store = JobLedgerStore(tmp_path / "ledger")
    store.write_header(inputs["header"])
    store.append_attempt(inputs["attempt"])
    attempt = create_attempt_record(
        attempt_id="attempt_gpe_2",
        job_id=first.job_id,
        attempt_number=2,
        prior_attempt_id=first.attempt_id,
        owner_id="supervisor",
        started_at=TS,
        status="started",
        header_sha256=first.header_sha256,
    )
    store.append_attempt(attempt)
    second = create_worker_request(**dict(inputs, attempt=attempt))
    assert first.request_id != second.request_id
    assert first.correlation == second.correlation
    old = create_worker_result(
        request=first, worker=identity(), status="completed"
    )
    with pytest.raises(WorkerProtocolError):
        validate_worker_result(old, second, identity())
    reopened = JobLedgerStore(tmp_path / "ledger")
    assert len(reopened.load_attempts(first.job_id)) == 2


def test_wire_authority_unknown_fields_and_nonfinite_rejected(inputs):
    result = create_worker_result(
        request=create_worker_request(**inputs),
        worker=identity(),
        status="completed",
    )
    for key, value in (
        ("result_trusted", True),
        ("unexpected", 1),
        ("usage", [float("nan"), None, None, None]),
    ):
        wire = dict(result.to_dict(), **{key: value})
        with pytest.raises(WorkerProtocolError):
            decode_message(canonical_json(wire), WorkerResult)


def test_result_wrong_worker_and_bounded_claims(inputs):
    request = create_worker_request(**inputs)
    result = create_worker_result(
        request=request, worker=identity(), status="completed"
    )
    with pytest.raises(WorkerProtocolError):
        validate_worker_result(result, request, identity("different"))
    for claims in (
        {"stdout_summary": "x" * 4097},
        {"usage": (True, 0, 0, 0)},
        {"changed_path_claims": ("../escape",)},
        {"status": "terminal_success"},
    ):
        with pytest.raises(ValueError):
            create_worker_result(request=request, worker=identity(), **claims)


def test_worker_claim_cannot_change_durable_truth(inputs, tmp_path):
    from backend.continuous_builder.gpd_job_events import create_job_event
    from backend.continuous_builder.gpd_job_state import (
        reduce_job_state,
        JobStateError,
    )

    store = JobLedgerStore(tmp_path / "durable")
    store.write_header(inputs["header"])
    events = []
    for kind in (
        "job_created",
        "job_admitted",
        "job_ready",
        "lease_acquired",
        "running_marked",
    ):
        events.append(
            create_job_event(
                event_id="evt_" + str(len(events)),
                job_id=inputs["header"].job_id,
                sequence=len(events) + 1,
                previous_event_digest=(
                    events[-1].event_digest if events else None
                ),
                event_kind=kind,
                actor_kind="system",
                actor_id="supervisor",
                reason_code="fixture",
                created_at=TS,
                attempt_id=inputs["attempt"].attempt_id,
            )
        )
        store.append_event(events[-1])
    before = (tmp_path / "durable/jobs/job_gpe/events.jsonl").read_bytes()
    request = create_worker_request(**inputs)
    result = AlphaFake().invoke(
        request, prepare_context(request, inputs["package"])
    )
    assert result.status == "completed"
    assert (
        tmp_path / "durable/jobs/job_gpe/events.jsonl"
    ).read_bytes() == before
    assert reduce_job_state(inputs["header"], events).state == "running"
    claim = create_job_event(
        event_id="evt_claim",
        job_id=result.job_id,
        sequence=6,
        previous_event_digest=events[-1].event_digest,
        event_kind="terminal_success",
        actor_kind="worker_claim",
        actor_id="fake",
        reason_code="fixture",
        created_at=TS,
        attempt_id=result.attempt_id,
        worker_claim=True,
    )
    with pytest.raises(JobStateError):
        reduce_job_state(inputs["header"], events + [claim])


def test_supplements_exact_delivery_and_omission(inputs, tmp_path):
    from backend.continuous_builder.context_engine import (
        seal_supplement_request,
        fulfill_supplement,
    )

    repo = tmp_path / "repo"
    model = build_system_model(repo, base_sha=BASE)
    ce_request = seal_context_task_request(
        task_id="context_gpe",
        base_sha=BASE,
        objective=inputs["contract"].goal,
        allowed_paths=inputs["contract"].allowed_scope,
        seed_paths=inputs["contract"].allowed_scope,
    )
    package = inputs["package"]
    supplement_request = seal_supplement_request(
        original_request=ce_request,
        package=package,
        worker_id="fake",
        subject="backend/widget.py",
        reason="additional evidence",
        category="file_excerpt",
    )
    supplement = fulfill_supplement(
        repo,
        supplement_request,
        original_request=ce_request,
        package=package,
        model=model,
    )
    request = create_worker_request(**inputs, supplements=(supplement,))
    payloads = prepare_context(request, package, (supplement,))
    assert len(payloads) == 2
    assert request.context[5][0][0] == supplement.supplement_sha256
    with pytest.raises(WorkerProtocolError):
        prepare_context(request, package)
    with pytest.raises(WorkerProtocolError):
        create_worker_request(**inputs, supplements=(supplement, supplement))
    object.__setattr__(supplement, "package_sha256", "e" * 64)
    with pytest.raises(ValueError):
        prepare_context(request, package, (supplement,))


def test_resealed_request_system_validation_and_wrong_context(inputs):
    request = create_worker_request(**inputs)
    wire = request.to_dict()
    wire["task_goal"] = "Changed goal"
    wire["digest"] = sha256_hex(
        canonical_json({k: v for k, v in wire.items() if k != "digest"})
    )
    forged = decode_message(canonical_json(wire), WorkerRequest)
    with pytest.raises(WorkerProtocolError, match="system-owned"):
        validate_worker_request(forged, **inputs)
    wire = request.to_dict()
    wire["context"][1] = "e" * 64
    with pytest.raises(WorkerProtocolError):
        decode_message(canonical_json(wire), WorkerRequest)


def test_no_tcb_or_execution_importers():
    import ast
    from pathlib import Path
    from backend.continuous_builder.trusted_policy import (
        create_mootos_tcb_registry_v1,
    )

    root = Path(__file__).resolve().parents[1]
    registry = create_mootos_tcb_registry_v1()
    assert not any("gpe_" in path for path in registry.protected_paths)
    for path in registry.protected_paths:
        if path == "requirements.txt":
            # GP-F crypto manifest is protected data, not a Python importer.
            continue
        tree = ast.parse((root / path).read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                assert "gpe_" not in (node.module or "")
    for name in ("gpe_protocol.py", "gpe_adapter.py"):
        tree = ast.parse(
            (root / "backend/continuous_builder" / name).read_text()
        )
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                assert not {n.name for n in node.names} & {
                    "socket",
                    "subprocess",
                    "requests",
                    "httpx",
                    "openai",
                }


def test_slice_correlation_wrong_job_and_real_identifier_vocabulary(inputs):
    correlation = create_slice_job_correlation(
        header=inputs["header"],
        blueprint_id="MootOS-Builder.v1",
        blueprint_sha256="b" * 64,
        slice_id="GP-E",
    )
    request = create_worker_request(**dict(inputs, correlation=correlation))
    assert request.correlation.slice_id == "GP-E"
    assert "state" not in correlation.to_dict()
    assert "completed" not in correlation.to_dict()
    other_header = reseal_header(inputs, job_id="other_job")
    other = create_slice_job_correlation(
        header=other_header,
        blueprint_id="MootOS",
        blueprint_sha256="b" * 64,
        slice_id="GP-E",
    )
    with pytest.raises(WorkerProtocolError):
        create_worker_request(**dict(inputs, correlation=other))


def test_factory_token_and_malformed_constraints(inputs):
    request = create_worker_request(**inputs)
    with pytest.raises(WorkerProtocolError):
        replace(request, _token=None)
    wire = request.to_dict()
    wire["admitted_request_constraints"] = ["{}"]
    wire["digest"] = sha256_hex(
        canonical_json({k: v for k, v in wire.items() if k != "digest"})
    )
    with pytest.raises(WorkerProtocolError):
        decode_message(canonical_json(wire), WorkerRequest)
