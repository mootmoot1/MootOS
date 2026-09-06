"""GP-D2 -- Append-only Job Events with optional digest chaining.

Events are the sole mutable history for a job. Headers are immutable;
derived state is a pure reducer over the event log. Duplicate event IDs,
sequence violations, and malformed payloads fail closed.
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

JOB_EVENT_SCHEMA_VERSION = "gpd-job-event-v1"
MAX_EVENT_BYTES = 32 * 1024
MAX_PAYLOAD_KEYS = 32
_TOKEN = object()

EVENT_KINDS = frozenset({
    "job_created",
    "job_admitted",
    "job_ready",
    "attempt_started",
    "lease_acquired",
    "lease_released",
    "heartbeat",
    "progress_noted",
    "checkpoint_recorded",
    "side_effect_recorded",
    "execution_unknown_declared",
    "reconciliation_recorded",
    "cancellation_requested",
    "cancelled",
    "stalled",
    "timed_out",
    "failed",
    "retryable_marked",
    "terminal_success",
    "terminal_failure",
    "waiting",
    "running_marked",
})


class JobEventError(GPAEvalSchemaError):
    """Raised when a job event cannot be appended safely."""


@dataclass(frozen=True)
class JobEvent:
    """One append-only ledger event. Worker claims are evidence only."""

    schema_version: str
    event_id: str
    job_id: str
    sequence: int
    previous_event_digest: object
    event_kind: str
    attempt_id: object
    actor_kind: str
    actor_id: str
    reason_code: str
    payload: dict
    created_at: str
    event_digest: str
    worker_claim: bool = False
    _token: object = field(default=None, repr=False, compare=False)

    def __post_init__(self):
        if self._token is not _TOKEN:
            raise JobEventError("JobEvent requires trusted factory")
        if self.schema_version != JOB_EVENT_SCHEMA_VERSION:
            raise JobEventError("schema_version is unsupported")
        require_id(self.event_id, "event_id")
        require_id(self.job_id, "job_id")
        if type(self.sequence) is not int or self.sequence < 1:
            raise JobEventError("sequence is malformed")
        if self.previous_event_digest is not None:
            require_sha256(
                self.previous_event_digest, "previous_event_digest"
            )
        if self.sequence == 1 and self.previous_event_digest is not None:
            raise JobEventError("first event must have null previous digest")
        if self.sequence > 1 and self.previous_event_digest is None:
            raise JobEventError("non-first event requires previous digest")
        if self.event_kind not in EVENT_KINDS:
            raise JobEventError("event_kind is unsupported")
        if self.attempt_id is not None:
            require_id(self.attempt_id, "attempt_id")
        if self.actor_kind not in (
            "system", "human", "supervisor", "worker_claim"
        ):
            raise JobEventError("actor_kind is unsupported")
        require_id(self.actor_id, "actor_id")
        require_text(self.reason_code, "reason_code", 128)
        if type(self.payload) is not dict:
            raise JobEventError("payload must be a dict")
        if len(self.payload) > MAX_PAYLOAD_KEYS:
            raise JobEventError("payload exceeds key bound")
        # Payload must be JSON-canonicalizable with sorted keys only.
        try:
            canonical_json(self.payload)
        except (TypeError, ValueError) as error:
            raise JobEventError("payload is not canonicalizable") from error
        parse_timestamp(self.created_at, "created_at", JobEventError)
        if type(self.worker_claim) is not bool:
            raise JobEventError("worker_claim must be boolean")
        if self.worker_claim and self.actor_kind != "worker_claim":
            raise JobEventError("worker_claim requires actor_kind worker_claim")
        require_sha256(self.event_digest, "event_digest")
        if self.event_digest != sha256_hex(canonical_json(self._body())):
            raise JobEventError("event_digest mismatch")
        if len(canonical_json(self.to_dict())) > MAX_EVENT_BYTES:
            raise JobEventError("event exceeds byte bound")

    def _body(self):
        return {
            "actor_id": self.actor_id,
            "actor_kind": self.actor_kind,
            "attempt_id": self.attempt_id,
            "created_at": self.created_at,
            "event_id": self.event_id,
            "event_kind": self.event_kind,
            "job_id": self.job_id,
            "payload": self.payload,
            "previous_event_digest": self.previous_event_digest,
            "reason_code": self.reason_code,
            "schema_version": self.schema_version,
            "sequence": self.sequence,
            "worker_claim": self.worker_claim,
        }

    def to_dict(self):
        body = dict(self._body())
        body["event_digest"] = self.event_digest
        return body


def create_job_event(**values):
    values.setdefault("schema_version", JOB_EVENT_SCHEMA_VERSION)
    values.setdefault("worker_claim", False)
    values.setdefault("attempt_id", None)
    values.setdefault("previous_event_digest", None)
    if "payload" not in values or values["payload"] is None:
        values["payload"] = {}
    if type(values["payload"]) is not dict:
        raise JobEventError("payload must be a dict")
    # Normalize payload via round-trip canonical load for stability.
    import json
    values["payload"] = json.loads(
        canonical_json(values["payload"]).decode("utf-8")
    )
    body = {
        "actor_id": values["actor_id"],
        "actor_kind": values["actor_kind"],
        "attempt_id": values.get("attempt_id"),
        "created_at": values["created_at"],
        "event_id": values["event_id"],
        "event_kind": values["event_kind"],
        "job_id": values["job_id"],
        "payload": values["payload"],
        "previous_event_digest": values.get("previous_event_digest"),
        "reason_code": values["reason_code"],
        "schema_version": values["schema_version"],
        "sequence": values["sequence"],
        "worker_claim": values.get("worker_claim", False),
    }
    digest = sha256_hex(canonical_json(body))
    return JobEvent(**{**values, "event_digest": digest, "_token": _TOKEN})


def validate_event_chain(events):
    """Fail closed on duplicate IDs, sequence gaps, or digest breaks."""
    if type(events) not in (list, tuple):
        raise JobEventError("events must be a sequence")
    seen_ids = set()
    prev_digest = None
    expected_seq = 1
    for event in events:
        if not isinstance(event, JobEvent):
            raise JobEventError("event entry invalid")
        if event.event_id in seen_ids:
            raise JobEventError("duplicate durable event identity")
        seen_ids.add(event.event_id)
        if event.sequence != expected_seq:
            raise JobEventError("sequence violation")
        if event.previous_event_digest != prev_digest:
            raise JobEventError("event digest chain break")
        prev_digest = event.event_digest
        expected_seq += 1
    return True
