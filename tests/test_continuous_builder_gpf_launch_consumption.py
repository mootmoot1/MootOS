"""Readiness and one-shot consumption; synthetic keys, nothing dispatched."""

import hashlib
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from types import MappingProxyType, SimpleNamespace

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from backend.continuous_builder import gpf_approval_authority as authority
from backend.continuous_builder import gpf_launch_candidate_binding as binding
from backend.continuous_builder import gpf_launch_consumption as consumption
from backend.continuous_builder import gpf_launch_dispatch_intent as readiness
from backend.continuous_builder import gpf_launch_facts as facts_source
from backend.continuous_builder import gpf_launch_state_projection as project
from backend.continuous_builder.gpd_job_store import JobLedgerStore
from backend.continuous_builder.gpe_protocol import create_worker_request
from backend.continuous_builder.gpf_dispatch_reservation import (
    create_dispatch_reservation,
)
from backend.continuous_builder.gpf_human_approval_receipt import (
    create_human_approval_receipt,
)
from backend.continuous_builder.trusted_policy import (
    create_mootos_tcb_registry_v1,
)
from backend.continuous_builder.trusted_policy_enforcement import (
    evaluate_changed_paths_against_tcb, OUTCOME_FORBIDDEN,
)
from test_continuous_builder_gpf_launch_preparation import (
    _build_inputs, _event, TS,
)

FUTURE = "2099-01-01T00:00:00+00:00"
READY = (
    ("job_created", {}), ("job_admitted", {}), ("job_ready", {}),
    ("attempt_started", {"attempt": True}),
)
DECISION = dict(coordinator_decision_id="sched_gpf",
                coordinator_decision_sha256="a" * 64)


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode()


def now_iso():
    return datetime.now(timezone.utc).isoformat()


@pytest.fixture
def signer(monkeypatch):
    # Ephemeral synthetic key only. The enrolled human key is never touched.
    private = Ed25519PrivateKey.generate()
    public = private.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    key_id = "sha256:" + hashlib.sha256(public).hexdigest()
    monkeypatch.setattr(authority, "_AUTHORIZED_PUBLIC_KEYS",
                        MappingProxyType({key_id: public}))
    return private, key_id


@pytest.fixture
def bench(tmp_path, monkeypatch):
    inputs = _build_inputs(tmp_path)
    request = create_worker_request(**inputs)
    job_id, attempt_id = request.job_id, request.attempt_id
    root = tmp_path / "authority"
    database = tmp_path / "product.sqlite"
    with sqlite3.connect(database) as db:
        db.executescript('''
            CREATE TABLE builder_blueprints (
                blueprint_id TEXT, blueprint_version TEXT,
                content_digest TEXT);
            CREATE TABLE builder_slices (
                blueprint_id TEXT, blueprint_version TEXT,
                slice_id TEXT, slice_version TEXT);
            CREATE TABLE builder_events (
                blueprint_id TEXT, blueprint_version TEXT, value TEXT);
            CREATE TABLE builder_attempts (attempt_id TEXT,
                blueprint_id TEXT, blueprint_version TEXT);
            CREATE TABLE builder_leases (attempt_id TEXT, value TEXT);
        ''')
        db.execute("INSERT INTO builder_blueprints VALUES (?,?,?)",
                   ("blueprint_gpf4", "1", "b" * 64))
        db.execute("INSERT INTO builder_slices VALUES (?,?,?,?)",
                   ("blueprint_gpf4", "1", "slice_gpf4", "1"))
    monkeypatch.setattr(binding, "_AUTHORITATIVE_ROOT", root)
    monkeypatch.setattr(binding, "_PRODUCT_DATABASE", database)
    raw = request.canonical_bytes()
    store = JobLedgerStore(root)

    def seed(events=READY, reserve=True):
        store.write_header(inputs["header"])
        store.append_attempt(inputs["attempt"])
        previous = None
        for sequence, (kind, extra) in enumerate(events, 1):
            values = dict(extra)
            if values.pop("attempt", False):
                values["attempt_id"] = attempt_id
            event = _event(sequence, kind, job_id, previous, **values)
            store.append_event(event)
            previous = event.event_digest
        if reserve:
            store.write_dispatch_reservation(
                create_dispatch_reservation(request=request))
        binding.assign_launch_candidate(
            job_id=job_id, attempt_id=attempt_id, request_bytes=raw,
            blueprint_id="blueprint_gpf4", blueprint_version="1",
            slice_id="slice_gpf4", created_at=TS)
        return capture()

    def capture():
        record = facts_source.capture_launch_facts(
            job_id=job_id, request_id=request.request_id, request_bytes=raw)
        return project.project_launch_state(facts=record, request_bytes=raw)

    def advance(kind, **extra):
        events = store.load_events(job_id)
        last = events[-1]
        store.append_event(_event(last.sequence + 1, kind, job_id,
                                  last.event_digest, **extra))

    return SimpleNamespace(
        seed=seed, capture=capture, advance=advance, inputs=inputs,
        request=request, root=root, job_id=job_id, attempt_id=attempt_id,
        store=store, raw=raw)


