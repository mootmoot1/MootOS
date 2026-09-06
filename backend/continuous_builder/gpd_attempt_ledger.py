"""GP-D4 -- Attempt ledger.

A retry always creates a new attempt identity. Prior attempts are never
overwritten. Attempts are evidence-bound records, not launch authority.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .gpa_eval_schema import (
    GPAEvalSchemaError,
    canonical_json,
    require_id,
    require_sha256,
    require_text,
    sha256_hex,
)
from .timestamps import parse_timestamp

ATTEMPT_SCHEMA_VERSION = "gpd-attempt-v1"
MAX_ATTEMPT_BYTES = 16 * 1024
_TOKEN = object()

ATTEMPT_STATUSES = frozenset({
    "started", "running", "checkpointed", "released", "failed",
    "timed_out", "stalled", "execution_unknown", "succeeded_unproven",
    "reconciled",
})


class AttemptLedgerError(GPAEvalSchemaError):
    """Raised when attempt ledger records fail closed."""


@dataclass(frozen=True)
class AttemptRecord:
    schema_version: str
    attempt_id: str
    job_id: str
    attempt_number: int
    owner_id: str
    started_at: str
    status: str
    prior_attempt_id: object
    header_sha256: str
    attempt_sha256: str
    worker_claim_success: bool = False
    _token: object = field(default=None, repr=False, compare=False)

    def __post_init__(self):
        if self._token is not _TOKEN:
            raise AttemptLedgerError("AttemptRecord requires trusted factory")
        if self.schema_version != ATTEMPT_SCHEMA_VERSION:
            raise AttemptLedgerError("schema_version is unsupported")
        require_id(self.attempt_id, "attempt_id")
        require_id(self.job_id, "job_id")
        if type(self.attempt_number) is not int or self.attempt_number < 1:
            raise AttemptLedgerError("attempt_number is malformed")
        require_id(self.owner_id, "owner_id")
        parse_timestamp(self.started_at, "started_at", AttemptLedgerError)
        if self.status not in ATTEMPT_STATUSES:
            raise AttemptLedgerError("attempt status unsupported")
        if self.prior_attempt_id is not None:
            require_id(self.prior_attempt_id, "prior_attempt_id")
        if self.attempt_number == 1 and self.prior_attempt_id is not None:
            raise AttemptLedgerError("first attempt cannot name a prior")
        if self.attempt_number > 1 and self.prior_attempt_id is None:
            raise AttemptLedgerError("retry attempt requires prior_attempt_id")
        require_sha256(self.header_sha256, "header_sha256")
        if type(self.worker_claim_success) is not bool:
            raise AttemptLedgerError("worker_claim_success must be boolean")
        require_sha256(self.attempt_sha256, "attempt_sha256")
        if self.attempt_sha256 != sha256_hex(canonical_json(self._body())):
            raise AttemptLedgerError("attempt_sha256 mismatch")
        if len(canonical_json(self.to_dict())) > MAX_ATTEMPT_BYTES:
            raise AttemptLedgerError("attempt exceeds byte bound")

    def _body(self):
        return {
            "attempt_id": self.attempt_id,
            "attempt_number": self.attempt_number,
            "header_sha256": self.header_sha256,
            "job_id": self.job_id,
            "owner_id": self.owner_id,
            "prior_attempt_id": self.prior_attempt_id,
            "schema_version": self.schema_version,
            "started_at": self.started_at,
            "status": self.status,
            "worker_claim_success": self.worker_claim_success,
        }

    def to_dict(self):
        body = dict(self._body())
        body["attempt_sha256"] = self.attempt_sha256
        return body


def create_attempt_record(**values):
    values.setdefault("schema_version", ATTEMPT_SCHEMA_VERSION)
    values.setdefault("prior_attempt_id", None)
    values.setdefault("worker_claim_success", False)
    body = {
        "attempt_id": values["attempt_id"],
        "attempt_number": values["attempt_number"],
        "header_sha256": values["header_sha256"],
        "job_id": values["job_id"],
        "owner_id": values["owner_id"],
        "prior_attempt_id": values.get("prior_attempt_id"),
        "schema_version": values["schema_version"],
        "started_at": values["started_at"],
        "status": values["status"],
        "worker_claim_success": values.get("worker_claim_success", False),
    }
    digest = sha256_hex(canonical_json(body))
    return AttemptRecord(
        **{**values, "attempt_sha256": digest, "_token": _TOKEN}
    )


def assert_new_attempt_identity(existing_attempts, new_attempt):
    """Reject overwrite of history and duplicate attempt IDs."""
    if not isinstance(new_attempt, AttemptRecord):
        raise AttemptLedgerError("new attempt invalid")
    ids = {a.attempt_id for a in existing_attempts}
    if new_attempt.attempt_id in ids:
        raise AttemptLedgerError("duplicate attempt identity")
    numbers = {a.attempt_number for a in existing_attempts}
    if new_attempt.attempt_number in numbers:
        raise AttemptLedgerError("attempt_number already used")
    if existing_attempts:
        last = max(existing_attempts, key=lambda a: a.attempt_number)
        if new_attempt.attempt_number != last.attempt_number + 1:
            raise AttemptLedgerError("attempt_number must be monotonic")
        if new_attempt.prior_attempt_id != last.attempt_id:
            raise AttemptLedgerError("prior_attempt_id mismatch")
        if new_attempt.header_sha256 != last.header_sha256:
            raise AttemptLedgerError("header ceilings cannot change on retry")
    return True
