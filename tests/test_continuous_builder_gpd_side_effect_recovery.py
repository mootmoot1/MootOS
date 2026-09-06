"""Focused tests for GP-D7/D8 side-effect, EXECUTION_UNKNOWN, recovery."""

import pytest

from backend.continuous_builder.gpd_attempt_ledger import create_attempt_record
from backend.continuous_builder.gpd_job_events import create_job_event
from backend.continuous_builder.gpd_job_header import create_durable_job_header
from backend.continuous_builder.gpd_job_store import JobLedgerStore, JobStoreError
from backend.continuous_builder.gpd_recovery import (
    RecoveryError,
    reconstruct_job,
    recovery_does_not_launch,
    recovery_is_deterministic,
)
from backend.continuous_builder.gpd_side_effect import (
    SideEffectError,
    create_reconciliation_record,
    create_side_effect_identity,
    detect_duplicate_side_effect_identity,
    execution_unknown_blocks_blind_retry,
    retry_eligibility,
)

DIGEST = "a" * 64
BASE = "48233394d4ccce88244adc5c7133efea92df60fb"
TS = "2026-09-06T22:00:00+00:00"
TS2 = "2026-09-06T22:05:00+00:00"
TS3 = "2026-09-06T22:10:00+00:00"


def _header(**overrides):
    values = dict(
        job_id="job_gpd_rec",
        repository_identity="mootmoot1/MootOS",
        base_sha=BASE,
        task_contract_id="tc_gpd_001",
        task_contract_sha256=DIGEST,
        execution_plan_id="plan_gpd_001",
        execution_plan_sha256=DIGEST,
        admission_decision_id="gpc_decision_001",
        admission_decision_sha256=DIGEST,
        architecture_baseline_sha256=DIGEST,
        trusted_policy_version="cb-trusted-policy-tcb-v1",
        tcb_registry_sha256=DIGEST,
        tcb_snapshot_sha256=DIGEST,
        approved_scope_ceiling=(
            "tests/fixtures/gpa_eval/nb_001/widget_counter.py",
        ),
        forbidden_scope=("backend/continuous_builder/trusted_policy.py",),
        admitted_capability_ids=("cb.repo.read",),
        budget_ceiling_wall_clock_seconds=600,
        required_gates=("human_review", "unit_tests"),
        logical_order=1,
        created_at=TS,
    )
    values.update(overrides)
    return create_durable_job_header(**values)


def _seed(store):
    header = _header()
    store.write_header(header)
    e1 = create_job_event(
        event_id="evt_0001", job_id=header.job_id, sequence=1,
        event_kind="job_created", actor_kind="system", actor_id="system_gpd",
        reason_code="create", created_at=TS,
    )
    store.append_event(e1)
    e2 = create_job_event(
        event_id="evt_0002", job_id=header.job_id, sequence=2,
        previous_event_digest=e1.event_digest, event_kind="job_admitted",
        actor_kind="system", actor_id="system_gpd", reason_code="admit",
        created_at=TS,
    )
    store.append_event(e2)
    e3 = create_job_event(
        event_id="evt_0003", job_id=header.job_id, sequence=3,
        previous_event_digest=e2.event_digest, event_kind="job_ready",
        actor_kind="system", actor_id="system_gpd", reason_code="ready",
        created_at=TS,
    )
    store.append_event(e3)
    return header, e3


def test_history_survives_restart(tmp_path):
    store = JobLedgerStore(tmp_path / "ledger")
    header, _ = _seed(store)
    store2 = JobLedgerStore(tmp_path / "ledger")
    loaded = store2.load_header(header.job_id)
    assert loaded.header_sha256 == header.header_sha256
    events = store2.load_events(header.job_id)
    assert len(events) == 3
    view = reconstruct_job(store2, header.job_id)
    assert view.state.state == "ready"
    assert view.human_gates == ("human_review", "unit_tests")
    assert recovery_is_deterministic(store2, header.job_id)
    assert recovery_does_not_launch() is True


def test_duplicate_event_rejected_by_store(tmp_path):
    store = JobLedgerStore(tmp_path / "ledger")
    header, last = _seed(store)
    dup = create_job_event(
        event_id="evt_0001", job_id=header.job_id, sequence=4,
        previous_event_digest=last.event_digest, event_kind="lease_acquired",
        actor_kind="system", actor_id="system_gpd", reason_code="dup",
        created_at=TS, attempt_id="att_001",
    )
    with pytest.raises(JobStoreError):
        store.append_event(dup)


