"""Tests for deterministic queue replay and corruption detection."""

import sqlite3
from dataclasses import replace

import pytest

from backend.continuous_builder.queue_projection import (
    MAX_REPLAY_EVENTS,
    QueueIntegrityError,
    replay_slice,
)
from backend.continuous_builder.queue_store import append_event
from test_continuous_builder_queue_store import prepared


def test_replay_reconstructs_current_state_after_restart(tmp_path):
    path, event = prepared(tmp_path)
    _, digest = append_event(path, event, 0, None)
    append_event(
        path, replace(event, event_id="event-2", next_state="researching"),
        1, digest,
    )
    first = replay_slice(path, event.blueprint_id, event.blueprint_version,
                         event.slice_id)
    second = replay_slice(path, event.blueprint_id, event.blueprint_version,
                          event.slice_id)
    assert first == second
    assert first.current_state == "researching"
    assert first.cache_authoritative is False


@pytest.mark.parametrize("column,value", [
    ("reason", "tampered"), ("previous_digest", "0" * 64),
    ("sequence", 9),
])
def test_replay_detects_tampering(column, value, tmp_path):
    path, event = prepared(tmp_path)
    append_event(path, event, 0, None)
    connection = sqlite3.connect(path)
    connection.execute(
        f"UPDATE builder_events SET {column}=? WHERE event_id=?",
        (value, event.event_id),
    )
    connection.commit()
    connection.close()
    with pytest.raises(QueueIntegrityError, match="corrupt"):
        replay_slice(path, event.blueprint_id, event.blueprint_version,
                     event.slice_id)


def test_replay_bounds_event_history_length(tmp_path):
    path, event = prepared(tmp_path)
    append_event(path, event, 0, None)
    connection = sqlite3.connect(path)
    connection.executemany(
        "INSERT INTO builder_events VALUES "
        "(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            (
                f"padding-{index}", event.blueprint_id,
                event.blueprint_version, event.blueprint_digest,
                event.slice_id, event.slice_version, index + 1, None,
                None, "idea", "padding", "actor", 0, None,
                event.dependency_digest, "adr-043-v1",
                "2026-01-01T00:00:00+00:00", f"padding-digest-{index}",
            )
            for index in range(1, MAX_REPLAY_EVENTS + 1)
        ),
    )
    connection.commit()
    connection.close()
    with pytest.raises(QueueIntegrityError, match="replay bound"):
        replay_slice(path, event.blueprint_id, event.blueprint_version,
                     event.slice_id)
