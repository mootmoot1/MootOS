"""GP-D6 -- Bounded immutable checkpoint contract.

Checkpoints are not huge worker memory dumps. Worker checkpoint claims are
validated and bounded; tampering fails closed via digest checks.
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

CHECKPOINT_SCHEMA_VERSION = "gpd-checkpoint-v1"
MAX_CHECKPOINT_BYTES = 24 * 1024
MAX_CURSOR_BYTES = 1024
MAX_NOTES = 16
_TOKEN = object()


class CheckpointError(GPAEvalSchemaError):
    """Raised when a checkpoint cannot be sealed safely."""


@dataclass(frozen=True)
class CheckpointContract:
    schema_version: str
    checkpoint_id: str
    job_id: str
    attempt_id: str
    sequence_at_checkpoint: int
    progress_cursor: str
    evidence_digests: tuple
    notes: tuple
    created_at: str
    header_sha256: str
    checkpoint_sha256: str
    worker_claim: bool = False
    system_accepted: bool = False
    _token: object = field(default=None, repr=False, compare=False)

    def __post_init__(self):
        if self._token is not _TOKEN:
            raise CheckpointError("CheckpointContract requires trusted factory")
        if self.schema_version != CHECKPOINT_SCHEMA_VERSION:
            raise CheckpointError("schema_version unsupported")
        require_id(self.checkpoint_id, "checkpoint_id")
        require_id(self.job_id, "job_id")
        require_id(self.attempt_id, "attempt_id")
        if (
            type(self.sequence_at_checkpoint) is not int
            or self.sequence_at_checkpoint < 1
        ):
            raise CheckpointError("sequence_at_checkpoint malformed")
        require_text(self.progress_cursor, "progress_cursor", MAX_CURSOR_BYTES)
        if type(self.evidence_digests) is not tuple:
            raise CheckpointError("evidence_digests malformed")
        if len(self.evidence_digests) > 32:
            raise CheckpointError("evidence_digests exceeds bound")
        for digest in self.evidence_digests:
            require_sha256(digest, "evidence_digests")
        if type(self.notes) is not tuple or len(self.notes) > MAX_NOTES:
            raise CheckpointError("notes malformed or excessive")
        for note in self.notes:
            require_text(note, "notes", 256)
        parse_timestamp(self.created_at, "created_at", CheckpointError)
        require_sha256(self.header_sha256, "header_sha256")
        if type(self.worker_claim) is not bool:
            raise CheckpointError("worker_claim must be boolean")
        if type(self.system_accepted) is not bool:
            raise CheckpointError("system_accepted must be boolean")
        # Worker claims are never auto-accepted.
        if self.worker_claim and self.system_accepted:
            raise CheckpointError(
                "worker checkpoint claim cannot self-accept"
            )
        require_sha256(self.checkpoint_sha256, "checkpoint_sha256")
        if self.checkpoint_sha256 != sha256_hex(canonical_json(self._body())):
            raise CheckpointError("checkpoint_sha256 mismatch")
        if len(canonical_json(self.to_dict())) > MAX_CHECKPOINT_BYTES:
            raise CheckpointError("checkpoint exceeds byte bound")

    def _body(self):
        return {
            "attempt_id": self.attempt_id,
            "checkpoint_id": self.checkpoint_id,
            "created_at": self.created_at,
            "evidence_digests": list(self.evidence_digests),
            "header_sha256": self.header_sha256,
            "job_id": self.job_id,
            "notes": list(self.notes),
            "progress_cursor": self.progress_cursor,
            "schema_version": self.schema_version,
            "sequence_at_checkpoint": self.sequence_at_checkpoint,
            "system_accepted": self.system_accepted,
            "worker_claim": self.worker_claim,
        }

    def to_dict(self):
        body = dict(self._body())
        body["checkpoint_sha256"] = self.checkpoint_sha256
        return body


def create_checkpoint_contract(**values):
    values.setdefault("schema_version", CHECKPOINT_SCHEMA_VERSION)
    values.setdefault("worker_claim", False)
    values.setdefault("system_accepted", False)
    digests = values.get("evidence_digests", ())
    if not isinstance(digests, tuple):
        digests = tuple(digests)
    values["evidence_digests"] = digests
    notes = values.get("notes", ())
    if not isinstance(notes, tuple):
        notes = tuple(notes)
    values["notes"] = notes
    body = {
        "attempt_id": values["attempt_id"],
        "checkpoint_id": values["checkpoint_id"],
        "created_at": values["created_at"],
        "evidence_digests": list(values["evidence_digests"]),
        "header_sha256": values["header_sha256"],
        "job_id": values["job_id"],
        "notes": list(values["notes"]),
        "progress_cursor": values["progress_cursor"],
        "schema_version": values["schema_version"],
        "sequence_at_checkpoint": values["sequence_at_checkpoint"],
        "system_accepted": values.get("system_accepted", False),
        "worker_claim": values.get("worker_claim", False),
    }
    digest = sha256_hex(canonical_json(body))
    return CheckpointContract(
        **{**values, "checkpoint_sha256": digest, "_token": _TOKEN}
    )


def detect_checkpoint_tamper(checkpoint, expected_sha256):
    if not isinstance(checkpoint, CheckpointContract):
        raise CheckpointError("checkpoint invalid")
    require_sha256(expected_sha256, "expected_sha256")
    if checkpoint.checkpoint_sha256 != expected_sha256:
        raise CheckpointError("checkpoint tamper detected")
    # Re-derive.
    if checkpoint.checkpoint_sha256 != sha256_hex(
        canonical_json(checkpoint._body())
    ):
        raise CheckpointError("checkpoint tamper detected")
    return False
