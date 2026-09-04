"""Tests for guarded append-only builder events."""

from dataclasses import replace

import pytest

from backend.continuous_builder.blueprint_store import store_blueprint
from backend.continuous_builder.chief_builder import BlueprintApprovalEvidence
from backend.continuous_builder.queue_store import (
    QueueEventInput,
    QueueStoreError,
    append_event,
    dependency_snapshot_digest,
)
from backend.continuous_builder.blueprint_parser import parse_blueprint
from backend.migrations import run_migrations
from test_continuous_builder_blueprint import make_blueprint


def prepared(tmp_path):
    path = tmp_path / "mootos.db"
    run_migrations(path)
    parsed = parse_blueprint(make_blueprint().canonical_bytes())
    approval = BlueprintApprovalEvidence(
        "a", parsed.content_sha256, "human", True
    )
    store_blueprint(path, parsed, approval, "2026-01-01T00:00:00+00:00")
    import sqlite3
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    dependency_digest = dependency_snapshot_digest(
        connection, parsed.blueprint.blueprint_id,
        parsed.blueprint.blueprint_version, "CB-001",
    )
    connection.close()
    event = QueueEventInput(
        "event-1", parsed.blueprint.blueprint_id,
        parsed.blueprint.blueprint_version, parsed.content_sha256,
        "CB-001", "1", "idea", "approved_blueprint", "human", False,
        dependency_digest, "adr-043-v1", "2026-01-01T00:00:01+00:00",
    )
    return path, event


def test_append_and_cas_are_durable_and_guarded(tmp_path):
    path, event = prepared(tmp_path)
    sequence, digest = append_event(path, event, 0, None)
    assert sequence == 1 and len(digest) == 64
    second = replace(event, event_id="event-2", next_state="researching")
    assert append_event(path, second, 1, digest)[0] == 2
    with pytest.raises(QueueStoreError, match="compare-and-swap"):
        append_event(path, replace(second, event_id="event-3"), 1, digest)


def test_duplicate_jump_and_source_drift_fail_closed(tmp_path):
    path, event = prepared(tmp_path)
    _, digest = append_event(path, event, 0, None)
    with pytest.raises(QueueStoreError, match="transition"):
        append_event(
            path, replace(event, event_id="jump", next_state="done"),
            1, digest,
        )
    with pytest.raises(QueueStoreError, match="binding"):
        append_event(
            path, replace(
                event, event_id="drift", blueprint_digest="0" * 64,
            ), 1, digest,
        )
    with pytest.raises(QueueStoreError, match="duplicate"):
        append_event(path, replace(event, next_state="researching"), 1, digest)


def test_actor_authentication_metadata_is_preserved_not_inferred(tmp_path):
    path, event = prepared(tmp_path)
    append_event(path, event, 0, None)
    import sqlite3
    connection = sqlite3.connect(path)
    value = connection.execute(
        "SELECT actor_id, actor_authenticated FROM builder_events"
    ).fetchone()
    connection.close()
    assert value == ("human", 0)
