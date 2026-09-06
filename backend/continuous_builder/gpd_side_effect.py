"""GP-D7 -- Side-effect identity, EXECUTION_UNKNOWN, and reconciliation.

Lost contact while a side effect may have happened must not assume
success, failure, or safe retry. Represent EXECUTION_UNKNOWN and
RECONCILE before repeating non-idempotent / external actions.

GP-D records identity and reconciliation contracts only — it does NOT
perform GitHub / network / provider operations.
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

SIDE_EFFECT_SCHEMA_VERSION = "gpd-side-effect-v1"
RECONCILE_SCHEMA_VERSION = "gpd-reconcile-v1"
MAX_RECORD_BYTES = 16 * 1024
_TOKEN = object()

SIDE_EFFECT_OP_TYPES = frozenset({
    "github_pr_create",
    "github_comment",
    "filesystem_write",
    "provider_invoke",
    "queue_transition",
    "external_webhook",
    "other_external",
})

SIDE_EFFECT_STATUSES = frozenset({
    "proposed",
    "requested",
    "receipted",
    "uncertain",
    "reconciled_applied",
    "reconciled_absent",
    "reconciled_conflict",
    "cancelled",
})

CERTAINTY = frozenset({"certain", "uncertain", "unknown"})

RECONCILE_VERDICTS = frozenset({
    "side_effect_confirmed_applied",
    "side_effect_confirmed_absent",
    "side_effect_conflict",
    "needs_human",
    "safe_to_retry_idempotent",
    "unsafe_to_retry",
})


class SideEffectError(GPAEvalSchemaError):
    """Raised when side-effect / reconciliation contracts fail closed."""


@dataclass(frozen=True)
class SideEffectIdentity:
    schema_version: str
    side_effect_id: str
    job_id: str
    attempt_id: str
    op_type: str
    target: str
    idempotency_key: str
    request_digest: str
    status: str
    certainty: str
    receipt_digest: object
    created_at: str
    side_effect_sha256: str
    performed: bool = False
    _token: object = field(default=None, repr=False, compare=False)

    def __post_init__(self):
        if self._token is not _TOKEN:
            raise SideEffectError(
                "SideEffectIdentity requires trusted factory"
            )
        if self.schema_version != SIDE_EFFECT_SCHEMA_VERSION:
            raise SideEffectError("schema_version unsupported")
        require_id(self.side_effect_id, "side_effect_id")
        require_id(self.job_id, "job_id")
        require_id(self.attempt_id, "attempt_id")
        if self.op_type not in SIDE_EFFECT_OP_TYPES:
            raise SideEffectError("op_type unsupported")
        require_text(self.target, "target", 512)
        require_text(self.idempotency_key, "idempotency_key", 256)
        require_sha256(self.request_digest, "request_digest")
        if self.status not in SIDE_EFFECT_STATUSES:
            raise SideEffectError("status unsupported")
        if self.certainty not in CERTAINTY:
            raise SideEffectError("certainty unsupported")
        if self.receipt_digest is not None:
            require_sha256(self.receipt_digest, "receipt_digest")
        parse_timestamp(self.created_at, "created_at", SideEffectError)
        # GP-D never performs the side effect.
        if self.performed is not False:
            raise SideEffectError("GP-D must not perform side effects")
        require_sha256(self.side_effect_sha256, "side_effect_sha256")
        if self.side_effect_sha256 != sha256_hex(canonical_json(self._body())):
            raise SideEffectError("side_effect_sha256 mismatch")

    def _body(self):
        return {
            "attempt_id": self.attempt_id,
            "certainty": self.certainty,
            "created_at": self.created_at,
            "idempotency_key": self.idempotency_key,
            "job_id": self.job_id,
            "op_type": self.op_type,
            "performed": False,
            "receipt_digest": self.receipt_digest,
            "request_digest": self.request_digest,
            "schema_version": self.schema_version,
            "side_effect_id": self.side_effect_id,
            "status": self.status,
            "target": self.target,
        }

    def to_dict(self):
        body = dict(self._body())
        body["side_effect_sha256"] = self.side_effect_sha256
        return body


@dataclass(frozen=True)
class ReconciliationRecord:
    schema_version: str
    reconciliation_id: str
    job_id: str
    attempt_id: str
    side_effect_id: object
    verdict: str
    evidence_digest: str
    actor_id: str
    reconciled_at: str
    clears_execution_unknown: bool
    retry_eligible_after: bool
    reconciliation_sha256: str
    _token: object = field(default=None, repr=False, compare=False)

    def __post_init__(self):
        if self._token is not _TOKEN:
            raise SideEffectError(
                "ReconciliationRecord requires trusted factory"
            )
        if self.schema_version != RECONCILE_SCHEMA_VERSION:
            raise SideEffectError("schema_version unsupported")
        require_id(self.reconciliation_id, "reconciliation_id")
        require_id(self.job_id, "job_id")
        require_id(self.attempt_id, "attempt_id")
        if self.side_effect_id is not None:
            require_id(self.side_effect_id, "side_effect_id")
        if self.verdict not in RECONCILE_VERDICTS:
            raise SideEffectError("verdict unsupported")
        require_sha256(self.evidence_digest, "evidence_digest")
        require_id(self.actor_id, "actor_id")
        parse_timestamp(self.reconciled_at, "reconciled_at", SideEffectError)
        if type(self.clears_execution_unknown) is not bool:
            raise SideEffectError("clears_execution_unknown must be boolean")
        if type(self.retry_eligible_after) is not bool:
            raise SideEffectError("retry_eligible_after must be boolean")
        # Blind retry of unsafe SE is forbidden.
        if (
            self.verdict == "unsafe_to_retry"
            and self.retry_eligible_after
        ):
            raise SideEffectError(
                "unsafe_to_retry cannot mark retry eligible"
            )
        if (
            self.verdict == "needs_human"
            and self.retry_eligible_after
        ):
            raise SideEffectError("needs_human cannot auto-enable retry")
        require_sha256(
            self.reconciliation_sha256, "reconciliation_sha256"
        )
        if self.reconciliation_sha256 != sha256_hex(
            canonical_json(self._body())
        ):
            raise SideEffectError("reconciliation_sha256 mismatch")

    def _body(self):
        return {
            "actor_id": self.actor_id,
            "attempt_id": self.attempt_id,
            "clears_execution_unknown": self.clears_execution_unknown,
            "evidence_digest": self.evidence_digest,
            "job_id": self.job_id,
            "reconciled_at": self.reconciled_at,
            "reconciliation_id": self.reconciliation_id,
            "retry_eligible_after": self.retry_eligible_after,
            "schema_version": self.schema_version,
            "side_effect_id": self.side_effect_id,
            "verdict": self.verdict,
        }

    def to_dict(self):
        body = dict(self._body())
        body["reconciliation_sha256"] = self.reconciliation_sha256
        return body


def create_side_effect_identity(**values):
    values.setdefault("schema_version", SIDE_EFFECT_SCHEMA_VERSION)
    values.setdefault("receipt_digest", None)
    values["performed"] = False
    body = {
        "attempt_id": values["attempt_id"],
        "certainty": values["certainty"],
        "created_at": values["created_at"],
        "idempotency_key": values["idempotency_key"],
        "job_id": values["job_id"],
        "op_type": values["op_type"],
        "performed": False,
        "receipt_digest": values.get("receipt_digest"),
        "request_digest": values["request_digest"],
        "schema_version": values["schema_version"],
        "side_effect_id": values["side_effect_id"],
        "status": values["status"],
        "target": values["target"],
    }
    digest = sha256_hex(canonical_json(body))
    return SideEffectIdentity(
        **{**values, "side_effect_sha256": digest, "_token": _TOKEN}
    )


def create_reconciliation_record(**values):
    values.setdefault("schema_version", RECONCILE_SCHEMA_VERSION)
    values.setdefault("side_effect_id", None)
    body = {
        "actor_id": values["actor_id"],
        "attempt_id": values["attempt_id"],
        "clears_execution_unknown": values["clears_execution_unknown"],
        "evidence_digest": values["evidence_digest"],
        "job_id": values["job_id"],
        "reconciled_at": values["reconciled_at"],
        "reconciliation_id": values["reconciliation_id"],
        "retry_eligible_after": values["retry_eligible_after"],
        "schema_version": values["schema_version"],
        "side_effect_id": values.get("side_effect_id"),
        "verdict": values["verdict"],
    }
    digest = sha256_hex(canonical_json(body))
    return ReconciliationRecord(
        **{**values, "reconciliation_sha256": digest, "_token": _TOKEN}
    )


def detect_duplicate_side_effect_identity(existing, candidate):
    if not isinstance(candidate, SideEffectIdentity):
        raise SideEffectError("candidate invalid")
    for item in existing:
        if item.side_effect_id == candidate.side_effect_id:
            raise SideEffectError("duplicate side_effect identity")
        if (
            item.idempotency_key == candidate.idempotency_key
            and item.request_digest != candidate.request_digest
        ):
            raise SideEffectError(
                "idempotency key conflicts with differing request"
            )
        if (
            item.idempotency_key == candidate.idempotency_key
            and item.request_digest == candidate.request_digest
        ):
            return True  # safe replay
    return False


def execution_unknown_blocks_blind_retry(state_name, side_effects):
    """True when retry of non-idempotent SE must not proceed blindly."""
    if state_name == "execution_unknown":
        return True
    for se in side_effects:
        if se.certainty in ("uncertain", "unknown") and se.status in (
            "requested", "uncertain"
        ):
            return True
    return False


def retry_eligibility(state_name, reconciliation=None, side_effects=()):
    """Deterministic retry gate. Reconcile first when unknown."""
    if state_name in ("cancelled", "terminal_success", "terminal_failure"):
        return False
    if execution_unknown_blocks_blind_retry(state_name, side_effects):
        if reconciliation is None:
            return False
        if not isinstance(reconciliation, ReconciliationRecord):
            raise SideEffectError("reconciliation invalid")
        return bool(reconciliation.retry_eligible_after)
    if state_name in ("retryable", "ready", "failed", "stalled", "timed_out"):
        return True
    return False