def proofs(bench, signer, gates=("human_review", "unit_tests")):
    private, key_id = signer
    out = []
    for gate in gates:
        record = create_human_approval_receipt(
            request=bench.request, gate=gate, approval_id="appr_" + gate,
            supplied_approver_identity="claimed_human",
            approved_capability_ids=("cb.repo.read",),
            approved_scope=("backend/widget.py",), created_at=TS,
            valid_until=FUTURE)
        raw = canonical(record.to_dict())
        out.append((raw, private.sign(authority.DOMAIN + raw), key_id))
    return tuple(out)


def issue(bench, ttl_seconds=300, **overrides):
    facts, _ = bench.capture()
    kwargs = dict(facts=facts, request_bytes=bench.raw, issued_at=now_iso(),
                  ttl_seconds=ttl_seconds, **DECISION)
    kwargs.update(overrides)
    return readiness.record_launch_dispatch_intent(**kwargs)


def consume(bench, signer, authorization_id="auth_gpf", **overrides):
    facts, _ = bench.capture()
    kwargs = dict(authorization_id=authorization_id,
                  authorization_sha256="c" * 64, facts=facts,
                  request_bytes=bench.raw, approvals=proofs(bench, signer))
    kwargs.update(overrides)
    return consumption.consume_launch_authorization(**kwargs)


# ------------------------------------------------------------- readiness


def test_exact_readiness_is_recorded_and_is_not_authority(bench):
    bench.seed()
    facts, projection = bench.capture()
    intent, status = issue(bench)
    assert status == "new"
    assert intent.job_id == bench.job_id
    assert intent.attempt_id == bench.attempt_id
    assert intent.request_id == bench.request.request_id
    assert intent.request_sha256 == facts.request_sha256
    assert intent.binding_sha256 == facts.binding_sha256
    assert intent.reservation_sha256 == projection.reservation_sha256
    assert intent.source_tokens_sha256 == projection.source_tokens_sha256
    assert intent.coordinator_decision_id == "sched_gpf"
    body = intent.to_dict()
    digest = body.pop("intent_sha256")
    assert digest == hashlib.sha256(canonical(body)).hexdigest()
    for flag in binding._FLAGS:
        assert getattr(intent, flag) is False
        assert intent.to_dict()[flag] is False
    assert readiness.dispatch_intent_grants_no_capability() is True
    assert readiness.load_launch_dispatch_intent(
        job_id=bench.job_id, request_id=bench.request.request_id) == intent


def test_identical_readiness_replay_is_idempotent(bench):
    bench.seed()
    issued = now_iso()
    first, first_status = issue(bench, issued_at=issued)
    second, second_status = issue(bench, issued_at=issued)
    assert (first_status, second_status) == ("new", "replay")
    assert first == second


def test_conflicting_readiness_replay_is_rejected(bench):
    bench.seed()
    issue(bench)
    with pytest.raises(readiness.LaunchIntentConflict):
        issue(bench, coordinator_decision_sha256="d" * 64)
    with pytest.raises(readiness.LaunchIntentConflict):
        issue(bench, ttl_seconds=600)


def test_readiness_requires_a_durable_reservation(bench):
    bench.seed(reserve=False)
    with pytest.raises(readiness.LaunchIntentError):
        issue(bench)


def test_readiness_rejects_stale_facts(bench):
    facts, _ = bench.seed()
    bench.advance("lease_acquired")
    with pytest.raises((facts_source.LaunchFactsStale,
                        readiness.LaunchIntentError)):
        readiness.record_launch_dispatch_intent(
            facts=facts, request_bytes=bench.raw, issued_at=now_iso(),
            ttl_seconds=300, **DECISION)


def test_readiness_rejects_wrong_request_bytes(bench, tmp_path):
    bench.seed()
    facts, _ = bench.capture()
    stranger = create_worker_request(
        **_build_inputs(tmp_path / "other", job_id="job_other"))
    with pytest.raises((facts_source.LaunchFactsStale,
                        readiness.LaunchIntentError)):
        readiness.record_launch_dispatch_intent(
            facts=facts, request_bytes=stranger.canonical_bytes(),
            issued_at=now_iso(), ttl_seconds=300, **DECISION)


@pytest.mark.parametrize("ttl", [0, -1, 901, 10_000])
def test_readiness_window_is_bounded(bench, ttl):
    bench.seed()
    with pytest.raises(readiness.LaunchIntentError):
        issue(bench, ttl_seconds=ttl)


