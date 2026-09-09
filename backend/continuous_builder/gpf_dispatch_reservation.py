"""GP-F1 -- Durable Dispatch Reservation / Replay Prevention.

Answers exactly one question, durably: **has this exact GP-E
``WorkerRequest`` already been dispatched for this GP-D attempt?**

A ``DispatchReservation`` binds ``request_id``, the full ``WorkerRequest``
digest, ``job_id``, ``attempt_id``, the GP-D header/attempt digests the
request itself claims, and the exact Context Engine package digest/base
SHA the request was built against. It is persisted through
:class:`gpd_job_store.JobLedgerStore` (see
``write_dispatch_reservation``/``load_dispatch_reservation``) -- the
existing GP-D file-backed, append-safe, atomic-rename ledger -- so a
restart preserves it without any new persistence technology or schema
migration.

A reservation is evidence, never authority:

- Sealing a reservation does **not** launch a worker.
- Reusing this module's ``request_sha256`` check for the *same* attempt
  with the *same* packet is a **replay** -- the caller must not launch a
  second time, but this module does not itself prevent that; see GP-F4
  (launch authorization boundary) for the actual gate.
- The *same* attempt with a **conflicting** packet fails closed at the
  store layer (``JobStoreError``, mirroring
  ``JobLedgerStore.write_header``'s existing "refuse to mutate" idiom) --
  it is never silently overwritten.
- A retry is a brand new GP-D attempt identity (``attempt_id``), which
  reserves its own, independent slot. This module never reuses a
  attempt's reservation slot for a different packet.

Zero authority: every reservation carries the same seven-flag false
authority vocabulary as ``gpd_job_header.DurableJobHeader``, plus an
explicit ``dispatch_authorized`` flag that is always False. Nothing here
answers "should this launch" -- only "has this exact thing already been
reserved".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from .gpa_eval_schema import (
    AUTHORITY_FLAGS,
    GPAEvalSchemaError,
    canonical_json,
    require_base_sha,
    require_id,
    require_sha256,
    sha256_hex,
)
from .gpe_protocol import WorkerRequest
from .timestamps import parse_timestamp

RESERVATION_SCHEMA_VERSION = "gpf-dispatch-reservation-v1"
MAX_RESERVATION_BYTES = 8 * 1024
_TOKEN = object()


class DispatchReservationError(GPAEvalSchemaError):
    """Raised when a dispatch reservation cannot be sealed safely."""


def _utcnow_iso():
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class DispatchReservation:
    """Durable, system-owned dispatch-replay record. Grants no capability."""

    schema_version: str
    job_id: str
    attempt_id: str
    request_id: str
    request_sha256: str
    header_sha256: str
    attempt_sha256: str
    context_base_sha: str
    context_package_digest: str
    reserved_at: str
    reservation_sha256: str
    dispatch_authorized: bool = False
    publication_authorized: bool = False
    queue_transition_authorized: bool = False
    github_authorized: bool = False
    merge_authorized: bool = False
    main_advancement_authorized: bool = False
    result_trusted: bool = False
    worker_output_trusted: bool = False
    _token: object = field(default=None, repr=False, compare=False)

    def __post_init__(self):
        if self._token is not _TOKEN:
            raise DispatchReservationError(
                "dispatch reservation requires trusted construction"
            )
        if self.schema_version != RESERVATION_SCHEMA_VERSION:
            raise DispatchReservationError("schema_version is unsupported")
        for name in ("job_id", "attempt_id", "request_id"):
            require_id(getattr(self, name), name)
        for name in (
            "request_sha256",
            "header_sha256",
            "attempt_sha256",
            "context_package_digest",
            "reservation_sha256",
        ):
            require_sha256(getattr(self, name), name)
        require_base_sha(self.context_base_sha, "context_base_sha")
        parse_timestamp(self.reserved_at, "reserved_at", DispatchReservationError)
        if self.dispatch_authorized is not False:
            raise DispatchReservationError(
                "a reservation can never claim dispatch authority"
            )
        for name in AUTHORITY_FLAGS:
            if getattr(self, name, False) is not False:
                raise DispatchReservationError(
                    "dispatch reservation cannot claim authority"
                )
        if self.reservation_sha256 != sha256_hex(canonical_json(self._body())):
            raise DispatchReservationError("reservation_sha256 mismatch")
        if len(canonical_json(self.to_dict())) > MAX_RESERVATION_BYTES:
            raise DispatchReservationError("reservation exceeds byte bound")

    def _body(self):
        return {
            "attempt_id": self.attempt_id,
            "attempt_sha256": self.attempt_sha256,
            "context_base_sha": self.context_base_sha,
            "context_package_digest": self.context_package_digest,
            "dispatch_authorized": False,
            "github_authorized": False,
            "header_sha256": self.header_sha256,
            "job_id": self.job_id,
            "main_advancement_authorized": False,
            "merge_authorized": False,
            "publication_authorized": False,
            "queue_transition_authorized": False,
            "request_id": self.request_id,
            "request_sha256": self.request_sha256,
            "reserved_at": self.reserved_at,
            "result_trusted": False,
            "schema_version": self.schema_version,
            "worker_output_trusted": False,
        }

    def to_dict(self):
        body = dict(self._body())
        body["reservation_sha256"] = self.reservation_sha256
        return body


def _seal(values):
    for name in AUTHORITY_FLAGS:
        values[name] = False
    values["dispatch_authorized"] = False
    provisional = object.__new__(DispatchReservation)
    for name, value in values.items():
        object.__setattr__(provisional, name, value)
    return DispatchReservation(
        **values,
        reservation_sha256=sha256_hex(canonical_json(provisional._body())),
        _token=_TOKEN,
    )


def create_dispatch_reservation(*, request, reserved_at=None):
    """Seal a :class:`DispatchReservation` from a validated GP-E
    ``WorkerRequest``.

    Deliberately takes the whole, already-validated request object
    rather than loose keyword fields -- every bound value is read
    straight from ``request`` so a caller cannot supply a
    reservation whose ``job_id``/``attempt_id``/digests disagree with
    the request it claims to reserve. This is the only path that should
    ever mint a *new* reservation.
    """
    if not isinstance(request, WorkerRequest):
        raise DispatchReservationError("request is invalid")
    values = {
        "schema_version": RESERVATION_SCHEMA_VERSION,
        "job_id": request.job_id,
        "attempt_id": request.attempt_id,
        "request_id": request.request_id,
        "request_sha256": request.digest,
        "header_sha256": request.header_sha256,
        "attempt_sha256": request.attempt_sha256,
        "context_base_sha": request.context[2],
        "context_package_digest": request.context[1],
        "reserved_at": reserved_at or _utcnow_iso(),
    }
    return _seal(values)


def reseal_dispatch_reservation_from_storage(**values):
    """Reconstruct a :class:`DispatchReservation` from trusted, already
    digest-verified on-disk fields.

    NOT for minting a new reservation from arbitrary/untrusted input --
    used only by :meth:`gpd_job_store.JobLedgerStore.load_dispatch_
    reservation` to rebuild the sealed object from bytes this same
    process already wrote and is about to digest-check again.
    """
    return _seal(dict(values))


def classify_reservation_attempt(existing, candidate):
    """Compare a candidate reservation against one already on disk.

    Returns ``"replay"`` when the two are byte-identical (the caller must
    still treat this as "already dispatched", never as authorization to
    launch again), or ``"conflict"`` when the same ``(job_id, attempt_id)``
    slot disagrees on any bound value -- callers must fail closed on
    conflict, never silently prefer one side.
    """
    if not isinstance(existing, DispatchReservation):
        raise DispatchReservationError("existing reservation is invalid")
    if not isinstance(candidate, DispatchReservation):
        raise DispatchReservationError("candidate reservation is invalid")
    if (existing.job_id, existing.attempt_id) != (
        candidate.job_id, candidate.attempt_id,
    ):
        raise DispatchReservationError(
            "reservations are not for the same job/attempt slot"
        )
    if existing.reservation_sha256 == candidate.reservation_sha256:
        return "replay"
    return "conflict"


def dispatch_reservation_grants_no_capability():
    """TRUST REVIEW helper: True -- a reservation grants no capability."""
    return True
