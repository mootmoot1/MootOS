"""Adversarial lifecycle routing tests for H1: hard-dependency gate bypass.

Before Phase 2.5, the hard-dependency completeness check in
``append_event`` only fired when ``next_state == "ready"`` literally.
Side-state routes (``paused``, ``changes_requested``) that reach
execution-capable states without ever passing back through ``ready``
bypassed it entirely. These tests reproduce the exact adversarial routes
named in the audit and prove they now fail closed.
"""

import sqlite3

import pytest

from backend.continuous_builder.blueprint_parser import parse_blueprint
from backend.continuous_builder.blueprint_store import store_blueprint
from backend.continuous_builder.chief_builder import BlueprintApprovalEvidence
from backend.continuous_builder.queue_store import (
    QueueEventInput,
    QueueStoreError,
    append_event,
    dependency_snapshot_digest,
)
from backend.migrations import run_migrations
from test_continuous_builder_blueprint import make_blueprint, make_slice

T0 = "2026-01-01T00:00:00+00:00"


def _prepared_with_unmet_dependency(tmp_path):
    upstream = make_slice(slice_id="CB-001", version="1")
    downstream = make_slice(
        slice_id="CB-002", version="1", hard_dependencies=("CB-001",),
    )
    path = tmp_path / "mootos.db"
    run_migrations(path)
    parsed = parse_blueprint(
        make_blueprint(slices=(upstream, downstream)).canonical_bytes()
    )
    approval = BlueprintApprovalEvidence(
        "a", parsed.content_sha256, "human", True,
    )
    store_blueprint(path, parsed, approval, T0)
    return path, parsed.blueprint.blueprint_id, parsed.blueprint.blueprint_version


def _event(path, blueprint_id, blueprint_version, slice_id, slice_version, state, event_id):
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
        dependency_digest, "adr-043-v1", T0,
    )


def test_paused_to_scheduled_bypass_is_rejected_with_unmet_dependency(tmp_path):
    path, blueprint_id, blueprint_version = _prepared_with_unmet_dependency(tmp_path)
    sequence, digest = append_event(
        path, _event(path, blueprint_id, blueprint_version, "CB-002", "1", "idea", "e1"),
        0, None,
    )
    sequence, digest = append_event(
        path, _event(path, blueprint_id, blueprint_version, "CB-002", "1", "paused", "e2"),
        sequence, digest,
    )
    with pytest.raises(QueueStoreError, match="execution-capable dependencies"):
        append_event(
            path,
            _event(path, blueprint_id, blueprint_version, "CB-002", "1", "scheduled", "e3"),
            sequence, digest,
        )


def test_paused_to_scheduled_succeeds_once_dependency_is_done(tmp_path):
    path, blueprint_id, blueprint_version = _prepared_with_unmet_dependency(tmp_path)
    from test_continuous_builder_readiness_bridge import _advance_to_done
    _advance_to_done(path, blueprint_id, blueprint_version, "CB-001", "1")

    sequence, digest = append_event(
        path, _event(path, blueprint_id, blueprint_version, "CB-002", "1", "idea", "e1"),
        0, None,
    )
    sequence, digest = append_event(
        path, _event(path, blueprint_id, blueprint_version, "CB-002", "1", "paused", "e2"),
        sequence, digest,
    )
    sequence, digest = append_event(
        path, _event(path, blueprint_id, blueprint_version, "CB-002", "1", "scheduled", "e3"),
        sequence, digest,
    )
    assert sequence == 3


def test_changes_requested_re_entry_to_building_is_also_gated(tmp_path):
    """changes_requested -> building re-enters an execution-capable state
    without passing back through "ready" -- this must be gated the same
    as every other entry, even though this system's forward-only,
    terminal "done" state means a dependency cannot regress after the
    first successful "ready" check in practice."""
    path, blueprint_id, blueprint_version = _prepared_with_unmet_dependency(tmp_path)
    from test_continuous_builder_readiness_bridge import _advance_to_done
    _advance_to_done(path, blueprint_id, blueprint_version, "CB-001", "1")

    sequence, digest = 0, None
    for index, state in enumerate(
        ("idea", "researching", "designing", "ready", "scheduled", "building",
         "reviewing", "changes_requested"),
    ):
        sequence, digest = append_event(
            path,
            _event(path, blueprint_id, blueprint_version, "CB-002", "1", state, f"e{index}"),
            sequence, digest,
        )
    # Re-entering "building" from "changes_requested" must still pass the
    # execution-capable gate (trivially true here since the dependency is
    # done) -- it is not exempt just because "ready" was already visited.
    sequence, digest = append_event(
        path,
        _event(path, blueprint_id, blueprint_version, "CB-002", "1", "building", "e-reentry"),
        sequence, digest,
    )
    assert sequence == 9


def test_execution_capable_states_all_require_dependency_completeness(tmp_path):
    path, blueprint_id, blueprint_version = _prepared_with_unmet_dependency(tmp_path)
    for state in ("ready", "scheduled", "building", "reviewing", "staging",
                  "testing", "ready_for_main", "done"):
        with pytest.raises(QueueStoreError, match="execution-capable dependencies"):
            append_event(
                path,
                _event(path, blueprint_id, blueprint_version, "CB-002", "1", state, f"probe-{state}"),
                0, None,
            )
