"""Trusted launch-eligibility semantics; synthetic keys, no real launch."""

import ast
import hashlib
import inspect
import json
import sqlite3
from types import MappingProxyType, SimpleNamespace

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from backend.continuous_builder import gpf_approval_authority as authority
from backend.continuous_builder import gpf_launch_candidate_binding as binding
from backend.continuous_builder import gpf_launch_facts as facts_source
from backend.continuous_builder import gpf_launch_semantics as semantics
from backend.continuous_builder import gpf_launch_state_projection as project
from backend.continuous_builder.gpd_heartbeat_lease import create_lease_record
from backend.continuous_builder.gpd_job_store import JobLedgerStore
from backend.continuous_builder.gpd_side_effect import (
    create_reconciliation_record,
)
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

ANCIENT = "2019-01-01T00:00:00+00:00"
PAST = "2020-01-01T00:00:00+00:00"
FUTURE = "2099-01-01T00:00:00+00:00"
READY = (
    ("job_created", {}), ("job_admitted", {}), ("job_ready", {}),
    ("attempt_started", {"attempt": True}),
)


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode()


def seal(body, field="receipt_sha256"):
    body = dict(body)
    body.pop(field, None)
    body[field] = hashlib.sha256(canonical(body)).hexdigest()
    return canonical(body)


@pytest.fixture
def signer(monkeypatch):
    # Ephemeral synthetic key in test memory only. The enrolled human key
    # at /Users/freeman/.mootos is never read, imported or referenced.
    private = Ed25519PrivateKey.generate()
    public = private.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    key_id = "sha256:" + hashlib.sha256(public).hexdigest()
    monkeypatch.setattr(authority, "_AUTHORIZED_PUBLIC_KEYS",
                        MappingProxyType({key_id: public}))
    return private, key_id


def proof(raw, signer):
    private, key_id = signer
    return (raw, private.sign(authority.DOMAIN + raw), key_id)


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
    args = dict(job_id=job_id, attempt_id=attempt_id, request_bytes=raw,
                blueprint_id="blueprint_gpf4", blueprint_version="1",
                slice_id="slice_gpf4", created_at=TS)
    store = JobLedgerStore(root)
    path = (root / "launch_bindings" / job_id / (request.request_id + ".json"))

    def seed(events=READY, leases=(), reconciliations=(), reserve=True,
             assign=True):
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
        for lease in leases:
            store.append_lease(lease)
        for record in reconciliations:
            store.append_reconciliation(record)
        if reserve:
            store.write_dispatch_reservation(
                create_dispatch_reservation(request=request))
        if assign:
            binding.assign_launch_candidate(**args)
            return capture()
        return None

    def capture():
        record = facts_source.capture_launch_facts(
            job_id=job_id, request_id=request.request_id, request_bytes=raw)
        return project.project_launch_state(facts=record, request_bytes=raw)

    return SimpleNamespace(
        seed=seed, capture=capture, inputs=inputs, request=request, root=root,
        database=database, job_id=job_id, attempt_id=attempt_id, args=args,
        store=store, raw=raw, path=path)


def receipt_proofs(bench, signer, gates=("human_review", "unit_tests"),
                   **overrides):
    proofs = []
    for gate in gates:
        record = create_human_approval_receipt(
            request=bench.request, gate=gate, approval_id="appr_" + gate,
            supplied_approver_identity="claimed_human",
            approved_capability_ids=("cb.repo.read",),
            approved_scope=("backend/widget.py",),
            created_at=overrides.pop("created_at", TS),
            valid_until=overrides.pop("valid_until", FUTURE))
        body = dict(record.to_dict())
        body.update(overrides)
        if {"approved_scope", "approved_capability_ids"} & set(overrides):
            body["subject_sha256"] = hashlib.sha256(canonical({
                "approved_capability_ids": body["approved_capability_ids"],
                "approved_scope": body["approved_scope"],
            })).hexdigest()
        proofs.append(proof(seal(body), signer))
    return tuple(proofs)


def evaluate(pair, approvals=()):
    return semantics.evaluate_launch_eligibility(
        facts=pair[0], projection=pair[1], approvals=approvals)


# ------------------------------------------------------------- eligible


def test_clean_exact_facts_are_eligible(bench, signer):
    pair = bench.seed()
    result = evaluate(pair, receipt_proofs(bench, signer))
    assert result.blocker_codes == ()
    assert result.eligible is True
    assert (result.job_id, result.attempt_id, result.request_id) == (
        bench.job_id, bench.attempt_id, bench.request.request_id)
    body = result.to_dict()
    digest = body.pop("eligibility_sha256")
    assert digest == hashlib.sha256(canonical(body)).hexdigest()
    for flag in binding._FLAGS:
        assert getattr(result, flag) is False
        assert result.to_dict()[flag] is False
    assert not hasattr(result, "launch_ready")
    assert semantics.launch_eligibility_grants_no_capability() is True


