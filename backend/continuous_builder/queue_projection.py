"""Authoritative replay-derived Continuous Builder queue state."""

import hashlib
import json
from dataclasses import dataclass

from backend.db import connect
from .queue_store import TRANSITIONS


class QueueIntegrityError(RuntimeError):
    """Raised when a durable event chain is corrupt or incomplete."""


@dataclass(frozen=True)
class QueueProjection:
    blueprint_id: str
    blueprint_version: str
    slice_id: str
    current_state: str
    sequence: int
    event_digest: str
    integrity_valid: bool = True
    cache_authoritative: bool = False


def replay_slice(database_path, blueprint_id, blueprint_version, slice_id):
    connection = connect(database_path)
    try:
        rows = connection.execute(
            "SELECT * FROM builder_events WHERE blueprint_id=? "
            "AND blueprint_version=? AND slice_id=? ORDER BY sequence",
            (blueprint_id, blueprint_version, slice_id),
        ).fetchall()
    finally:
        connection.close()
    if not rows:
        raise QueueIntegrityError("event history is empty")
    previous_digest = None
    previous_state = None
    for expected_sequence, row in enumerate(rows, 1):
        if row["sequence"] != expected_sequence:
            raise QueueIntegrityError("event sequence is corrupt")
        if row["previous_digest"] != previous_digest or (
            row["previous_state"] != previous_state
        ):
            raise QueueIntegrityError("event chain binding is corrupt")
        if row["next_state"] not in TRANSITIONS.get(previous_state, ()):
            raise QueueIntegrityError("event transition is corrupt")
        values = {
            key: row[key] for key in (
                "event_id", "blueprint_id", "blueprint_version",
                "blueprint_digest", "slice_id", "slice_version",
                "next_state", "reason", "actor_id", "dependency_digest",
                "policy_version", "created_at", "attempt_id",
            )
        }
        values["actor_authenticated"] = bool(row["actor_authenticated"])
        values["sequence"] = row["sequence"]
        values["previous_digest"] = row["previous_digest"]
        values["previous_state"] = row["previous_state"]
        encoded = json.dumps(values, sort_keys=True, separators=(",", ":"))
        digest = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
        if digest != row["event_digest"]:
            raise QueueIntegrityError("event digest is corrupt")
        previous_digest = digest
        previous_state = row["next_state"]
    return QueueProjection(
        blueprint_id, blueprint_version, slice_id, previous_state,
        len(rows), previous_digest,
    )
