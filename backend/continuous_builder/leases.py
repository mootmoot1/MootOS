"""Durable attempt ownership, leases, and local idempotency records."""

import sqlite3
from dataclasses import dataclass

from backend.db import connect
from .text_safety import utf8_length
from .timestamps import parse_timestamp


class LeaseError(RuntimeError):
    """Raised when durable attempt or lease coordination fails closed."""


def _identity(value, name):
    if (
        not isinstance(value, str) or not value
        or utf8_length(value) > 256
    ):
        raise LeaseError(f"{name} is malformed or excessive")
    return value


def _timestamp(value, name):
    return parse_timestamp(value, name, LeaseError)


RECONCILIATION_VERDICTS = (
    "worker_confirmed_stopped", "worker_confirmed_running",
)


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
    reconciliation_verdict: str = None


@dataclass(frozen=True)
class IdempotencyResult:
    key: str
    operation: str
    content_digest: str
    created_at: str
    replayed: bool


@dataclass(frozen=True)
class ReconciliationRecord:
    reconciliation_id: str
    lease_id: str
    attempt_id: str
    verdict: str
    evidence: str
    actor_id: str
    reconciled_at: str


def create_attempt(
    database_path, attempt_id, blueprint_id, blueprint_version,
    slice_id, slice_version, owner_id, created_at,
):
    for value, name in (
        (attempt_id, "attempt ID"), (blueprint_id, "blueprint ID"),
        (blueprint_version, "blueprint version"), (slice_id, "slice ID"),
        (slice_version, "slice version"), (owner_id, "owner ID"),
    ):
        _identity(value, name)
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
    for value, name in (
        (lease_id, "lease ID"), (attempt_id, "attempt ID"),
        (slice_id, "slice ID"), (owner_id, "owner ID"),
    ):
        _identity(value, name)
    acquired = _timestamp(acquired_at, "acquired_at")
    expires = _timestamp(expires_at, "expires_at")
    if expires <= acquired:
        raise LeaseError("lease expiry must follow acquisition")
    connection = connect(database_path)
    try:
        connection.execute("BEGIN IMMEDIATE")
        attempt = connection.execute(
            "SELECT slice_id, owner_id, blueprint_id, blueprint_version, "
            "slice_version FROM builder_attempts WHERE attempt_id=?",
            (attempt_id,),
        ).fetchone()
        if attempt is None or attempt["slice_id"] != slice_id or (
            attempt["owner_id"] != owner_id
        ):
            raise LeaseError("lease ownership binding mismatch")
        connection.execute(
            "INSERT INTO builder_leases VALUES (?,?,?,?,?,?,NULL,?,?,?)",
            (lease_id, attempt_id, slice_id, owner_id, acquired_at,
             expires_at, attempt["blueprint_id"],
             attempt["blueprint_version"], attempt["slice_version"]),
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
        reconciliation = None
        if row is not None:
            reconciliation = connection.execute(
                "SELECT verdict FROM builder_lease_reconciliations "
                "WHERE lease_id=? ORDER BY reconciled_at DESC LIMIT 1",
                (lease_id,),
            ).fetchone()
    finally:
        connection.close()
    if row is None:
        raise LeaseError("lease does not exist")
    expired = observed >= _timestamp(row["expires_at"], "expires_at")
    verdict = reconciliation["verdict"] if reconciliation is not None else None
    if row["released_at"]:
        status = "released"
    elif not expired:
        status = "active"
    elif verdict == "worker_confirmed_running":
        status = "needs_human"
    else:
        status = "expired_uncertain"
    return LeaseStatus(
        row["lease_id"], row["attempt_id"], row["slice_id"],
        row["owner_id"], status, expired,
        reconciliation_verdict=verdict,
    )


def reconcile_expired_lease(
    database_path, reconciliation_id, lease_id, actor_id, verdict,
    evidence, reconciled_at,
):
    """Explicitly and durably resolve an expired, unreleased lease.

    Expiry alone never implies the worker stopped. A verdict with
    supporting evidence is required before a slice can be redispatched:
    ``worker_confirmed_stopped`` releases the lease so a new attempt may
    be leased; ``worker_confirmed_running`` records the uncertainty as an
    explicit needs-human state and leaves the lease held, so nothing can
    silently take over.
    """
    for value, name in (
        (reconciliation_id, "reconciliation ID"), (lease_id, "lease ID"),
        (actor_id, "actor ID"), (evidence, "reconciliation evidence"),
    ):
        _identity(value, name)
    if verdict not in RECONCILIATION_VERDICTS:
        raise LeaseError("reconciliation verdict is unsupported")
    reconciled = _timestamp(reconciled_at, "reconciled_at")
    connection = connect(database_path)
    try:
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute(
            "SELECT attempt_id, expires_at, released_at "
            "FROM builder_leases WHERE lease_id=?", (lease_id,),
        ).fetchone()
        if row is None:
            raise LeaseError("lease does not exist")
        if row["released_at"] is not None:
            raise LeaseError("lease is already released")
        if reconciled < _timestamp(row["expires_at"], "expires_at"):
            raise LeaseError("lease has not expired")
        connection.execute(
            "INSERT INTO builder_lease_reconciliations VALUES "
            "(?,?,?,?,?,?,?)",
            (reconciliation_id, lease_id, row["attempt_id"], verdict,
             evidence, actor_id, reconciled_at),
        )
        if verdict == "worker_confirmed_stopped":
            connection.execute(
                "UPDATE builder_leases SET released_at=? "
                "WHERE lease_id=? AND released_at IS NULL",
                (reconciled_at, lease_id),
            )
        connection.commit()
    except sqlite3.IntegrityError as error:
        connection.rollback()
        raise LeaseError("duplicate reconciliation identity") from error
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
    return ReconciliationRecord(
        reconciliation_id, lease_id, row["attempt_id"], verdict, evidence,
        actor_id, reconciled_at,
    )


def release_lease(database_path, lease_id, owner_id, released_at):
    _identity(lease_id, "lease ID")
    _identity(owner_id, "owner ID")
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
    """Reserve an idempotency key, distinguishing three outcomes.

    An unseen key is durably reserved. The same key replayed with the
    same operation/content digest is a safe no-op that returns the
    original record (``replayed=True``) rather than failing -- callers
    retrying after a timeout must not be punished for it. The same key
    reused with a *different* operation or content digest is a genuine
    identity conflict and fails closed.
    """
    for value, name in (
        (key, "idempotency key"), (operation, "operation"),
        (content_digest, "content digest"),
    ):
        _identity(value, name)
    _timestamp(created_at, "created_at")
    connection = connect(database_path)
    try:
        connection.execute("BEGIN IMMEDIATE")
        existing = connection.execute(
            "SELECT operation, content_digest, created_at "
            "FROM builder_idempotency WHERE idempotency_key=?",
            (key,),
        ).fetchone()
        if existing is not None:
            if (
                existing["operation"] == operation
                and existing["content_digest"] == content_digest
            ):
                connection.commit()
                return IdempotencyResult(
                    key, operation, content_digest, existing["created_at"],
                    replayed=True,
                )
            raise LeaseError(
                "idempotency key conflicts with a differing request"
            )
        connection.execute(
            "INSERT INTO builder_idempotency VALUES (?,?,?,?)",
            (key, operation, content_digest, created_at),
        )
        connection.commit()
        return IdempotencyResult(
            key, operation, content_digest, created_at, replayed=False,
        )
    except sqlite3.IntegrityError as error:
        connection.rollback()
        raise LeaseError("duplicate durable idempotency identity") from error
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