def test_eligibility_is_not_authorization(bench, signer):
    result = evaluate(bench.seed(), receipt_proofs(bench, signer))
    assert result.eligible is True
    assert result.launch_authorized is False
    assert not hasattr(semantics, "TrustedLaunchAuthorization")
    assert not hasattr(semantics, "authorize_launch")


# ------------------------------------------------------------- currentness


def test_stale_source_blocks(bench, signer):
    facts, projection = bench.seed()
    last = bench.store.load_events(bench.job_id)[-1]
    bench.store.append_event(_event(len(bench.store.load_events(
        bench.job_id)) + 1, "lease_acquired", bench.job_id, last.event_digest))
    fresh = facts_source.capture_launch_facts(
        job_id=bench.job_id, request_id=bench.request.request_id,
        request_bytes=bench.raw)
    result = evaluate((fresh, projection), receipt_proofs(bench, signer))
    assert result.blocker_codes == ("facts_stale",)
    assert result.eligible is False


def test_binding_missing_blocks(bench, signer):
    pair = bench.seed()
    bench.path.unlink()
    result = evaluate(pair, receipt_proofs(bench, signer))
    assert result.blocker_codes == ("binding_missing",)


def test_binding_mismatch_blocks(bench, signer):
    pair = bench.seed()
    body = json.loads(bench.path.read_bytes())
    body["created_at"] = "2026-09-09T00:00:00+00:00"
    bench.path.write_bytes(seal(body, "binding_sha256"))
    result = evaluate(pair, receipt_proofs(bench, signer))
    assert result.blocker_codes == ("binding_mismatch",)


# ------------------------------------------------------------ reservation


def test_missing_reservation_blocks(bench, signer):
    pair = bench.seed(reserve=False)
    result = evaluate(pair, receipt_proofs(bench, signer))
    assert result.blocker_codes == ("reservation_missing",)


def test_reservation_bound_to_another_request_blocks(bench, signer):
    bench.store.write_header(bench.inputs["header"])
    bench.store.append_attempt(bench.inputs["attempt"])
    previous = None
    for sequence, (kind, extra) in enumerate(READY, 1):
        values = {"attempt_id": bench.attempt_id} if extra else {}
        event = _event(sequence, kind, bench.job_id, previous, **values)
        bench.store.append_event(event)
        previous = event.event_digest
    bench.store.write_dispatch_reservation(
        create_dispatch_reservation(request=bench.request))
    slot = (bench.root / "jobs" / bench.job_id / "attempts" /
            bench.attempt_id / "dispatch_reservation.json")
    body = json.loads(slot.read_bytes())
    body["request_sha256"] = "e" * 64
    slot.write_bytes(seal(body, "reservation_sha256"))
    binding.assign_launch_candidate(**bench.args)
    result = evaluate(bench.capture(), receipt_proofs(bench, signer))
    assert result.blocker_codes == ("reservation_mismatch",)


# -------------------------------------------------------------- lifecycle


def test_superseded_attempt_blocks(bench, signer):
    pair = bench.seed(READY + (
        ("attempt_started", {"attempt_id": "attempt_successor"}),))
    result = evaluate(pair, receipt_proofs(bench, signer))
    assert result.blocker_codes == ("attempt_superseded",)


@pytest.mark.parametrize("events,expected", [
    (READY + (("cancellation_requested", {}),), "cancellation_requested"),
    (READY + (("cancelled", {}),), "cancelled"),
    (READY + (("lease_acquired", {}), ("execution_unknown_declared", {})),
     "execution_unknown"),
    (READY + (("lease_acquired", {}), ("stalled", {}),
              ("reconciliation_recorded", {})), "reconciling"),
    (READY + (("lease_acquired", {}), ("stalled", {})), "stalled"),
    (READY + (("lease_acquired", {}), ("timed_out", {})), "timed_out"),
    (READY + (("lease_acquired", {}), ("running_marked", {}),
              ("failed", {})), "failed"),
    (READY + (("lease_acquired", {}), ("running_marked", {}),
              ("terminal_failure", {})), "job_terminal"),
    (READY + (("lease_acquired", {}), ("running_marked", {}),
              ("terminal_success", {"payload": {"system_proof": True}})),
     "job_terminal"),
])
def test_lifecycle_states_block(bench, signer, events, expected):
    result = evaluate(bench.seed(events), receipt_proofs(bench, signer))
    assert expected in result.blocker_codes
    assert result.eligible is False


