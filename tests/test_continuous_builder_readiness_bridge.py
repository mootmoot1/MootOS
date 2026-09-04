"""Tests for the pure, read-only authoritative durable-readiness bridge.

The bridge (backend/continuous_builder/readiness_bridge.py) exists so
that Phase 3 never has to trust a caller's bare
``DependencyReceipt(authoritative=True)`` claim -- these tests prove it
actually derives authority from durable, replayed event history and the
immutable stored blueprint snapshot, and fails closed on staleness,
version drift, and tampering.
"""

import sqlite3

from backend.continuous_builder.blueprint_parser import parse_blueprint
from backend.continuous_builder.blueprint_store import store_blueprint
from backend.continuous_builder.chief_builder import BlueprintApprovalEvidence
from backend.continuous_builder.queue_store import (
    PRIMARY,
    QueueEventInput,
    append_event,
    dependency_snapshot_digest,
)
from backend.continuous_builder.readiness_bridge import (
    derive_dependency_receipt,
    derive_dependency_receipts,
)
from backend.migrations import run_migrations
from test_continuous_builder_blueprint import make_blueprint, make_slice

T0 = "2026-01-01T00:00:00+00:00"


def _two_slice_blueprint():
    upstream = make_slice(slice_id="CB-001", version="1")
    downstream = make_slice(
        slice_id="CB-002", version="1", hard_dependencies=("CB-001",),
    )
    return make_blueprint(slices=(upstream, downstream))


def _prepared(tmp_path):
    path = tmp_path / "mootos.db"
    run_migrations(path)
    parsed = parse_blueprint(_two_slice_blueprint().canonical_bytes())
    approval = BlueprintApprovalEvidence(
        "a", parsed.content_sha256, "human", True,
    )
    store_blueprint(path, parsed, approval, T0)
    return path, parsed.blueprint.blueprint_id, parsed.blueprint.blueprint_version


def _advance_to_done(path, blueprint_id, blueprint_version, slice_id, slice_version):
    sequence, digest = 0, None
    for index, state in enumerate(PRIMARY):
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
        event = QueueEventInput(
            f"event-{slice_id}-{index}", blueprint_id, blueprint_version,
            blueprint_digest, slice_id, slice_version, state, "advance",
            "human", False, dependency_digest, "adr-043-v1", T0,
        )
        sequence, digest = append_event(path, event, sequence, digest)


def test_bridge_proves_completion_from_durable_replay_not_a_claim(tmp_path):
    path, blueprint_id, blueprint_version = _prepared(tmp_path)
    _advance_to_done(path, blueprint_id, blueprint_version, "CB-001", "1")
    receipt = derive_dependency_receipt(
        path, blueprint_id, blueprint_version, "CB-001", "1",
    )
    assert receipt.authoritative is True
    assert receipt.passed is True
    assert receipt.slice_id == "CB-001"


def test_bridge_fails_closed_when_dependency_never_reached_done(tmp_path):
    path, blueprint_id, blueprint_version = _prepared(tmp_path)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    dependency_digest = dependency_snapshot_digest(
        connection, blueprint_id, blueprint_version, "CB-001",
    )
    blueprint_digest = connection.execute(
        "SELECT content_digest FROM builder_blueprints WHERE "
        "blueprint_id=? AND blueprint_version=?",
        (blueprint_id, blueprint_version),
    ).fetchone()["content_digest"]
    connection.close()
    event = QueueEventInput(
        "event-1", blueprint_id, blueprint_version, blueprint_digest,
        "CB-001", "1", "idea", "advance", "human", False,
        dependency_digest, "adr-043-v1", T0,
    )
    append_event(path, event, 0, None)
    receipt = derive_dependency_receipt(
        path, blueprint_id, blueprint_version, "CB-001", "1",
    )
    assert receipt.authoritative is True
    assert receipt.passed is False


def test_bridge_fails_closed_on_stale_version_claim(tmp_path):
    path, blueprint_id, blueprint_version = _prepared(tmp_path)
    _advance_to_done(path, blueprint_id, blueprint_version, "CB-001", "1")
    receipt = derive_dependency_receipt(
        path, blueprint_id, blueprint_version, "CB-001", "2",
    )
    assert receipt.authoritative is False
    assert receipt.passed is False


def test_bridge_fails_closed_when_slice_has_no_durable_snapshot(tmp_path):
    path, blueprint_id, blueprint_version = _prepared(tmp_path)
    receipt = derive_dependency_receipt(
        path, blueprint_id, blueprint_version, "CB-999", "1",
    )
    assert receipt.authoritative is False
    assert receipt.passed is False


def test_bridge_fails_closed_when_event_chain_is_tampered(tmp_path):
    path, blueprint_id, blueprint_version = _prepared(tmp_path)
    _advance_to_done(path, blueprint_id, blueprint_version, "CB-001", "1")
    connection = sqlite3.connect(path)
    connection.execute(
        "UPDATE builder_events SET reason='forged' WHERE slice_id='CB-001'"
    )
    connection.commit()
    connection.close()
    receipt = derive_dependency_receipt(
        path, blueprint_id, blueprint_version, "CB-001", "1",
    )
    assert receipt.authoritative is False


def test_two_receipts_for_identical_evidence_are_identical(tmp_path):
    path, blueprint_id, blueprint_version = _prepared(tmp_path)
    _advance_to_done(path, blueprint_id, blueprint_version, "CB-001", "1")
    first = derive_dependency_receipt(
        path, blueprint_id, blueprint_version, "CB-001", "1",
    )
    second = derive_dependency_receipt(
        path, blueprint_id, blueprint_version, "CB-001", "1",
    )
    assert first.receipt_id == second.receipt_id


def test_derive_dependency_receipts_covers_declared_hard_dependency(tmp_path):
    path, blueprint_id, blueprint_version = _prepared(tmp_path)
    _advance_to_done(path, blueprint_id, blueprint_version, "CB-001", "1")
    receipts = derive_dependency_receipts(
        path, blueprint_id, blueprint_version, "CB-002",
    )
    assert len(receipts) == 1
    assert receipts[0].slice_id == "CB-001"
    assert receipts[0].authoritative is True
    assert receipts[0].passed is True


def test_derive_dependency_receipts_empty_for_unknown_slice(tmp_path):
    path, blueprint_id, blueprint_version = _prepared(tmp_path)
    receipts = derive_dependency_receipts(
        path, blueprint_id, blueprint_version, "CB-999",
    )
    assert receipts == ()
