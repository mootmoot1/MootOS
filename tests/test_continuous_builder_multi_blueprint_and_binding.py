"""M1: multi-blueprint lease behavior, and H3: adversarial attempt binding.

M1 -- two different blueprint *versions* that happen to share a
slice_id must not block each other's leases; only genuinely the same
(blueprint_id, blueprint_version, slice_id, slice_version) may hold one
active lease at a time.

H3 -- knowing an attempt_id string must never be treated as proof of
authorship. An event must be rejected if its attempt_id names a real
attempt bound to a *different* blueprint/version/slice, or no attempt at
all.
"""

import sqlite3

import pytest

from backend.continuous_builder.blueprint_parser import parse_blueprint
from backend.continuous_builder.blueprint_store import store_blueprint
from backend.continuous_builder.chief_builder import BlueprintApprovalEvidence
from backend.continuous_builder.leases import acquire_lease, create_attempt
from backend.continuous_builder.queue_store import (
    QueueEventInput,
    QueueStoreError,
    append_event,
    dependency_snapshot_digest,
)
from backend.migrations import run_migrations
from test_continuous_builder_blueprint import make_blueprint, make_slice

T0 = "2026-01-01T00:00:00+00:00"
T1 = "2026-01-01T00:01:00+00:00"


def _store(path, blueprint_version):
    parsed = parse_blueprint(
        make_blueprint(
            blueprint_version=blueprint_version, slices=(make_slice(),),
        ).canonical_bytes()
    )
    approval = BlueprintApprovalEvidence(
        f"approval-{blueprint_version}", parsed.content_sha256, "human", True,
    )
    store_blueprint(path, parsed, approval, T0)
    return parsed.blueprint.blueprint_id, parsed.blueprint.blueprint_version


def test_active_leases_on_different_blueprint_versions_do_not_conflict(tmp_path):
    path = tmp_path / "mootos.db"
    run_migrations(path)
    blueprint_id, v1 = _store(path, "v1")
    _, v2 = _store(path, "v2")

    create_attempt(
        path, "attempt-v1", blueprint_id, v1, "CB-001", "1", "owner-1", T0,
    )
    create_attempt(
        path, "attempt-v2", blueprint_id, v2, "CB-001", "1", "owner-2", T0,
    )
    acquire_lease(path, "lease-v1", "attempt-v1", "CB-001", "owner-1", T0, T1)
    # Same slice_id, different blueprint_version -- must succeed, not
    # collide with the v1 active lease.
    acquire_lease(path, "lease-v2", "attempt-v2", "CB-001", "owner-2", T0, T1)

    connection = sqlite3.connect(path)
    active = connection.execute(
        "SELECT lease_id, blueprint_version FROM builder_leases "
        "WHERE released_at IS NULL ORDER BY blueprint_version"
    ).fetchall()
    connection.close()
    assert active == [("lease-v1", "v1"), ("lease-v2", "v2")]


def test_second_lease_on_same_blueprint_version_still_conflicts(tmp_path):
    path = tmp_path / "mootos.db"
    run_migrations(path)
    blueprint_id, v1 = _store(path, "v1")
    create_attempt(
        path, "attempt-a", blueprint_id, v1, "CB-001", "1", "owner-a", T0,
    )
    create_attempt(
        path, "attempt-b", blueprint_id, v1, "CB-001", "1", "owner-b", T0,
    )
    acquire_lease(path, "lease-a", "attempt-a", "CB-001", "owner-a", T0, T1)
    from backend.continuous_builder.leases import LeaseError
    with pytest.raises(LeaseError, match="duplicate active lease"):
        acquire_lease(path, "lease-b", "attempt-b", "CB-001", "owner-b", T0, T1)


def _event(path, blueprint_id, blueprint_version, slice_id, slice_version, state, event_id, attempt_id):
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    dependency_digest = dependency_snapshot_digest(
        connection, blueprint_id, blueprint_version, slice_id,
    )
    blueprint_digest = connection.execute(
        "SELECT content_digest FROM builder_blueprints WHERE "
        "blueprint_id=? AND blueprint_version=?",
        (blueprint_id, blueprint_version),
    ).fetchone()["content_digest"]
    connection.close()
    return QueueEventInput(
        event_id, blueprint_id, blueprint_version, blueprint_digest,
        slice_id, slice_version, state, "advance", "human", False,
        dependency_digest, "adr-043-v1", T0, attempt_id=attempt_id,
    )


def test_event_rejects_an_attempt_id_that_does_not_exist(tmp_path):
    path = tmp_path / "mootos.db"
    run_migrations(path)
    blueprint_id, v1 = _store(path, "v1")
    with pytest.raises(QueueStoreError, match="event attempt binding mismatch"):
        append_event(
            path,
            _event(path, blueprint_id, v1, "CB-001", "1", "idea", "e1", "never-created"),
            0, None,
        )


def test_event_rejects_an_attempt_id_bound_to_a_different_slice(tmp_path):
    path = tmp_path / "mootos.db"
    run_migrations(path)
    blueprint_id, v1 = _store(path, "v1")
    parsed = parse_blueprint(
        make_blueprint(
            blueprint_version=v1,
            slices=(make_slice(slice_id="CB-001"), make_slice(slice_id="CB-002")),
        ).canonical_bytes()
    )
    # Overwrite v1's stored snapshot with a two-slice blueprint so
    # CB-002 exists to bind a foreign attempt against.
    connection = sqlite3.connect(path)
    connection.execute("DELETE FROM builder_blueprints WHERE blueprint_id=? AND blueprint_version=?", (blueprint_id, v1))
    connection.execute("DELETE FROM builder_slices WHERE blueprint_id=? AND blueprint_version=?", (blueprint_id, v1))
    connection.commit()
    connection.close()
    approval = BlueprintApprovalEvidence(
        "approval-two-slice", parsed.content_sha256, "human", True,
    )
    store_blueprint(path, parsed, approval, T0)

    create_attempt(
        path, "attempt-cb002", blueprint_id, v1, "CB-002", "1", "owner-1", T0,
    )
    with pytest.raises(QueueStoreError, match="event attempt binding mismatch"):
        append_event(
            path,
            _event(path, blueprint_id, v1, "CB-001", "1", "idea", "e1", "attempt-cb002"),
            0, None,
        )


def test_event_rejects_an_attempt_id_bound_to_a_different_blueprint_version(tmp_path):
    path = tmp_path / "mootos.db"
    run_migrations(path)
    blueprint_id, v1 = _store(path, "v1")
    _, v2 = _store(path, "v2")
    create_attempt(
        path, "attempt-v2", blueprint_id, v2, "CB-001", "1", "owner-1", T0,
    )
    with pytest.raises(QueueStoreError, match="event attempt binding mismatch"):
        append_event(
            path,
            _event(path, blueprint_id, v1, "CB-001", "1", "idea", "e1", "attempt-v2"),
            0, None,
        )
