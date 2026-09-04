"""Pure, read-only bridge from durable Phase 2 state to Phase 1 readiness
evidence (``DependencyReceipt``).

Phase 3 (worker dispatch, not built yet) must never accept a caller's
bare assertion of ``DependencyReceipt(authoritative=True)`` -- that field
is exactly the kind of claim a compromised or buggy caller could forge,
and nothing in ``dependency_analysis.py`` itself can tell a forged
receipt from a real one (it only checks internal consistency of whatever
receipts it is handed). This module is the only place authority is
allowed to originate from: it derives every receipt from

  * the stored, immutable blueprint/slice version in ``builder_slices``
    (blueprint_store.py's durable snapshot -- never the caller's claim
    of what version a dependency is at), and
  * the replayed, integrity-checked event history for that exact slice
    (queue_projection.replay_slice, which re-verifies the whole digest
    chain and every transition against ``TRANSITIONS`` before returning
    anything),

never from what a caller says is true. Every receipt's ``receipt_id`` is
itself a digest of the evidence used to produce it, so a receipt cannot
be relabeled or replayed against different evidence without changing its
own identity.

Stale or forged evidence fails closed: a missing/rebased slice, a
version mismatch, or a corrupt event chain all produce
``authoritative=False`` (or ``passed=False``) rather than raising past a
default-success value. This module performs no writes, no dispatch, and
no worker execution -- it only reads what Phase 2 already durably
recorded.
"""

import hashlib
import json

from backend.db import connect
from .dependency_analysis import DependencyReceipt
from .queue_projection import QueueIntegrityError, replay_slice

COMPLETE_STATE = "done"


class ReadinessBridgeError(RuntimeError):
    """Raised when bridge inputs themselves are malformed."""


def _receipt_id(
    blueprint_id, blueprint_version, slice_id, slice_version, evidence,
):
    payload = "|".join((
        blueprint_id, blueprint_version, slice_id, slice_version, evidence,
    ))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def derive_dependency_receipt(
    database_path, blueprint_id, blueprint_version, dependency_slice_id,
    expected_slice_version,
):
    """Derive one ``DependencyReceipt`` purely from durable state.

    Returns ``authoritative=True, passed=True`` only when the dependency
    slice's stored version matches ``expected_slice_version`` exactly and
    its replayed, integrity-checked event history shows it reached the
    terminal "done" state. Anything else -- missing slice, version
    drift, a corrupt or absent event chain -- fails closed with
    ``authoritative=False``, never a default success.
    """
    for value, name in (
        (blueprint_id, "blueprint ID"), (blueprint_version, "blueprint version"),
        (dependency_slice_id, "dependency slice ID"),
        (expected_slice_version, "expected slice version"),
    ):
        if not isinstance(value, str) or not value:
            raise ReadinessBridgeError(f"{name} is malformed")

    connection = connect(database_path)
    try:
        stored = connection.execute(
            "SELECT slice_version FROM builder_slices WHERE "
            "blueprint_id=? AND blueprint_version=? AND slice_id=?",
            (blueprint_id, blueprint_version, dependency_slice_id),
        ).fetchone()
    finally:
        connection.close()

    if stored is None or stored["slice_version"] != expected_slice_version:
        return DependencyReceipt(
            receipt_id=_receipt_id(
                blueprint_id, blueprint_version, dependency_slice_id,
                expected_slice_version, "no_matching_stored_version",
            ),
            slice_id=dependency_slice_id,
            slice_version=expected_slice_version, passed=False,
            authoritative=False,
        )

    try:
        projection = replay_slice(
            database_path, blueprint_id, blueprint_version,
            dependency_slice_id,
        )
    except QueueIntegrityError:
        return DependencyReceipt(
            receipt_id=_receipt_id(
                blueprint_id, blueprint_version, dependency_slice_id,
                expected_slice_version, "integrity_check_failed",
            ),
            slice_id=dependency_slice_id,
            slice_version=expected_slice_version, passed=False,
            authoritative=False,
        )

    return DependencyReceipt(
        receipt_id=_receipt_id(
            blueprint_id, blueprint_version, dependency_slice_id,
            expected_slice_version, projection.event_digest,
        ),
        slice_id=dependency_slice_id, slice_version=expected_slice_version,
        passed=projection.current_state == COMPLETE_STATE,
        authoritative=True,
    )


def derive_dependency_receipts(
    database_path, blueprint_id, blueprint_version, slice_id,
):
    """Derive receipts for every hard and soft dependency declared for
    ``slice_id`` in its own durable, stored blueprint snapshot -- never
    from a caller-supplied dependency list. Returns ``()`` (no receipts
    to bridge) if the slice itself has no durable snapshot."""
    connection = connect(database_path)
    try:
        row = connection.execute(
            "SELECT canonical_json FROM builder_slices WHERE "
            "blueprint_id=? AND blueprint_version=? AND slice_id=?",
            (blueprint_id, blueprint_version, slice_id),
        ).fetchone()
    finally:
        connection.close()
    if row is None:
        return ()
    definition = json.loads(row["canonical_json"])
    dependency_ids = sorted(
        set(definition["hard_dependencies"])
        | set(definition["soft_dependencies"])
    )
    receipts = []
    for dependency_id in dependency_ids:
        connection = connect(database_path)
        try:
            dependency_row = connection.execute(
                "SELECT slice_version FROM builder_slices WHERE "
                "blueprint_id=? AND blueprint_version=? AND slice_id=?",
                (blueprint_id, blueprint_version, dependency_id),
            ).fetchone()
        finally:
            connection.close()
        if dependency_row is None:
            continue
        receipts.append(derive_dependency_receipt(
            database_path, blueprint_id, blueprint_version, dependency_id,
            dependency_row["slice_version"],
        ))
    return tuple(receipts)
