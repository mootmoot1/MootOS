"""Transactional append-only Continuous Builder event storage."""

import hashlib
import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime

from backend.db import connect


class QueueStoreError(RuntimeError):
    """Raised when an event transition or compare-and-swap fails."""


PRIMARY = (
    "idea", "researching", "designing", "ready", "scheduled", "building",
    "reviewing", "staging", "testing", "ready_for_main", "done",
)
SIDE = (
    "blocked", "changes_requested", "paused", "superseded", "retired",
    "cancelled",
)
TRANSITIONS = {
    None: ("idea",),
    **{PRIMARY[index]: (PRIMARY[index + 1], "blocked", "paused", "cancelled")
       for index in range(len(PRIMARY) - 1)},
    "blocked": ("researching", "designing", "ready", "cancelled"),
    "changes_requested": ("building", "cancelled"),
    "paused": ("researching", "designing", "ready", "scheduled", "cancelled"),
    "reviewing": (
        "staging", "changes_requested", "blocked", "paused", "cancelled",
    ),
    "superseded": (), "retired": (), "cancelled": (), "done": (),
}
_DIGEST = re.compile(r"^[0-9a-f]{64}$")
for state in PRIMARY[:-1]:
    TRANSITIONS[state] = tuple(set(TRANSITIONS.get(state, ())) | {
        "superseded", "retired"
    })


@dataclass(frozen=True)
class QueueEventInput:
    event_id: str
    blueprint_id: str
    blueprint_version: str
    blueprint_digest: str
    slice_id: str
    slice_version: str
    next_state: str
    reason: str
    actor_id: str
    actor_authenticated: bool
    dependency_digest: str
    policy_version: str
    created_at: str
    attempt_id: str = None

    def __post_init__(self):
        values = (
            self.event_id, self.blueprint_id, self.blueprint_version,
            self.slice_id, self.slice_version, self.reason, self.actor_id,
            self.policy_version,
        )
        if any(
            not isinstance(value, str) or not value
            or len(value.encode("utf-8")) > 256 for value in values
        ):
            raise QueueStoreError("event metadata is malformed or excessive")
        if self.next_state not in set(PRIMARY) | set(SIDE):
            raise QueueStoreError("event state is unsupported")
        if _DIGEST.fullmatch(self.blueprint_digest or "") is None or (
            _DIGEST.fullmatch(self.dependency_digest or "") is None
        ):
            raise QueueStoreError("event digest metadata is malformed")
        if self.attempt_id is not None and (
            not isinstance(self.attempt_id, str) or not self.attempt_id
            or len(self.attempt_id.encode("utf-8")) > 256
        ):
            raise QueueStoreError("attempt identity is malformed")
        try:
            timestamp = datetime.fromisoformat(self.created_at)
        except (TypeError, ValueError) as error:
            raise QueueStoreError("event timestamp is malformed") from error
        if timestamp.tzinfo is None:
            raise QueueStoreError("event timestamp requires a timezone")
        if type(self.actor_authenticated) is not bool:
            raise QueueStoreError("authentication flag must be boolean")