def test_reconciliation_holding_record_blocks(bench, signer):
    record = create_reconciliation_record(
        reconciliation_id="rec_hold", job_id=bench.job_id,
        attempt_id=bench.attempt_id, side_effect_id=None,
        verdict="needs_human", evidence_digest="c" * 64,
        actor_id="supervisor", reconciled_at=TS,
        clears_execution_unknown=False, retry_eligible_after=False)
    pair = bench.seed(reconciliations=(record,))
    result = evaluate(pair, receipt_proofs(bench, signer))
    assert result.blocker_codes == ("reconciliation_required",)


def test_expired_lease_is_ambiguous_not_proof_of_no_execution(bench, signer):
    lease = create_lease_record(
        lease_id="lease_expired", job_id=bench.job_id,
        attempt_id=bench.attempt_id, owner_id="worker_slot",
        acquired_at=ANCIENT, expires_at=PAST, released_at=None)
    pair = bench.seed(leases=(lease,))
    result = evaluate(pair, receipt_proofs(bench, signer))
    assert result.blocker_codes == ("reconciliation_required",
                                    "lease_ambiguous")
    assert pair[1].lease_expired is True
    assert pair[1].lease_reconciled is False


def test_unexpired_lease_alone_does_not_block(bench, signer):
    lease = create_lease_record(
        lease_id="lease_live", job_id=bench.job_id,
        attempt_id=bench.attempt_id, owner_id="worker_slot",
        acquired_at=TS, expires_at=FUTURE, released_at=None)
    pair = bench.seed(leases=(lease,))
    assert pair[1].lease_present is True
    assert evaluate(pair, receipt_proofs(bench, signer)).eligible is True


# ------------------------------------------------- correlation / admission


def forge_correlation(request, **changes):
    """Rewrite the request's signed product correlation, resealing both."""
    body = json.loads(request.canonical_bytes())
    correlation = dict(body["correlation"])
    correlation.update(changes)
    body["correlation"] = json.loads(seal(correlation, "digest"))
    return seal(body, "digest")


def test_mismatched_product_correlation_blocks(bench, signer):
    forged = forge_correlation(bench.request, blueprint_id="blueprint_other")
    bench.seed(assign=False)
    # The real writer refuses a packet whose correlation contradicts the
    # assignment, so only a hand-forged binding can reach this state.
    with pytest.raises(binding.LaunchBindingError):
        binding.assign_launch_candidate(
            **{**bench.args, "request_bytes": forged})
    header = bench.inputs["header"]
    body = dict(schema_version=binding.VERSION, job_id=bench.job_id,
                header_sha256=header.header_sha256,
                attempt_id=bench.attempt_id,
                request_id=bench.request.request_id,
                request_sha256=json.loads(forged)["digest"],
                blueprint_id="blueprint_gpf4", blueprint_version="1",
                blueprint_sha256="b" * 64, slice_id="slice_gpf4",
                slice_version="1",
                admission_decision_id=header.admission_decision_id,
                admission_decision_sha256=header.admission_decision_sha256,
                created_at=TS, **{flag: False for flag in binding._FLAGS})
    bench.path.parent.mkdir(parents=True, exist_ok=True)
    bench.path.write_bytes(seal(body, "binding_sha256"))
    facts = facts_source.capture_launch_facts(
        job_id=bench.job_id, request_id=bench.request.request_id,
        request_bytes=forged)
    facts, projection = project.project_launch_state(
        facts=facts, request_bytes=forged)
    assert projection.correlation_verified is False
    result = semantics.evaluate_launch_eligibility(
        facts=facts, projection=projection,
        approvals=receipt_proofs(bench, signer))
    assert "product_correlation_unverified" in result.blocker_codes
    assert result.eligible is False


def test_tcb_drift_makes_admission_incompatible(bench, signer, monkeypatch):
    pair = bench.seed()
    monkeypatch.setattr(semantics, "create_mootos_tcb_registry_v1",
                        lambda: SimpleNamespace(registry_sha256="0" * 64))
    result = evaluate(pair, receipt_proofs(bench, signer))
    assert result.blocker_codes == ("admission_incompatible",)


# --------------------------------------------------------------- approval


def test_missing_gate_blocks(bench):
    assert evaluate(bench.seed()).blocker_codes == ("required_gate_missing",)


