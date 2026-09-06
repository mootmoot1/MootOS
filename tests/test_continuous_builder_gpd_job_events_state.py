"""Focused tests for GP-D2 events and GP-D3 state reducer."""

import pytest

from backend.continuous_builder.gpd_job_events import (
    JobEventError,
    create_job_event,
    validate_event_chain,
)
from backend.continuous_builder.gpd_job_header import create_durable_job_header
from backend.continuous_builder.gpd_job_state import (
    JobStateError,
    reduce_job_state,
)

DIGEST = "a" * 64
BASE = "48233394d4ccce88244adc5c7133efea92df60fb"
TS = "2026-09-06T22:00:00+00:00"


def _header():
    return create_durable_job_header(
        job_id="job_gpd_evt",
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
        required_gates=("human_review",),
        logical_order=1,
        created_at=TS,
    )


def _event(seq, kind, prev=None, **kwargs):
    values = dict(
        event_id=f"evt_{seq:04d}",
        job_id="job_gpd_evt",
        sequence=seq,
        previous_event_digest=prev,
        event_kind=kind,
        actor_kind="system",
        actor_id="system_gpd",
        reason_code="unit_test",
        payload={},
        created_at=TS,
    )
    values.update(kwargs)
    return create_job_event(**values)


def test_digest_chain_and_reducer():
    e1 = _event(1, "job_created")
    e2 = _event(2, "job_admitted", e1.event_digest)
    e3 = _event(3, "job_ready", e2.event_digest)
    validate_event_chain([e1, e2, e3])
    state = reduce_job_state(_header(), [e1, e2, e3])
    assert state.state == "ready"
    assert state.sequence == 3
    assert state.required_gates == ("human_review",)


def test_duplicate_event_id_rejected():
    e1 = _event(1, "job_created")
    e2 = _event(2, "job_admitted", e1.event_digest, event_id="evt_0001")
    with pytest.raises(JobEventError):
        validate_event_chain([e1, e2])


def test_sequence_violation():
    e1 = _event(1, "job_created")
    e2 = _event(2, "job_admitted", e1.event_digest)
    # Gap: claiming sequence 4 after 2.
    e4 = create_job_event(
        event_id="evt_0004",
        job_id="job_gpd_evt",
        sequence=4,
        previous_event_digest=e2.event_digest,
        event_kind="job_ready",
        actor_kind="system",
        actor_id="system_gpd",
        reason_code="unit_test",
        created_at=TS,
    )
    with pytest.raises(JobEventError):
        validate_event_chain([e1, e2, e4])
    with pytest.raises(JobEventError):
        create_job_event(
            event_id="evt_bad",
            job_id="job_gpd_evt",
            sequence=1,
            previous_event_digest=e1.event_digest,
            event_kind="job_admitted",
            actor_kind="system",
            actor_id="system_gpd",
            reason_code="unit_test",
            created_at=TS,
        )


def test_invalid_transition_fail_closed():
    e1 = _event(1, "job_created")
    e2 = _event(2, "terminal_success", e1.event_digest, payload={
        "system_proof": True,
    })
    with pytest.raises(JobStateError):
        reduce_job_state(_header(), [e1, e2])


def test_worker_success_alone_not_terminal():
    e1 = _event(1, "job_created")
    e2 = _event(2, "job_admitted", e1.event_digest)
    e3 = _event(3, "job_ready", e2.event_digest)
    e4 = _event(4, "lease_acquired", e3.event_digest, attempt_id="att_001")
    e5 = _event(5, "running_marked", e4.event_digest, attempt_id="att_001")
    e6 = _event(
        6, "terminal_success", e5.event_digest,
        attempt_id="att_001", actor_kind="worker_claim",
        actor_id="worker_x", worker_claim=True, payload={},
    )
    with pytest.raises(JobStateError):
        reduce_job_state(_header(), [e1, e2, e3, e4, e5, e6])


def test_terminal_cannot_reopen():
    e1 = _event(1, "job_created")
    e2 = _event(2, "cancelled", e1.event_digest)
    e3 = _event(3, "job_ready", e2.event_digest)
    with pytest.raises(JobStateError):
        reduce_job_state(_header(), [e1, e2, e3])