def test_execution_unknown_blocks_blind_retry(tmp_path):
    store = JobLedgerStore(tmp_path / "ledger")
    header, last = _seed(store)
    e4 = create_job_event(
        event_id="evt_0004", job_id=header.job_id, sequence=4,
        previous_event_digest=last.event_digest, event_kind="lease_acquired",
        actor_kind="system", actor_id="system_gpd", reason_code="lease",
        created_at=TS, attempt_id="att_001",
    )
    store.append_event(e4)
    e5 = create_job_event(
        event_id="evt_0005", job_id=header.job_id, sequence=5,
        previous_event_digest=e4.event_digest, event_kind="running_marked",
        actor_kind="system", actor_id="system_gpd", reason_code="run",
        created_at=TS, attempt_id="att_001",
    )
    store.append_event(e5)
    e6 = create_job_event(
        event_id="evt_0006", job_id=header.job_id, sequence=6,
        previous_event_digest=e5.event_digest,
        event_kind="execution_unknown_declared",
        actor_kind="supervisor", actor_id="supervisor_gpd",
        reason_code="lost_contact", created_at=TS2, attempt_id="att_001",
    )
    store.append_event(e6)
    se = create_side_effect_identity(
        side_effect_id="se_001",
        job_id=header.job_id,
        attempt_id="att_001",
        op_type="github_pr_create",
        target="mootmoot1/MootOS",
        idempotency_key="idem_pr_001",
        request_digest=DIGEST,
        status="uncertain",
        certainty="unknown",
        created_at=TS2,
    )
    store.append_side_effect(se)
    view = reconstruct_job(store, header.job_id)
    assert view.state.state == "execution_unknown"
    assert view.blind_retry_blocked is True
    assert view.retry_eligible is False
    assert execution_unknown_blocks_blind_retry(
        view.state.state, view.side_effects
    )


def test_reconcile_then_retry_eligible(tmp_path):
    store = JobLedgerStore(tmp_path / "ledger")
    header, last = _seed(store)
    # advance to execution_unknown quickly via ready->... actually need path
    e4 = create_job_event(
        event_id="evt_0004", job_id=header.job_id, sequence=4,
        previous_event_digest=last.event_digest, event_kind="lease_acquired",
        actor_kind="system", actor_id="system_gpd", reason_code="lease",
        created_at=TS, attempt_id="att_001",
    )
    store.append_event(e4)
    e5 = create_job_event(
        event_id="evt_0005", job_id=header.job_id, sequence=5,
        previous_event_digest=e4.event_digest,
        event_kind="execution_unknown_declared",
        actor_kind="supervisor", actor_id="supervisor_gpd",
        reason_code="lost_contact", created_at=TS2, attempt_id="att_001",
    )
    store.append_event(e5)
    rec = create_reconciliation_record(
        reconciliation_id="rec_001",
        job_id=header.job_id,
        attempt_id="att_001",
        side_effect_id=None,
        verdict="side_effect_confirmed_absent",
        evidence_digest=DIGEST,
        actor_id="human_ops",
        reconciled_at=TS3,
        clears_execution_unknown=True,
        retry_eligible_after=True,
    )
    store.append_reconciliation(rec)
    e6 = create_job_event(
        event_id="evt_0006", job_id=header.job_id, sequence=6,
        previous_event_digest=e5.event_digest,
        event_kind="reconciliation_recorded",
        actor_kind="human", actor_id="human_ops",
        reason_code="reconciled", created_at=TS3, attempt_id="att_001",
        payload={"clears_execution_unknown": True},
    )
    store.append_event(e6)
    view = reconstruct_job(store, header.job_id)
    assert view.state.state == "reconciling"
    assert retry_eligibility(
        "retryable", reconciliation=rec, side_effects=()
    )


def test_duplicate_side_effect_detected():
    se1 = create_side_effect_identity(
        side_effect_id="se_001",
        job_id="job_gpd_rec",
        attempt_id="att_001",
        op_type="filesystem_write",
        target="tmp/out.txt",
        idempotency_key="idem_1",
        request_digest=DIGEST,
        status="proposed",
        certainty="certain",
        created_at=TS,
    )
    se2 = create_side_effect_identity(
        side_effect_id="se_001",
        job_id="job_gpd_rec",
        attempt_id="att_001",
        op_type="filesystem_write",
        target="tmp/out.txt",
        idempotency_key="idem_1",
        request_digest=DIGEST,
        status="proposed",
        certainty="certain",
        created_at=TS,
    )
    with pytest.raises(SideEffectError):
        detect_duplicate_side_effect_identity([se1], se2)


def test_stale_contract_rejected_on_recovery(tmp_path):
    store = JobLedgerStore(tmp_path / "ledger")
    header, _ = _seed(store)
    with pytest.raises(RecoveryError):
        reconstruct_job(
            store, header.job_id, expected_contract_sha256="d" * 64
        )


def test_header_immutable(tmp_path):
    store = JobLedgerStore(tmp_path / "ledger")
    header, _ = _seed(store)
    other = _header(logical_order=2)
    # same job_id but different digest
    other = _header(budget_ceiling_wall_clock_seconds=999)
    with pytest.raises(JobStoreError):
        store.write_header(other)


def test_new_attempt_on_retry(tmp_path):
    store = JobLedgerStore(tmp_path / "ledger")
    header, _ = _seed(store)
    a1 = create_attempt_record(
        attempt_id="att_001", job_id=header.job_id, attempt_number=1,
        owner_id="owner_a", started_at=TS, status="started",
        header_sha256=header.header_sha256,
    )
    store.append_attempt(a1)
    a2 = create_attempt_record(
        attempt_id="att_002", job_id=header.job_id, attempt_number=2,
        owner_id="owner_a", started_at=TS2, status="started",
        prior_attempt_id="att_001", header_sha256=header.header_sha256,
    )
    store.append_attempt(a2)
    attempts = store.load_attempts(header.job_id)
    assert [a.attempt_id for a in attempts] == ["att_001", "att_002"]
