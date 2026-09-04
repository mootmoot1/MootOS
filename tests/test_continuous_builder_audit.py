"""Integrated tests for bounded builder audit and rollback proof."""

import shutil
import sqlite3
from dataclasses import replace

import pytest

from backend.continuous_builder.audit import (
    AuditError,
    read_slice_audit,
    record_artifact_reference,
    validate_blueprint_integrity,
)
from backend.continuous_builder.leases import acquire_lease, create_attempt
from backend.continuous_builder.queue_store import (
    QueueStoreError,
    append_event,
)
from backend.migrations import get_schema_version, run_migrations
from test_continuous_builder_queue_store import prepared


T0 = "2026-01-01T00:00:00+00:00"
T1 = "2026-01-01T00:01:00+00:00"


def test_complete_durable_chain_has_bounded_integrity_audit(tmp_path):
    path, event = prepared(tmp_path)
    _, digest = append_event(
        path, event, 0, None,
        expected_dependency_digest=event.dependency_digest,
    )
    create_attempt(
        path, "attempt-1", event.blueprint_id, event.blueprint_version,
        event.slice_id, event.slice_version, "owner", T0,
    )
    researching = replace(
        event, event_id="event-2", next_state="researching",
        attempt_id="attempt-1",
    )
    append_event(path, researching, 1, digest, event.dependency_digest)
    acquire_lease(
        path, "lease-1", "attempt-1", event.slice_id, "owner", T0, T1,
    )
    record_artifact_reference(
        path, "artifact-1", event.slice_id, "attempt-1", "patch",
        "a" * 64, 42, T1,
    )
    audit = read_slice_audit(
        path, event.blueprint_id, event.blueprint_version, event.slice_id, 10,
    )
    assert audit.current_state == "researching"
    assert audit.integrity_valid is True
    assert len(audit.events) == 2
    assert len(audit.attempts) == 1
    assert len(audit.leases) == 1
    assert len(audit.artifacts) == 1
    assert audit.externally_verified is False


def test_audit_is_bounded_and_artifacts_are_digest_only(tmp_path):
    path, _ = prepared(tmp_path)
    with pytest.raises(AuditError, match="limit"):
        read_slice_audit(path, "continuous-builder", "phase-1", "CB-001", 101)
    with pytest.raises(AuditError, match="digest"):
        record_artifact_reference(
            path, "a", "CB-001", None, "raw", "secret", 1, T0,
        )
    with pytest.raises(AuditError, match="attempt binding"):
        record_artifact_reference(
            path, "a", "CB-001", None, "patch", "a" * 64, 1, T0,
        )
    with pytest.raises(AuditError, match="attempt binding mismatch"):
        record_artifact_reference(
            path, "a", "CB-001", "missing", "patch", "a" * 64, 1, T0,
        )


def test_dependency_snapshot_drift_fails_before_transaction(tmp_path):
    path, event = prepared(tmp_path)
    with pytest.raises(QueueStoreError, match="dependency snapshot"):
        append_event(path, event, 0, None, "0" * 64)
    connection = sqlite3.connect(path)
    count = connection.execute(
        "SELECT count(*) FROM builder_events"
    ).fetchone()[0]
    assert count == 0
    connection.close()


def test_integrity_query_reports_tampering_without_repair(tmp_path):
    path, event = prepared(tmp_path)
    append_event(path, event, 0, None)
    connection = sqlite3.connect(path)
    connection.execute("UPDATE builder_events SET reason='forged'")
    connection.commit()
    connection.close()
    assert validate_blueprint_integrity(
        path, event.blueprint_id, event.blueprint_version
    ) == ((event.slice_id, False),)


def test_pre_migration_backup_is_restorable_on_disposable_database(tmp_path):
    original = tmp_path / "upgrade-target.db"
    backup = tmp_path / "backup.db"
    run_migrations(original)
    connection = sqlite3.connect(original)
    for table in (
        "builder_lease_reconciliations", "builder_artifacts",
        "builder_leases", "builder_attempts", "builder_idempotency",
        "builder_events", "builder_slices", "builder_blueprints",
    ):
        connection.execute(f"DROP TABLE {table}")
    connection.execute("DELETE FROM schema_migrations WHERE version IN (6, 7)")
    connection.commit()
    connection.close()
    shutil.copy2(original, backup)
    assert get_schema_version(backup) == 5
    assert run_migrations(original) == 7
    assert get_schema_version(backup) == 5
