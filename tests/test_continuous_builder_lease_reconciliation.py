"""Tests for H2: expired unreleased lease reconciliation.

Expiry alone must never imply the worker stopped, there must be no
silent takeover, and no redispatch may occur until an explicit, audited
reconciliation succeeds.
"""

import pytest

from backend.continuous_builder.leases import (
    LeaseError,
    acquire_lease,
    create_attempt,
    inspect_lease,
    reconcile_expired_lease,
)
from test_continuous_builder_queue_store import prepared

T0 = "2026-01-01T00:00:00+00:00"
T1 = "2026-01-01T00:01:00+00:00"
T2 = "2026-01-01T00:02:00+00:00"
T3 = "2026-01-01T00:03:00+00:00"


def _leased(tmp_path):
    path, _ = prepared(tmp_path)
    create_attempt(
        path, "attempt-1", "continuous-builder", "phase-1", "CB-001", "1",
        "owner-1", T0,
    )
    acquire_lease(path, "lease-1", "attempt-1", "CB-001", "owner-1", T0, T1)
    return path


def test_expired_lease_cannot_be_reconciled_before_it_expires(tmp_path):
    path = _leased(tmp_path)
    with pytest.raises(LeaseError, match="has not expired"):
        reconcile_expired_lease(
            path, "r1", "lease-1", "operator", "worker_confirmed_stopped",
            "checked process table", T0,
        )


def test_worker_confirmed_stopped_releases_the_lease(tmp_path):
    path = _leased(tmp_path)
    record = reconcile_expired_lease(
        path, "r1", "lease-1", "operator", "worker_confirmed_stopped",
        "process no longer running on host", T2,
    )
    assert record.verdict == "worker_confirmed_stopped"
    status = inspect_lease(path, "lease-1", T2)
    assert status.status == "released"
    assert status.reconciliation_verdict == "worker_confirmed_stopped"
    create_attempt(
        path, "attempt-2", "continuous-builder", "phase-1", "CB-001", "1",
        "owner-2", T2,
    )
    acquire_lease(path, "lease-2", "attempt-2", "CB-001", "owner-2", T2, T3)


def test_worker_confirmed_running_blocks_redispatch_as_needs_human(tmp_path):
    path = _leased(tmp_path)
    reconcile_expired_lease(
        path, "r1", "lease-1", "operator", "worker_confirmed_running",
        "process still owns the working tree", T2,
    )
    status = inspect_lease(path, "lease-1", T2)
    assert status.status == "needs_human"
    assert status.reconciliation_verdict == "worker_confirmed_running"
    create_attempt(
        path, "attempt-2", "continuous-builder", "phase-1", "CB-001", "1",
        "owner-2", T2,
    )
    with pytest.raises(LeaseError, match="duplicate active lease"):
        acquire_lease(path, "lease-2", "attempt-2", "CB-001", "owner-2", T2, T3)


def test_unreconciled_expiry_never_claims_worker_stopped_or_takeover(tmp_path):
    path = _leased(tmp_path)
    status = inspect_lease(path, "lease-1", T2)
    assert status.status == "expired_uncertain"
    assert status.worker_stopped is False
    assert status.takeover_authorized is False
    assert status.reconciliation_verdict is None


def test_reconciliation_requires_a_supported_verdict(tmp_path):
    path = _leased(tmp_path)
    with pytest.raises(LeaseError, match="verdict is unsupported"):
        reconcile_expired_lease(
            path, "r1", "lease-1", "operator", "worker_probably_fine",
            "vibes", T2,
        )


def test_cannot_reconcile_an_already_released_lease(tmp_path):
    path = _leased(tmp_path)
    reconcile_expired_lease(
        path, "r1", "lease-1", "operator", "worker_confirmed_stopped",
        "confirmed dead", T2,
    )
    with pytest.raises(LeaseError, match="already released"):
        reconcile_expired_lease(
            path, "r2", "lease-1", "operator", "worker_confirmed_stopped",
            "confirmed dead again", T3,
        )


def test_reconciliation_is_durable_and_audited(tmp_path):
    path = _leased(tmp_path)
    reconcile_expired_lease(
        path, "r1", "lease-1", "operator-a", "worker_confirmed_running",
        "still writing files", T2,
    )
    import sqlite3
    connection = sqlite3.connect(path)
    row = connection.execute(
        "SELECT lease_id, attempt_id, verdict, evidence, actor_id "
        "FROM builder_lease_reconciliations WHERE reconciliation_id='r1'"
    ).fetchone()
    connection.close()
    assert row == (
        "lease-1", "attempt-1", "worker_confirmed_running",
        "still writing files", "operator-a",
    )
