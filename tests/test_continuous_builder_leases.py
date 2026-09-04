"""Tests for durable attempts, leases, and idempotency."""

from dataclasses import replace

import pytest

from backend.continuous_builder.leases import (
    LeaseError,
    acquire_lease,
    create_attempt,
    inspect_lease,
    release_lease,
    reserve_idempotency,
)
from backend.continuous_builder.queue_store import QueueStoreError, append_event
from test_continuous_builder_queue_store import prepared


T0 = "2026-01-01T00:00:00+00:00"
T1 = "2026-01-01T00:01:00+00:00"
T2 = "2026-01-01T00:02:00+00:00"


def create(path, attempt="attempt-1", owner="owner-1"):
    create_attempt(
        path, attempt, "continuous-builder", "phase-1",
        "CB-001", "1", owner, T0,
    )


def test_attempt_and_active_lease_ownership_are_durably_unique(tmp_path):
    path, _ = prepared(tmp_path)
    create(path)
    acquire_lease(path, "lease-1", "attempt-1", "CB-001", "owner-1", T0, T1)
    with pytest.raises(LeaseError, match="duplicate attempt"):
        create(path)
    create(path, "attempt-2", "owner-2")
    with pytest.raises(LeaseError, match="duplicate active lease"):
        acquire_lease(
            path, "lease-2", "attempt-2", "CB-001", "owner-2", T0, T1,
        )


def test_expiry_is_uncertain_and_never_claims_worker_stopped(tmp_path):
    path, _ = prepared(tmp_path)
    create(path)
    acquire_lease(path, "lease-1", "attempt-1", "CB-001", "owner-1", T0, T1)
    status = inspect_lease(path, "lease-1", T2)
    assert status.status == "expired_uncertain"
    assert status.expired is True
    assert status.worker_stopped is False
    assert status.takeover_authorized is False
    create(path, "attempt-2", "owner-2")
    with pytest.raises(LeaseError, match="duplicate active lease"):
        acquire_lease(
            path, "lease-2", "attempt-2", "CB-001", "owner-2", T1, T2,
        )


def test_explicit_release_allows_new_coordination_record(tmp_path):
    path, _ = prepared(tmp_path)
    create(path)
    acquire_lease(path, "lease-1", "attempt-1", "CB-001", "owner-1", T0, T1)
    release_lease(path, "lease-1", "owner-1", T1)
    assert inspect_lease(path, "lease-1", T2).status == "released"
    create(path, "attempt-2", "owner-2")
    acquire_lease(path, "lease-2", "attempt-2", "CB-001", "owner-2", T1, T2)


def test_idempotency_is_backed_by_database_uniqueness(tmp_path):
    path, _ = prepared(tmp_path)
    reserve_idempotency(path, "key-1", "plan", "a" * 64, T0)
    with pytest.raises(LeaseError, match="duplicate durable"):
        reserve_idempotency(path, "key-1", "plan", "a" * 64, T0)


def test_ownership_and_timestamp_mismatches_fail_closed(tmp_path):
    path, _ = prepared(tmp_path)
    create(path)
    with pytest.raises(LeaseError, match="ownership"):
        acquire_lease(path, "lease-1", "attempt-1", "CB-001", "other", T0, T1)
    with pytest.raises(LeaseError, match="follow"):
        acquire_lease(
            path, "lease-1", "attempt-1", "CB-001", "owner-1", T1, T0,
        )


def test_active_lease_rejects_transition_from_another_attempt(tmp_path):
    path, event = prepared(tmp_path)
    _, digest = append_event(path, event, 0, None)
    create(path)
    acquire_lease(
        path, "lease-1", "attempt-1", "CB-001", "owner-1", T0, T1,
    )
    other = replace(
        event, event_id="event-2", next_state="researching",
        attempt_id="other-attempt",
    )
    with pytest.raises(QueueStoreError, match="active lease"):
        append_event(path, other, 1, digest)