def test_partial_gate_coverage_blocks(bench, signer):
    proofs = receipt_proofs(bench, signer, gates=("human_review",))
    assert evaluate(bench.seed(), proofs).blocker_codes == (
        "required_gate_missing",)


def test_invalid_signature_blocks(bench, signer):
    raw, _, key_id = receipt_proofs(bench, signer, gates=("human_review",))[0]
    forged = (raw, bytes(64), key_id)
    result = evaluate(bench.seed(), (forged,))
    assert result.blocker_codes == ("required_gate_missing",
                                    "approval_invalid")


def test_expired_approval_blocks(bench, signer):
    proofs = receipt_proofs(bench, signer, created_at=ANCIENT,
                            valid_until=PAST)
    result = evaluate(bench.seed(), proofs)
    assert result.blocker_codes == ("required_gate_missing",
                                    "approval_expired")


def test_approval_for_another_attempt_blocks(tmp_path, bench, signer):
    other = _build_inputs(tmp_path / "other", job_id="job_other")
    stranger = create_worker_request(**other)
    record = create_human_approval_receipt(
        request=stranger, gate="human_review", approval_id="appr_stranger",
        supplied_approver_identity="claimed_human",
        approved_capability_ids=(), approved_scope=(), created_at=TS)
    result = evaluate(bench.seed(),
                      (proof(canonical(record.to_dict()), signer),))
    assert result.blocker_codes == ("required_gate_missing",
                                    "approval_wrong_attempt",
                                    "approval_wrong_request")


def test_approval_for_another_request_digest_blocks(bench, signer):
    proofs = receipt_proofs(bench, signer, gates=("human_review",),
                            request_sha256="d" * 64)
    result = evaluate(bench.seed(), proofs)
    assert result.blocker_codes == ("required_gate_missing",
                                    "approval_wrong_request")


def test_scope_widening_blocks(bench, signer):
    proofs = receipt_proofs(bench, signer,
                            approved_scope=["backend/secrets.py"])
    result = evaluate(bench.seed(), proofs)
    assert result.blocker_codes == ("scope_widening",)


def test_capability_widening_blocks(bench, signer):
    proofs = receipt_proofs(bench, signer,
                            approved_capability_ids=["cb.repo.write"])
    result = evaluate(bench.seed(), proofs)
    assert result.blocker_codes == ("capability_widening",)


def test_narrowing_approval_is_accepted(bench, signer):
    proofs = receipt_proofs(bench, signer, approved_scope=[],
                            approved_capability_ids=[])
    assert evaluate(bench.seed(), proofs).eligible is True


def test_signature_never_overrides_another_blocker(bench, signer):
    pair = bench.seed(READY + (("cancelled", {}),))
    result = evaluate(pair, receipt_proofs(bench, signer))
    assert result.eligible is False
    assert "cancelled" in result.blocker_codes


# --------------------------------------------------------------- ordering


def test_multiple_blockers_use_canonical_order(bench, signer):
    lease = create_lease_record(
        lease_id="lease_expired", job_id=bench.job_id,
        attempt_id=bench.attempt_id, owner_id="worker_slot",
        acquired_at=ANCIENT, expires_at=PAST, released_at=None)
    pair = bench.seed(
        READY + (("lease_acquired", {}), ("execution_unknown_declared", {})),
        leases=(lease,), reserve=False)
    proofs = receipt_proofs(bench, signer, gates=("human_review",),
                            created_at=ANCIENT, valid_until=PAST)
    result = evaluate(pair, proofs)
    assert result.blocker_codes == (
        "reservation_missing", "execution_unknown", "reconciliation_required",
        "lease_ambiguous", "required_gate_missing", "approval_expired")
    order = [semantics.BLOCKER_CODES.index(c) for c in result.blocker_codes]
    assert order == sorted(order)
    assert evaluate(pair, proofs).blocker_codes == result.blocker_codes


def test_blocker_vocabulary_is_complete_and_unique():
    required = {
        "facts_stale", "binding_missing", "binding_mismatch",
        "reservation_missing", "reservation_mismatch", "attempt_superseded",
        "cancellation_requested", "cancelled", "execution_unknown",
        "reconciliation_required", "reconciling", "stalled", "timed_out",
        "failed", "job_terminal", "lease_ambiguous",
        "product_correlation_unverified",
        "admission_incompatible", "required_gate_missing", "approval_invalid",
        "approval_expired", "approval_wrong_attempt", "approval_wrong_request",
        "scope_widening", "capability_widening",
    }
    assert set(semantics.BLOCKER_CODES) == required
    assert len(set(semantics.BLOCKER_CODES)) == len(semantics.BLOCKER_CODES)