@pytest.mark.parametrize("delta", [-3600, 3600])
def test_readiness_issue_time_must_be_current(bench, delta):
    bench.seed()
    skewed = (datetime.now(timezone.utc) +
              timedelta(seconds=delta)).isoformat()
    with pytest.raises(readiness.LaunchIntentError):
        issue(bench, issued_at=skewed)


@pytest.mark.parametrize("argument", ["root", "store", "projection", "now"])
def test_worker_cannot_select_root_store_or_clock(bench, argument):
    bench.seed()
    facts, _ = bench.capture()
    with pytest.raises(TypeError):
        readiness.record_launch_dispatch_intent(
            facts=facts, request_bytes=bench.raw, issued_at=now_iso(),
            ttl_seconds=300, **DECISION, **{argument: object()})


# --------------------------------------------------------- one-shot spend


def test_first_consumption_succeeds_and_grants_nothing(bench, signer):
    bench.seed()
    intent, _ = issue(bench)
    record = consume(bench, signer)
    assert record.job_id == bench.job_id
    assert record.attempt_id == bench.attempt_id
    assert record.request_id == bench.request.request_id
    assert record.dispatch_intent_sha256 == intent.intent_sha256
    assert record.authorization_id == "auth_gpf"
    body = record.to_dict()
    digest = body.pop("consumption_sha256")
    assert digest == hashlib.sha256(canonical(body)).hexdigest()
    for flag in binding._FLAGS:
        assert getattr(record, flag) is False
        assert record.to_dict()[flag] is False
    assert consumption.consumption_grants_no_capability() is True
    assert consumption.load_launch_consumption(
        job_id=bench.job_id, request_id=bench.request.request_id) == record


def test_identical_replay_after_consumption_is_refused(bench, signer):
    bench.seed()
    issue(bench)
    consume(bench, signer)
    with pytest.raises(consumption.LaunchAlreadyConsumed):
        consume(bench, signer)
    # A different authorization cannot spend the same opportunity either.
    with pytest.raises(consumption.LaunchAlreadyConsumed):
        consume(bench, signer, authorization_id="auth_other")


def test_consumption_requires_readiness(bench, signer):
    bench.seed()
    with pytest.raises(consumption.LaunchConsumptionError):
        consume(bench, signer)


def test_expired_readiness_is_refused(bench, signer, monkeypatch):
    bench.seed()
    issue(bench, ttl_seconds=60)
    monkeypatch.setattr(readiness.TrustedLaunchDispatchIntent, "is_expired",
                        lambda self, at: True)
    with pytest.raises(consumption.LaunchConsumptionError):
        consume(bench, signer)
    assert consumption.load_launch_consumption(
        job_id=bench.job_id, request_id=bench.request.request_id) is None


def test_changed_request_is_refused(bench, signer, tmp_path):
    bench.seed()
    issue(bench)
    stranger = create_worker_request(
        **_build_inputs(tmp_path / "other", job_id="job_other"))
    facts, _ = bench.capture()
    with pytest.raises((consumption.LaunchConsumptionError,
                        facts_source.LaunchFactsStale)):
        consumption.consume_launch_authorization(
            authorization_id="auth_gpf", authorization_sha256="c" * 64,
            facts=facts, request_bytes=stranger.canonical_bytes(),
            approvals=proofs(bench, signer))


def test_source_drift_after_readiness_is_refused(bench, signer):
    bench.seed()
    issue(bench)
    facts, _ = bench.capture()
    bench.advance("lease_acquired")
    with pytest.raises((consumption.LaunchConsumptionError,
                        facts_source.LaunchFactsStale)):
        consumption.consume_launch_authorization(
            authorization_id="auth_gpf", authorization_sha256="c" * 64,
            facts=facts, request_bytes=bench.raw,
            approvals=proofs(bench, signer))
    assert consumption.load_launch_consumption(
        job_id=bench.job_id, request_id=bench.request.request_id) is None


@pytest.mark.parametrize("kind,blocker", [
    ("cancellation_requested", "cancellation_requested"),
    ("cancelled", "cancelled"),
])
def test_cancellation_between_readiness_and_consumption_is_refused(
    bench, signer, kind, blocker,
):
    bench.seed()
    issue(bench)
    bench.advance(kind)
    with pytest.raises(consumption.LaunchConsumptionBlocked) as result:
        consume(bench, signer)
    assert blocker in result.value.blocker_codes
    assert result.value.consumption_recorded is False
    assert consumption.load_launch_consumption(
        job_id=bench.job_id, request_id=bench.request.request_id) is None


