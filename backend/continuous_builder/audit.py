"""Bounded Continuous Builder audit reads and artifact references."""

import re
import sqlite3
from dataclasses import dataclass

from backend.db import connect
from .queue_projection import QueueIntegrityError, replay_slice


class AuditError(RuntimeError):
    """Raised when a bounded audit request or reference is invalid."""


_DIGEST = re.compile(r"^[0-9a-f]{64}$")
MAX_AUDIT_EVENTS = 100


@dataclass(frozen=True)
class SliceAudit:
    slice_id: str
    current_state: str
    sequence: int
    integrity_valid: bool
    blocked: bool
    events: tuple
    attempts: tuple
    leases: tuple
    artifacts: tuple
    externally_verified: bool = False


def record_artifact_reference(
    database_path, artifact_id, slice_id, attempt_id, kind,
    content_digest, size_bytes, created_at,
):
    if _DIGEST.fullmatch(content_digest or "") is None:
        raise AuditError("artifact digest is malformed")
    if type(size_bytes) is not int or not 0 <= size_bytes <= 100 * 1024 * 1024:
        raise AuditError("artifact size is outside its bound")
    if any(not isinstance(value, str) or not value or len(value) > 256
           for value in (artifact_id, slice_id, kind, created_at)):
        raise AuditError("artifact metadata is malformed")
    if not isinstance(attempt_id, str) or not attempt_id:
        raise AuditError("artifact attempt binding is required")
    connection = connect(database_path)
    try:
        connection.execute("BEGIN IMMEDIATE")
        attempt = connection.execute(
            "SELECT slice_id FROM builder_attempts WHERE attempt_id=?",
            (attempt_id,),
        ).fetchone()
        if attempt is None or attempt["slice_id"] != slice_id:
            raise AuditError("artifact attempt binding mismatch")
        connection.execute(
            "INSERT INTO builder_artifacts VALUES (?,?,?,?,?,?,?)",
            (artifact_id, slice_id, attempt_id, kind, content_digest,
             size_bytes, created_at),
        )
        connection.commit()
    except sqlite3.IntegrityError as error:
        connection.rollback()
        raise AuditError("duplicate or unbound artifact reference") from error
    finally:
        connection.close()


def read_slice_audit(
    database_path, blueprint_id, blueprint_version, slice_id, limit=100,
):
    if type(limit) is not int or not 1 <= limit <= MAX_AUDIT_EVENTS:
        raise AuditError("audit limit is outside its bound")
    projection = replay_slice(
        database_path, blueprint_id, blueprint_version, slice_id
    )
    connection = connect(database_path)
    try:
        events = connection.execute(
            "SELECT event_id, sequence, previous_state, next_state, reason, "
            "actor_id, actor_authenticated, attempt_id, dependency_digest, "
            "policy_version, created_at, event_digest FROM builder_events "
            "WHERE blueprint_id=? AND blueprint_version=? AND slice_id=? "
            "ORDER BY sequence DESC LIMIT ?",
            (blueprint_id, blueprint_version, slice_id, limit),
        ).fetchall()
        attempts = connection.execute(
            "SELECT attempt_id, owner_id, created_at FROM builder_attempts "
            "WHERE blueprint_id=? AND blueprint_version=? AND slice_id=? "
            "ORDER BY created_at DESC LIMIT ?",
            (blueprint_id, blueprint_version, slice_id, limit),
        ).fetchall()
        leases = connection.execute(
            "SELECT l.lease_id, l.attempt_id, l.owner_id, l.acquired_at, "
            "l.expires_at, l.released_at FROM builder_leases l "
            "JOIN builder_attempts a ON a.attempt_id=l.attempt_id "
            "WHERE a.blueprint_id=? AND a.blueprint_version=? "
            "AND a.slice_id=? ORDER BY l.acquired_at DESC LIMIT ?",
            (blueprint_id, blueprint_version, slice_id, limit),
        ).fetchall()
        artifacts = connection.execute(
            "SELECT r.artifact_id, r.attempt_id, r.kind, r.content_digest, "
            "r.size_bytes, r.created_at FROM builder_artifacts r "
            "JOIN builder_attempts a ON a.attempt_id=r.attempt_id "
            "WHERE a.blueprint_id=? AND a.blueprint_version=? "
            "AND a.slice_id=? ORDER BY r.created_at DESC LIMIT ?",
            (blueprint_id, blueprint_version, slice_id, limit),
        ).fetchall()
    finally:
        connection.close()

    def convert(rows):
        return tuple(dict(row) for row in rows)

    return SliceAudit(
        slice_id, projection.current_state, projection.sequence, True,
        projection.current_state in ("blocked", "changes_requested", "paused"),
        convert(events), convert(attempts), convert(leases),
        convert(artifacts),
    )


def validate_blueprint_integrity(database_path, blueprint_id, version):
    connection = connect(database_path)
    try:
        slices = connection.execute(
            "SELECT slice_id FROM builder_slices WHERE blueprint_id=? "
            "AND blueprint_version=? ORDER BY slice_id",
            (blueprint_id, version),
        ).fetchall()
    finally:
        connection.close()
    results = []
    for row in slices:
        try:
            replay_slice(database_path, blueprint_id, version, row["slice_id"])
            results.append((row["slice_id"], True))
        except QueueIntegrityError:
            results.append((row["slice_id"], False))
    return tuple(results)
