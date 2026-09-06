"""Focused tests for GP-D4/D5/D6 attempt, heartbeat/lease, checkpoint."""

import pytest

from backend.continuous_builder.gpd_attempt_ledger import (
    AttemptLedgerError,
    assert_new_attempt_identity,
    create_attempt_record,
)
from backend.continuous_builder.gpd_checkpoint import (
    CheckpointError,
    create_checkpoint_contract,
    detect_checkpoint_tamper,
)
from backend.continuous_builder.gpd_heartbeat_lease import (
    HeartbeatLeaseError,
    assert_single_active_lease,
    create_heartbeat_evidence,
    create_lease_record,
    create_stall_evidence,
    heartbeat_without_progress_is_stall_evidence,
)

DIGEST = "b" * 64
TS = "2026-09-06T22:00:00+00:00"
TS2 = "2026-09-06T22:05:00+00:00"
TS3 = "2026-09-06T22:10:00+00:00"


def test_retry_creates_new_attempt_never_overwrite():
    a1 = create_attempt_record(
        attempt_id="att_001",
        job_id="job_gpd_att",
        attempt_number=1,
        owner_id="owner_a",
        started_at=TS,
        status="started",
        header_sha256=DIGEST,
    )
    a2 = create_attempt_record(
        attempt_id="att_002",
        job_id="job_gpd_att",
        attempt_number=2,
        owner_id="owner_a",
        started_at=TS2,
        status="started",
        prior_attempt_id="att_001",
        header_sha256=DIGEST,
    )
    assert_new_attempt_identity([a1], a2)
    with pytest.raises(AttemptLedgerError):
        assert_new_attempt_identity([a1], a1)


def test_lease_expiry_does_not_prove_side_effect_absence():
    lease = create_lease_record(
        lease_id="lease_001",
        job_id="job_gpd_att",
        attempt_id="att_001",
        owner_id="owner_a",
        acquired_at=TS,
        expires_at=TS2,
    )
    assert lease.is_expired(TS3) is True
    with pytest.raises(HeartbeatLeaseError):
        create_stall_evidence(
            stall_id="stall_001",
            job_id="job_gpd_att",
            attempt_id="att_001",
            lease_id="lease_001",
            reason_code="lease_expired",
            heartbeat_without_progress_count=0,
            lease_expired=True,
            observed_at=TS3,
            side_effect_absence_proven=True,
        )


def test_heartbeat_without_progress_is_stall_evidence():
    hbs = [
        create_heartbeat_evidence(
            heartbeat_id=f"hb_{i}",
            job_id="job_gpd_att",
            attempt_id="att_001",
            lease_id="lease_001",
            observed_at=TS,
            progress_advanced=False,
        )
        for i in range(1, 4)
    ]
    assert heartbeat_without_progress_is_stall_evidence(hbs, threshold=3)


def test_single_active_lease():
    l1 = create_lease_record(
        lease_id="lease_001",
        job_id="job_gpd_att",
        attempt_id="att_001",
        owner_id="owner_a",
        acquired_at=TS,
        expires_at=TS2,
    )
    l2 = create_lease_record(
        lease_id="lease_002",
        job_id="job_gpd_att",
        attempt_id="att_002",
        owner_id="owner_b",
        acquired_at=TS,
        expires_at=TS2,
    )
    with pytest.raises(HeartbeatLeaseError):
        assert_single_active_lease([l1, l2], "job_gpd_att")


def test_checkpoint_tamper_detected():
    cp = create_checkpoint_contract(
        checkpoint_id="cp_001",
        job_id="job_gpd_att",
        attempt_id="att_001",
        sequence_at_checkpoint=5,
        progress_cursor="node:step_2",
        evidence_digests=(DIGEST,),
        notes=("bounded",),
        created_at=TS,
        header_sha256=DIGEST,
        system_accepted=True,
    )
    detect_checkpoint_tamper(cp, cp.checkpoint_sha256)
    with pytest.raises(CheckpointError):
        detect_checkpoint_tamper(cp, "c" * 64)


def test_worker_checkpoint_cannot_self_accept():
    with pytest.raises(CheckpointError):
        create_checkpoint_contract(
            checkpoint_id="cp_002",
            job_id="job_gpd_att",
            attempt_id="att_001",
            sequence_at_checkpoint=5,
            progress_cursor="node:step_2",
            evidence_digests=(DIGEST,),
            notes=(),
            created_at=TS,
            header_sha256=DIGEST,
            worker_claim=True,
            system_accepted=True,
        )