def test_execution_unknown_between_readiness_and_consumption_is_refused(
    bench, signer,
):
    bench.seed()
    issue(bench)
    bench.advance("lease_acquired")
    bench.advance("execution_unknown_declared")
    with pytest.raises(consumption.LaunchConsumptionBlocked) as result:
        consume(bench, signer)
    assert "execution_unknown" in result.value.blocker_codes
    assert consumption.load_launch_consumption(
        job_id=bench.job_id, request_id=bench.request.request_id) is None


def test_reconciliation_between_readiness_and_consumption_is_refused(
    bench, signer,
):
    bench.seed()
    issue(bench)
    bench.advance("lease_acquired")
    bench.advance("stalled")
    bench.advance("reconciliation_recorded")
    with pytest.raises(consumption.LaunchConsumptionBlocked) as result:
        consume(bench, signer)
    assert "reconciling" in result.value.blocker_codes
    assert consumption.load_launch_consumption(
        job_id=bench.job_id, request_id=bench.request.request_id) is None


def test_missing_human_gate_blocks_consumption(bench):
    bench.seed()
    issue(bench)
    facts, _ = bench.capture()
    with pytest.raises(consumption.LaunchConsumptionBlocked) as result:
        consumption.consume_launch_authorization(
            authorization_id="auth_gpf", authorization_sha256="c" * 64,
            facts=facts, request_bytes=bench.raw)
    assert "required_gate_missing" in result.value.blocker_codes


def test_retry_attempt_cannot_reuse_readiness_or_consumption(bench, signer):
    """A retry is a new attempt, hence a new request slot, hence no reuse."""
    bench.seed()
    intent, _ = issue(bench)
    consume(bench, signer)
    successor = "attempt_job_gpf4_2"
    assert intent.attempt_id != successor
    assert consumption.load_launch_consumption(
        job_id=bench.job_id, request_id=bench.request.request_id) is not None
    # The successor attempt has no readiness and no spent-marker of its own.
    successor_request = "gpe_" + hashlib.sha256(canonical(
        ["gpe-worker-v1", bench.job_id, successor])).hexdigest()[:60]
    with pytest.raises(readiness.LaunchIntentError):
        readiness.load_launch_dispatch_intent(
            job_id=bench.job_id, request_id=successor_request)
    assert consumption.load_launch_consumption(
        job_id=bench.job_id, request_id=successor_request) is None


def test_drift_around_the_write_burns_the_opportunity(bench, signer,
                                                      monkeypatch):
    """Post-write drift must refuse dispatch, not dispatch against drift."""
    bench.seed()
    issue(bench)
    original = consumption._current
    state = {"calls": 0}

    def drifting(facts, request_bytes, approvals):
        result = original(facts, request_bytes, approvals)
        state["calls"] += 1
        if state["calls"] == 1:
            bench.advance("cancellation_requested")
        return result

    monkeypatch.setattr(consumption, "_current", drifting)
    with pytest.raises(consumption.LaunchConsumptionDrift) as result:
        consume(bench, signer)
    assert result.value.consumption_recorded is True
    # The opportunity is spent: the marker exists and can never be reused.
    assert consumption.load_launch_consumption(
        job_id=bench.job_id, request_id=bench.request.request_id) is not None


def test_no_worker_or_provider_is_invoked(bench, signer):
    bench.seed()
    issue(bench)
    record = consume(bench, signer)
    assert not hasattr(consumption, "dispatch")
    assert not hasattr(consumption, "invoke_worker")
    assert record.launch_authorized is False
    assert record.worker_output_trusted is False


# ------------------------------------------------------- protected surface


def test_new_authority_surfaces_are_protected():
    registry = create_mootos_tcb_registry_v1()
    paths = (
        "backend/continuous_builder/gpf_launch_dispatch_intent.py",
        "backend/continuous_builder/gpf_launch_consumption.py",
    )
    for path in paths:
        assert path in registry.protected_paths
        assert registry.component_for_path(path).change_policy == "human_only"
    assert evaluate_changed_paths_against_tcb(
        list(paths)).outcome == OUTCOME_FORBIDDEN


def test_trusted_launch_authorization_still_does_not_exist():
    for module in (readiness, consumption):
        assert not hasattr(module, "TrustedLaunchAuthorization")
        assert not hasattr(module, "authorize_launch")


def test_benign_source_change_does_not_void_readiness(bench, signer):
    """A heartbeat is not a blocker; only a semantic blocker refuses.

    Readiness names a candidate, not a byte-for-byte source snapshot, so
    ordinary ledger movement must not silently void a selection while a
    cancellation reports the same coarse error.
    """
    bench.seed()
    intent, _ = issue(bench)
    bench.advance("lease_acquired")
    record = consume(bench, signer)
    assert record.dispatch_intent_sha256 == intent.intent_sha256
    # The intent still records the snapshot it was selected against, and the
    # consumption record records the snapshot actually decided against.
    assert record.source_tokens_sha256 != intent.source_tokens_sha256
