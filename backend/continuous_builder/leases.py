"""Durable attempt ownership, leases, and local idempotency records."""

import sqlite3
from dataclasses import dataclass
from datetime import datetime

from backend.db import connect


class LeaseError(RuntimeError):
    """Raised when durable attempt or lease coordination fails closed."""


def _timestamp(value, name):
    if not isinstance(value, str):
        raise LeaseError(f"{name} must be an ISO timestamp")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        raise LeaseError(f"{name} must be an ISO timestamp") from error
    if parsed.tzinfo is None:
        raise LeaseError(f"{name} must include a timezone")
    return parsed


@dataclass(frozen=True)
class LeaseStatus:
    lease_id: str
    attempt_id: str
    slice_id: str
    owner_id: str
    status: str
    expired: bool
    worker_stopped: bool = False
    takeover_authorized: bool = False


def create_attempt(
    database_path, attempt_id, blueprint_id, blueprint_version,
    slice_id, slice_version, owner_id, created_at,
):
    _timestamp(created_at, "created_at")
    connection = connect(database_path)
    try:
        connection.execute("BEGIN IMMEDIATE")
        source = connection.execute(
            "SELECT slice_version FROM builder_slices WHERE blueprint_id=? "
            "AND blueprint_version=? AND slice_id=?",
            (blueprint_id, blueprint_version, slice_id),
        ).fetchone()
        if source is None or source["slice_version"] != slice_version:
            raise LeaseError("attempt source binding mismatch")
        connection.execute(
            "INSERT INTO builder_attempts VALUES (?,?,?,?,?,?,?)",
            (attempt_id, blueprint_id, blueprint_version, slice_id,
             slice_version, owner_id, created_at),
        )
        connection.commit()
    except sqlite3.IntegrityError as error:
        connection.rollback()
        raise LeaseError("duplicate attempt identity") from error
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def acquire_lease(
    database_path, lease_id, attempt_id, slice_id, owner_id,
    acquired_at, expires_at,
):
    acquired = _timestamp(acquired_at, "acquired_at")
    expires = _timestamp(expires_at, "expires_at")
    if expires <= acquired:
        raise LeaseError("lease expiry must follow acquisition")
    connection = connect(database_path)
    try:
        connection.execute("BEGIN IMMEDIATE")
        attempt = connection.execute(
            "SELECT slice_id, owner_id FROM builder_attempts "
            "WHERE attempt_id=?",
            (attempt_id,),
        ).fetchone()
        if attempt is None or attempt["slice_id"] != slice_id or (
            attempt["owner_id"] != owner_id
        ):
            raise LeaseError("lease ownership binding mismatch")
        connection.execute(
            "INSERT INTO builder_leases VALUES (?,?,?,?,?,?,NULL)",
            (lease_id, attempt_id, slice_id, owner_id,
             acquired_at, expires_at),
        )
        connection.commit()
    except sqlite3.IntegrityError as error:
        connection.rollback()
        raise LeaseError("duplicate active lease or lease identity") from error
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def inspect_lease(database_path, lease_id, observed_at):
    observed = _timestamp(observed_at, "observed_at")
    connection = connect(database_path)
    try:
        row = connection.execute(
            "SELECT * FROM builder_leases WHERE lease_id=?", (lease_id,)
        ).fetchone()
    finally:
        connection.close()
    if row is None:
        raise LeaseError("lease does not exist")
    expired = observed >= _timestamp(row["expires_at"], "expires_at")
    status = "released" if row["released_at"] else (
        "expired_uncertain" if expired else "active"
    )
    return LeaseStatus(
        row["lease_id"], row["attempt_id"], row["slice_id"],
        row["owner_id"], status, expired,
    )


def release_lease(database_path, lease_id, owner_id, released_at):
    _timestamp(released_at, "released_at")
    connection = connect(database_path)
    try:
        connection.execute("BEGIN IMMEDIATE")
        cursor = connection.execute(
            "UPDATE builder_leases SET released_at=? WHERE lease_id=? "
            "AND owner_id=? AND released_at IS NULL",
            (released_at, lease_id, owner_id),
        )
        if cursor.rowcount != 1:
            raise LeaseError("lease release ownership conflict")
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def reserve_idempotency(
    database_path, key, operation, content_digest, created_at,
):
    _timestamp(created_at, "created_at")
    connection = connect(database_path)
    try:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            "INSERT INTO builder_idempotency VALUES (?,?,?,?)",
            (key, operation, content_digest, created_at),
        )
        connection.commit()
    except sqlite3.IntegrityError as error:
        connection.rollback()
        raise LeaseError("duplicate durable idempotency identity") from error
    finally:
        connection.close()