def _digest(values):
    payload = json.dumps(values, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def dependency_snapshot_digest(
    connection, blueprint_id, blueprint_version, slice_id,
):
    row = connection.execute(
        "SELECT canonical_json FROM builder_slices WHERE blueprint_id=? "
        "AND blueprint_version=? AND slice_id=?",
        (blueprint_id, blueprint_version, slice_id),
    ).fetchone()
    if row is None:
        raise QueueStoreError("slice definition is missing")
    definition = json.loads(row["canonical_json"])
    snapshot = []
    for dependency_id in sorted(definition["hard_dependencies"]):
        dependency = connection.execute(
            "SELECT s.slice_version, e.next_state, e.event_digest "
            "FROM builder_slices s LEFT JOIN builder_events e "
            "ON e.blueprint_id=s.blueprint_id "
            "AND e.blueprint_version=s.blueprint_version "
            "AND e.slice_id=s.slice_id "
            "WHERE s.blueprint_id=? AND s.blueprint_version=? "
            "AND s.slice_id=? ORDER BY e.sequence DESC LIMIT 1",
            (blueprint_id, blueprint_version, dependency_id),
        ).fetchone()
        if dependency is None:
            raise QueueStoreError("dependency definition is missing")
        snapshot.append({
            "event_digest": dependency["event_digest"],
            "slice_id": dependency_id,
            "slice_version": dependency["slice_version"],
            "state": dependency["next_state"],
        })
    return _digest(snapshot)


def append_event(
    database_path, event, expected_sequence, expected_digest,
    expected_dependency_digest=None,
):
    if not isinstance(event, QueueEventInput):
        raise QueueStoreError("event input is invalid")
    connection = connect(database_path)
    try:
        connection.execute("BEGIN IMMEDIATE")
        source = connection.execute(
            "SELECT b.content_digest, s.slice_version "
            "FROM builder_blueprints b "
            "JOIN builder_slices s USING (blueprint_id, blueprint_version) "
            "WHERE b.blueprint_id=? AND b.blueprint_version=? "
            "AND s.slice_id=?",
            (event.blueprint_id, event.blueprint_version, event.slice_id),
        ).fetchone()
        if (
            source is None
            or source["content_digest"] != event.blueprint_digest
        ):
            raise QueueStoreError("blueprint binding mismatch")
        if source["slice_version"] != event.slice_version:
            raise QueueStoreError("slice version drift")
        durable_dependency_digest = dependency_snapshot_digest(
            connection, event.blueprint_id, event.blueprint_version,
            event.slice_id,
        )
        if event.dependency_digest != durable_dependency_digest or (
            expected_dependency_digest is not None
            and expected_dependency_digest != durable_dependency_digest
        ):
            raise QueueStoreError("dependency snapshot drift")
        if event.next_state == "ready":
            definition = json.loads(connection.execute(
                "SELECT canonical_json FROM builder_slices "
                "WHERE blueprint_id=? AND blueprint_version=? AND slice_id=?",
                (event.blueprint_id, event.blueprint_version, event.slice_id),
            ).fetchone()["canonical_json"])
            for dependency_id in definition["hard_dependencies"]:
                state = connection.execute(
                    "SELECT next_state FROM builder_events "
                    "WHERE blueprint_id=? "
                    "AND blueprint_version=? AND slice_id=? "
                    "ORDER BY sequence DESC LIMIT 1",
                    (event.blueprint_id, event.blueprint_version,
                     dependency_id),
                ).fetchone()
                if state is None or state["next_state"] != "done":
                    raise QueueStoreError(
                        "ready dependencies are not complete"
                    )
        active_lease = connection.execute(
            "SELECT l.attempt_id FROM builder_leases l "
            "JOIN builder_attempts a ON a.attempt_id=l.attempt_id "
            "WHERE a.blueprint_id=? AND a.blueprint_version=? "
            "AND a.slice_id=? AND l.released_at IS NULL",
            (event.blueprint_id, event.blueprint_version, event.slice_id),
        ).fetchone()
        if active_lease is not None and (
            event.attempt_id != active_lease["attempt_id"]
        ):
            raise QueueStoreError("active lease conflicts with transition")
        prior = connection.execute(
            "SELECT sequence, event_digest, next_state FROM builder_events "
            "WHERE blueprint_id=? AND blueprint_version=? AND slice_id=? "
            "ORDER BY sequence DESC LIMIT 1",
            (event.blueprint_id, event.blueprint_version, event.slice_id),
        ).fetchone()
        sequence = 0 if prior is None else int(prior["sequence"])
        prior_digest = None if prior is None else prior["event_digest"]
        prior_state = None if prior is None else prior["next_state"]
        if sequence != expected_sequence or prior_digest != expected_digest:
            raise QueueStoreError("event compare-and-swap conflict")
        if event.next_state not in TRANSITIONS.get(prior_state, ()):
            raise QueueStoreError("invalid lifecycle transition")
        values = {
            **event.__dict__, "sequence": sequence + 1,
            "previous_digest": prior_digest, "previous_state": prior_state,
        }
        event_digest = _digest(values)
        connection.execute(
            "INSERT INTO builder_events VALUES "
            "(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (event.event_id, event.blueprint_id, event.blueprint_version,
             event.blueprint_digest, event.slice_id, event.slice_version,
             sequence + 1, prior_digest, prior_state, event.next_state,
             event.reason, event.actor_id, int(event.actor_authenticated),
             event.attempt_id, event.dependency_digest, event.policy_version,
             event.created_at, event_digest),
        )
        connection.commit()
        return sequence + 1, event_digest
    except sqlite3.IntegrityError as error:
        connection.rollback()
        raise QueueStoreError("duplicate durable event identity") from error
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