# ------------------------------------------------------------- projection


def test_projection_is_evidence_without_authority(bench):
    facts, projection = bench.seed()
    assert projection.schema_version == project.VERSION
    assert projection.derived_state == "ready"
    assert projection.current_attempt_id == bench.attempt_id
    assert projection.facts_sha256 == facts.facts_sha256
    assert projection.required_gates == ("human_review", "unit_tests")
    body = projection.to_dict()
    digest = body.pop("projection_sha256")
    assert digest == hashlib.sha256(canonical(body)).hexdigest()
    for flag in binding._FLAGS:
        assert getattr(projection, flag) is False
        assert projection.to_dict()[flag] is False
    assert not hasattr(projection, "eligible")


def test_projection_refuses_stale_facts(bench):
    facts, _ = bench.seed()
    last = bench.store.load_events(bench.job_id)[-1]
    bench.store.append_event(_event(last.sequence + 1, "lease_acquired",
                                    bench.job_id, last.event_digest))
    with pytest.raises(facts_source.LaunchFactsStale):
        project.project_launch_state(facts=facts, request_bytes=bench.raw)


def test_projection_fails_closed_on_corrupt_sources(bench):
    bench.seed()
    facts = facts_source.capture_launch_facts(
        job_id=bench.job_id, request_id=bench.request.request_id,
        request_bytes=bench.raw)
    (bench.root / "jobs" / bench.job_id / "leases.jsonl").write_bytes(
        b"malformed\n")
    with pytest.raises((project.LaunchStateProjectionError,
                        facts_source.LaunchFactsStale)):
        project.project_launch_state(facts=facts, request_bytes=bench.raw)


@pytest.mark.parametrize("argument", ["root", "store", "now", "state"])
def test_projection_takes_no_caller_source_or_clock(bench, argument):
    facts, _ = bench.seed()
    with pytest.raises(TypeError):
        project.project_launch_state(
            facts=facts, request_bytes=bench.raw, **{argument: object()})


# ------------------------------------------------------- trusted closure


def test_untrusted_records_are_refused(bench):
    facts, projection = bench.seed()
    for kwargs in (dict(facts=SimpleNamespace(), projection=projection),
                   dict(facts=facts, projection=SimpleNamespace()),
                   dict(facts=facts, projection=projection, approvals=[])):
        with pytest.raises(semantics.LaunchSemanticsError):
            semantics.evaluate_launch_eligibility(**kwargs)


@pytest.mark.parametrize("argument", ["root", "store", "at", "now",
                                      "required_gates"])
def test_no_caller_supplied_source_or_clock(bench, argument):
    facts, projection = bench.seed()
    with pytest.raises(TypeError):
        semantics.evaluate_launch_eligibility(
            facts=facts, projection=projection, **{argument: object()})


def test_transitive_import_closure_excludes_execution_stacks():
    from pathlib import Path
    root = Path(inspect.getfile(semantics)).parent
    pending, seen = ["gpf_launch_semantics"], set()
    while pending:
        module = pending.pop()
        if module in seen:
            continue
        seen.add(module)
        for node in ast.walk(ast.parse((root / (module + ".py")).read_text())):
            if isinstance(node, ast.ImportFrom) and node.level:
                if node.module:
                    pending.append(node.module)
                else:
                    pending.extend(alias.name for alias in node.names)
    assert seen == {
        "gpf_launch_semantics", "gpf_launch_state_projection",
        "gpf_launch_facts", "gpf_launch_candidate_binding",
        "gpf_approval_authority", "gpc_trusted_admission_core",
        "gpd_job_state", "gpd_job_events", "gpd_job_header",
        "gpa_eval_schema", "timestamps", "trusted_policy", "paths",
        "text_safety",
    }
    for forbidden in ("context_engine", "system_model", "gpe_protocol",
                      "gpf_supervisor", "gpf_launch_preparation",
                      "gpf_binding_resolution", "gpd_job_store",
                      "gpd_recovery"):
        assert forbidden not in seen


def test_new_modules_are_protected_tcb_paths():
    registry = create_mootos_tcb_registry_v1()
    paths = (
        "backend/continuous_builder/gpf_launch_semantics.py",
        "backend/continuous_builder/gpf_launch_state_projection.py",
    )
    for path in paths:
        assert path in registry.protected_paths
        component = registry.component_for_path(path)
        assert component.change_policy == "human_only"
    outcome = evaluate_changed_paths_against_tcb(list(paths))
    assert outcome.outcome == OUTCOME_FORBIDDEN
