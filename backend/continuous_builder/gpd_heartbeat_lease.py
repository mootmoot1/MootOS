"""GP-D5 -- Heartbeat / Lease / Stall evidence.

Lease expiry is NOT proof that no side effect occurred. Heartbeats without
progress are stall evidence. One active owner per job lease.
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

HEARTBEAT_SCHEMA_VERSION = "gpd-heartbeat-v1"
LEASE_SCHEMA_VERSION = "gpd-lease-v1"
STALL_SCHEMA_VERSION = "gpd-stall-v1"
MAX_RECORD_BYTES = 16 * 1024
_TOKEN = object()


class HeartbeatLeaseError(GPAEvalSchemaError):
    """Raised when heartbeat/lease/stall evidence fails closed."""


@dataclass(frozen=True)
class LeaseRecord:
    schema_version: str
    lease_id: str
    job_id: str
    attempt_id: str
    owner_id: str
    acquired_at: str
    expires_at: str
    released_at: object
    lease_sha256: str
    _token: object = field(default=None, repr=False, compare=False)

    def __post_init__(self):
        if self._token is not _TOKEN:
            raise HeartbeatLeaseError("LeaseRecord requires trusted factory")
        if self.schema_version != LEASE_SCHEMA_VERSION:
            raise HeartbeatLeaseError("schema_version unsupported")
        require_id(self.lease_id, "lease_id")
        require_id(self.job_id, "job_id")
        require_id(self.attempt_id, "attempt_id")
        require_id(self.owner_id, "owner_id")
        acquired = parse_timestamp(
            self.acquired_at, "acquired_at", HeartbeatLeaseError
        )
        expires = parse_timestamp(
            self.expires_at, "expires_at", HeartbeatLeaseError
        )
        if expires <= acquired:
            raise HeartbeatLeaseError("lease expiry must follow acquisition")
        if self.released_at is not None:
            released = parse_timestamp(
                self.released_at, "released_at", HeartbeatLeaseError
            )
            if released < acquired:
                raise HeartbeatLeaseError("released_at precedes acquired_at")
        require_sha256(self.lease_sha256, "lease_sha256")
        if self.lease_sha256 != sha256_hex(canonical_json(self._body())):
            raise HeartbeatLeaseError("lease_sha256 mismatch")

    def _body(self):
        return {
            "acquired_at": self.acquired_at,
            "attempt_id": self.attempt_id,
            "expires_at": self.expires_at,
            "job_id": self.job_id,
            "lease_id": self.lease_id,
            "owner_id": self.owner_id,
            "released_at": self.released_at,
            "schema_version": self.schema_version,
        }

    def to_dict(self):
        body = dict(self._body())
        body["lease_sha256"] = self.lease_sha256
        return body

    def is_expired(self, observed_at):
        observed = parse_timestamp(
            observed_at, "observed_at", HeartbeatLeaseError
        )
        expires = parse_timestamp(
            self.expires_at, "expires_at", HeartbeatLeaseError
        )
        return observed >= expires and self.released_at is None


@dataclass(frozen=True)
class HeartbeatEvidence:
    schema_version: str
    heartbeat_id: str
    job_id: str
    attempt_id: str
    lease_id: str
    observed_at: str
    progress_token: object
    progress_advanced: bool
    heartbeat_sha256: str
    _token: object = field(default=None, repr=False, compare=False)

    def __post_init__(self):
        if self._token is not _TOKEN:
            raise HeartbeatLeaseError(
                "HeartbeatEvidence requires trusted factory"
            )
        if self.schema_version != HEARTBEAT_SCHEMA_VERSION:
            raise HeartbeatLeaseError("schema_version unsupported")
        require_id(self.heartbeat_id, "heartbeat_id")
        require_id(self.job_id, "job_id")
        require_id(self.attempt_id, "attempt_id")
        require_id(self.lease_id, "lease_id")
        parse_timestamp(self.observed_at, "observed_at", HeartbeatLeaseError)
        if self.progress_token is not None:
            require_text(self.progress_token, "progress_token", 256)
        if type(self.progress_advanced) is not bool:
            raise HeartbeatLeaseError("progress_advanced must be boolean")
        require_sha256(self.heartbeat_sha256, "heartbeat_sha256")
        if self.heartbeat_sha256 != sha256_hex(canonical_json(self._body())):
            raise HeartbeatLeaseError("heartbeat_sha256 mismatch")

    def _body(self):
        return {
            "attempt_id": self.attempt_id,
            "heartbeat_id": self.heartbeat_id,
            "job_id": self.job_id,
            "lease_id": self.lease_id,
            "observed_at": self.observed_at,
            "progress_advanced": self.progress_advanced,
            "progress_token": self.progress_token,
            "schema_version": self.schema_version,
        }

    def to_dict(self):
        body = dict(self._body())
        body["heartbeat_sha256"] = self.heartbeat_sha256
        return body


@dataclass(frozen=True)
class StallEvidence:
    schema_version: str
    stall_id: str
    job_id: str
    attempt_id: str
    lease_id: str
    reason_code: str
    heartbeat_without_progress_count: int
    lease_expired: bool
    observed_at: str
    stall_sha256: str
    side_effect_absence_proven: bool = False
    _token: object = field(default=None, repr=False, compare=False)

    def __post_init__(self):
        if self._token is not _TOKEN:
            raise HeartbeatLeaseError("StallEvidence requires trusted factory")
        if self.schema_version != STALL_SCHEMA_VERSION:
            raise HeartbeatLeaseError("schema_version unsupported")
        require_id(self.stall_id, "stall_id")
        require_id(self.job_id, "job_id")
        require_id(self.attempt_id, "attempt_id")
        require_id(self.lease_id, "lease_id")
        require_text(self.reason_code, "reason_code", 128)
        if (
            type(self.heartbeat_without_progress_count) is not int
            or self.heartbeat_without_progress_count < 0
        ):
            raise HeartbeatLeaseError("heartbeat_without_progress_count bad")
        if type(self.lease_expired) is not bool:
            raise HeartbeatLeaseError("lease_expired must be boolean")
        if self.side_effect_absence_proven is not False:
            # Expiry never proves absence of side effects.
            raise HeartbeatLeaseError(
                "expired lease does not prove side-effect absence"
            )
        parse_timestamp(self.observed_at, "observed_at", HeartbeatLeaseError)
        require_sha256(self.stall_sha256, "stall_sha256")
        if self.stall_sha256 != sha256_hex(canonical_json(self._body())):
            raise HeartbeatLeaseError("stall_sha256 mismatch")

    def _body(self):
        return {
            "attempt_id": self.attempt_id,
            "heartbeat_without_progress_count": (
                self.heartbeat_without_progress_count
            ),
            "job_id": self.job_id,
            "lease_expired": self.lease_expired,
            "lease_id": self.lease_id,
            "observed_at": self.observed_at,
            "reason_code": self.reason_code,
            "schema_version": self.schema_version,
            "side_effect_absence_proven": False,
            "stall_id": self.stall_id,
        }

    def to_dict(self):
        body = dict(self._body())
        body["stall_sha256"] = self.stall_sha256
        return body


def create_lease_record(**values):
    values.setdefault("schema_version", LEASE_SCHEMA_VERSION)
    values.setdefault("released_at", None)
    body = {
        "acquired_at": values["acquired_at"],
        "attempt_id": values["attempt_id"],
        "expires_at": values["expires_at"],
        "job_id": values["job_id"],
        "lease_id": values["lease_id"],
        "owner_id": values["owner_id"],
        "released_at": values.get("released_at"),
        "schema_version": values["schema_version"],
    }
    digest = sha256_hex(canonical_json(body))
    return LeaseRecord(**{**values, "lease_sha256": digest, "_token": _TOKEN})


def create_heartbeat_evidence(**values):
    values.setdefault("schema_version", HEARTBEAT_SCHEMA_VERSION)
    values.setdefault("progress_token", None)
    body = {
        "attempt_id": values["attempt_id"],
        "heartbeat_id": values["heartbeat_id"],
        "job_id": values["job_id"],
        "lease_id": values["lease_id"],
        "observed_at": values["observed_at"],
        "progress_advanced": values["progress_advanced"],
        "progress_token": values.get("progress_token"),
        "schema_version": values["schema_version"],
    }
    digest = sha256_hex(canonical_json(body))
    return HeartbeatEvidence(
        **{**values, "heartbeat_sha256": digest, "_token": _TOKEN}
    )


def create_stall_evidence(**values):
    values.setdefault("schema_version", STALL_SCHEMA_VERSION)
    if values.get("side_effect_absence_proven") is True:
        raise HeartbeatLeaseError(
            "expired lease does not prove side-effect absence"
        )
    values["side_effect_absence_proven"] = False
    body = {
        "attempt_id": values["attempt_id"],
        "heartbeat_without_progress_count": values[
            "heartbeat_without_progress_count"
        ],
        "job_id": values["job_id"],
        "lease_expired": values["lease_expired"],
        "lease_id": values["lease_id"],
        "observed_at": values["observed_at"],
        "reason_code": values["reason_code"],
        "schema_version": values["schema_version"],
        "side_effect_absence_proven": False,
        "stall_id": values["stall_id"],
    }
    digest = sha256_hex(canonical_json(body))
    return StallEvidence(
        **{**values, "stall_sha256": digest, "_token": _TOKEN}
    )


def assert_single_active_lease(leases, job_id):
    active = [
        lease for lease in leases
        if lease.job_id == job_id and lease.released_at is None
    ]
    if len(active) > 1:
        raise HeartbeatLeaseError("multiple active owners for job lease")
    return True


def heartbeat_without_progress_is_stall_evidence(heartbeats, threshold=3):
    if type(threshold) is not int or threshold < 1:
        raise HeartbeatLeaseError("threshold malformed")
    streak = 0
    for hb in heartbeats:
        if not isinstance(hb, HeartbeatEvidence):
            raise HeartbeatLeaseError("heartbeat invalid")
        if hb.progress_advanced:
            streak = 0
        else:
            streak += 1
            if streak >= threshold:
                return True
    return False
