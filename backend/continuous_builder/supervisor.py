"""Receipt-driven, fail-closed worker supervision policy for CB-024.

This module does not launch, retry, kill, publish, or advance queue state. It
classifies one already-observed CB-022 execution, optionally binds CB-023
artifact-intake evidence, and produces immutable retry/circuit-breaker advice.
Future runtime integrations may supply trusted liveness/progress observations,
but worker-authored text is intentionally absent from every decision surface.
"""

import hashlib
import json
import re
from dataclasses import dataclass, field, replace
from typing import Optional

from .text_safety import utf8_length
from .worker_artifact import ArtifactIntakeReceipt, WorkerArtifactError
from .worker_runtime import WorkerExecutionReceipt, WorkerRuntimeError


class SupervisorError(ValueError):
    """Raised when CB-024 supervision evidence cannot be trusted."""


POLICY_VERSION = "cb-worker-supervisor-v1"
MAX_RECEIPT_BYTES = 128 * 1024
MAX_REASON_BYTES = 1024
_IDENTITY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@-]{0,255}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_POLICY_TOKEN = object()
_OBSERVATION_TOKEN = object()
_BREAKER_TOKEN = object()
_RECEIPT_TOKEN = object()

_FAILURE_CLASSES = {
    "succeeded",
    "failed",
    "crashed",
    "timed_out",
    "stalled",
    "cancelled",
    "termination_uncertain",
    "cleanup_uncertain",
    "containment_violation",
    "artifact_security_rejected",
    "unknown_failure",
}
_RETRYABLE = {"failed", "crashed", "timed_out", "stalled"}
_IMMEDIATE_OPEN = {
    "termination_uncertain",
    "cleanup_uncertain",
    "containment_violation",
    "artifact_security_rejected",
    "unknown_failure",
}


def _canonical(value):
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _digest(value):
    return hashlib.sha256(value).hexdigest()


def _identity(value, name):
    if (
        not isinstance(value, str)
        or _IDENTITY.fullmatch(value or "") is None
        or utf8_length(value) > 256
    ):
        raise SupervisorError(f"{name} is malformed")
    return value


def _sha256(value, name):
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise SupervisorError(f"{name} is malformed")
    return value


def _bounded_reason(value):
    if not isinstance(value, str) or not value or (
        utf8_length(value) > MAX_REASON_BYTES
    ):
        raise SupervisorError("supervision reason is malformed")
    return value


@dataclass(frozen=True)
class SupervisionPolicy:
    liveness_timeout_seconds: int
    stall_timeout_seconds: int
    max_retry_attempts: int
    circuit_breaker_failures: int
    kill_switch_engaged: bool
    policy_sha256: str
    policy_version: str = POLICY_VERSION
    _policy_token: object = field(default=None, repr=False, compare=False)

    def __post_init__(self):
        if self._policy_token is not _POLICY_TOKEN:
            raise SupervisorError("supervision policy requires trusted factory")
        if self.policy_version != POLICY_VERSION:
            raise SupervisorError("supervision policy version is unsupported")
        for name in ("liveness_timeout_seconds", "stall_timeout_seconds"):
            value = getattr(self, name)
            if type(value) is not int or value <= 0:
                raise SupervisorError(f"{name} is invalid")
        if (
            type(self.max_retry_attempts) is not int
            or self.max_retry_attempts < 0
            or self.max_retry_attempts > 16
        ):
            raise SupervisorError("max retry attempts is invalid")
        if (
            type(self.circuit_breaker_failures) is not int
            or not 1 <= self.circuit_breaker_failures <= 64
        ):
            raise SupervisorError("circuit breaker threshold is invalid")
        if type(self.kill_switch_engaged) is not bool:
            raise SupervisorError("kill switch state is invalid")
        if self.policy_sha256 != _digest(self._payload()):
            raise SupervisorError("supervision policy digest mismatch")

    def _body(self):
        return {
            "circuit_breaker_failures": self.circuit_breaker_failures,
            "kill_switch_engaged": self.kill_switch_engaged,
            "liveness_timeout_seconds": self.liveness_timeout_seconds,
            "max_retry_attempts": self.max_retry_attempts,
            "policy_version": POLICY_VERSION,
            "stall_timeout_seconds": self.stall_timeout_seconds,
        }

    def _payload(self):
        return _canonical(self._body())

    def canonical_bytes(self):
        value = self._body()
        value["policy_sha256"] = self.policy_sha256
        return _canonical(value)


def create_supervision_policy(
    *,
    liveness_timeout_seconds=60,
    stall_timeout_seconds=300,
    max_retry_attempts=2,
    circuit_breaker_failures=3,
    kill_switch_engaged=False,
):
    values = {
        "liveness_timeout_seconds": liveness_timeout_seconds,
        "stall_timeout_seconds": stall_timeout_seconds,
        "max_retry_attempts": max_retry_attempts,
        "circuit_breaker_failures": circuit_breaker_failures,
        "kill_switch_engaged": kill_switch_engaged,
    }
    provisional = object.__new__(SupervisionPolicy)
    for name, value in values.items():
        object.__setattr__(provisional, name, value)
    object.__setattr__(provisional, "policy_version", POLICY_VERSION)
    return SupervisionPolicy(
        **values,
        policy_sha256=_digest(provisional._payload()),
        _policy_token=_POLICY_TOKEN,
    )


@dataclass(frozen=True)
class SupervisorObservation:
    execution_receipt_digest: str
    attempt_id: str
    execution_id: str
    request_digest: str
    worker_provider_id: str
    runtime_policy_digest: str
    liveness_observed: bool
    seconds_since_liveness: int
    seconds_since_progress: int
    absolute_deadline_exceeded: bool
    cancellation_observed: bool
    stop_attempted_observed: bool
    kill_attempted_observed: bool
    containment_violation_observed: bool
    observation_sha256: str
    _observation_token: object = field(
        default=None, repr=False, compare=False
    )

    def __post_init__(self):
        if self._observation_token is not _OBSERVATION_TOKEN:
            raise SupervisorError(
                "supervisor observation requires trusted factory"
            )
        _sha256(self.execution_receipt_digest, "execution receipt digest")
        _identity(self.attempt_id, "attempt ID")
        _identity(self.execution_id, "execution ID")
        _identity(self.worker_provider_id, "worker provider ID")
        _sha256(self.request_digest, "request digest")
        _sha256(self.runtime_policy_digest, "runtime policy digest")
        for name in ("seconds_since_liveness", "seconds_since_progress"):
            value = getattr(self, name)
            if type(value) is not int or value < 0:
                raise SupervisorError(f"{name} is invalid")
        for name in (
            "liveness_observed",
            "absolute_deadline_exceeded",
            "cancellation_observed",
            "stop_attempted_observed",
            "kill_attempted_observed",
            "containment_violation_observed",
        ):
            if type(getattr(self, name)) is not bool:
                raise SupervisorError(f"{name} is invalid")
        if self.kill_attempted_observed and not self.stop_attempted_observed:
            raise SupervisorError("kill escalation requires an observed stop")
        if self.observation_sha256 != _digest(self._payload()):
            raise SupervisorError("supervisor observation digest mismatch")

    def _body(self):
        return {
            "absolute_deadline_exceeded": self.absolute_deadline_exceeded,
            "attempt_id": self.attempt_id,
            "cancellation_observed": self.cancellation_observed,
            "containment_violation_observed": (
                self.containment_violation_observed
            ),
            "execution_id": self.execution_id,
            "execution_receipt_digest": self.execution_receipt_digest,
            "kill_attempted_observed": self.kill_attempted_observed,
            "liveness_observed": self.liveness_observed,
            "request_digest": self.request_digest,
            "runtime_policy_digest": self.runtime_policy_digest,
            "seconds_since_liveness": self.seconds_since_liveness,
            "seconds_since_progress": self.seconds_since_progress,
            "stop_attempted_observed": self.stop_attempted_observed,
            "worker_provider_id": self.worker_provider_id,
        }

    def _payload(self):
        return _canonical(self._body())

    def canonical_bytes(self):
        value = self._body()
        value["observation_sha256"] = self.observation_sha256
        return _canonical(value)


def create_supervisor_observation(
    execution_receipt,
    *,
    liveness_observed=True,
    seconds_since_liveness=0,
    seconds_since_progress=0,
    absolute_deadline_exceeded=False,
    cancellation_observed=False,
    stop_attempted_observed=False,
    kill_attempted_observed=False,
    containment_violation_observed=False,
):
    _validate_execution(execution_receipt)
    values = {
        "execution_receipt_digest": execution_receipt.receipt_sha256,
        "attempt_id": execution_receipt.attempt_id,
        "execution_id": execution_receipt.execution_id,
        "request_digest": execution_receipt.request_digest,
        "worker_provider_id": execution_receipt.worker_provider_id,
        "runtime_policy_digest": execution_receipt.policy_digest,
        "liveness_observed": liveness_observed,
        "seconds_since_liveness": seconds_since_liveness,
        "seconds_since_progress": seconds_since_progress,
        "absolute_deadline_exceeded": absolute_deadline_exceeded,
        "cancellation_observed": cancellation_observed,
        "stop_attempted_observed": stop_attempted_observed,
        "kill_attempted_observed": kill_attempted_observed,
        "containment_violation_observed": containment_violation_observed,
    }
    provisional = object.__new__(SupervisorObservation)
    for name, value in values.items():
        object.__setattr__(provisional, name, value)
    return SupervisorObservation(
        **values,
        observation_sha256=_digest(provisional._payload()),
        _observation_token=_OBSERVATION_TOKEN,
    )


@dataclass(frozen=True)
class CircuitBreakerSnapshot:
    worker_provider_id: str
    request_digest: str
    state: str
    consecutive_failures: int
    last_failure_class: str
    supervision_policy_digest: str
    snapshot_sha256: str
    _breaker_token: object = field(default=None, repr=False, compare=False)

    def __post_init__(self):
        if self._breaker_token is not _BREAKER_TOKEN:
            raise SupervisorError(
                "circuit breaker snapshot requires trusted factory"
            )
        _identity(self.worker_provider_id, "worker provider ID")
        _sha256(self.request_digest, "request digest")
        _sha256(self.supervision_policy_digest, "supervision policy digest")
        if self.state not in {"closed", "open"}:
            raise SupervisorError("circuit breaker state is malformed")
        if (
            type(self.consecutive_failures) is not int
            or self.consecutive_failures < 0
            or self.consecutive_failures > 64
        ):
            raise SupervisorError("circuit breaker count is malformed")
        if self.last_failure_class not in _FAILURE_CLASSES | {"none"}:
            raise SupervisorError("circuit breaker failure class is malformed")
        if self.state == "closed" and self.consecutive_failures == 0 and (
            self.last_failure_class not in {"none", "succeeded", "cancelled"}
        ):
            raise SupervisorError("closed circuit breaker history is malformed")
        if self.snapshot_sha256 != _digest(self._payload()):
            raise SupervisorError("circuit breaker digest mismatch")

    def _body(self):
        return {
            "consecutive_failures": self.consecutive_failures,
            "last_failure_class": self.last_failure_class,
            "request_digest": self.request_digest,
            "state": self.state,
            "supervision_policy_digest": self.supervision_policy_digest,
            "worker_provider_id": self.worker_provider_id,
        }

    def _payload(self):
        return _canonical(self._body())

    def canonical_bytes(self):
        value = self._body()
        value["snapshot_sha256"] = self.snapshot_sha256
        return _canonical(value)


def create_initial_circuit_breaker(execution_receipt, policy):
    _validate_execution(execution_receipt)
    _validate_policy(policy)
    return _breaker_snapshot(
        execution_receipt,
        policy,
        state="open" if policy.kill_switch_engaged else "closed",
        consecutive_failures=0,
        last_failure_class="none",
    )


@dataclass(frozen=True)
class SupervisionReceipt:
    attempt_id: str
    execution_id: str
    request_digest: str
    execution_receipt_digest: str
    worker_provider_id: str
    runtime_policy_digest: str
    supervision_policy_digest: str
    observation_digest: str
    artifact_intake_receipt_digest: str
    final_classification: str
    observed_runtime_lifecycle_state: str
    timeout_observed: bool
    stall_observed: bool
    cancellation_observed: bool
    stop_attempted: bool
    kill_attempted: bool
    termination_confirmed: bool
    cleanup_confirmed: bool
    termination_uncertain: bool
    cleanup_uncertain: bool
    retry_eligible: bool
    retry_count: int
    retry_cap: int
    circuit_breaker_state: str
    consecutive_failures: int
    reason_code: str
    breaker_snapshot_digest: str
    receipt_sha256: str
    policy_version: str = POLICY_VERSION
    worker_output_trusted: bool = False
    result_verified: bool = False
    patch_verified: bool = False
    externally_verified: bool = False
    publication_authorized: bool = False
    queue_transition_authorized: bool = False
    github_authorized: bool = False
    _receipt_token: object = field(default=None, repr=False, compare=False)

    def __post_init__(self):
        if self._receipt_token is not _RECEIPT_TOKEN:
            raise SupervisorError("supervision receipt requires trusted factory")
        _identity(self.attempt_id, "attempt ID")
        _identity(self.execution_id, "execution ID")
        _identity(self.worker_provider_id, "worker provider ID")
        for name in (
            "request_digest",
            "execution_receipt_digest",
            "runtime_policy_digest",
            "supervision_policy_digest",
            "observation_digest",
            "breaker_snapshot_digest",
            "receipt_sha256",
        ):
            _sha256(getattr(self, name), name)
        if self.artifact_intake_receipt_digest:
            _sha256(
                self.artifact_intake_receipt_digest,
                "artifact intake receipt digest",
            )
        if self.final_classification not in _FAILURE_CLASSES:
            raise SupervisorError("supervision classification is malformed")
        if type(self.retry_count) is not int or self.retry_count < 0:
            raise SupervisorError("retry count is malformed")
        if type(self.retry_cap) is not int or self.retry_cap < 0:
            raise SupervisorError("retry cap is malformed")
        if self.circuit_breaker_state not in {"closed", "open"}:
            raise SupervisorError("circuit breaker state is malformed")
        if type(self.consecutive_failures) is not int or (
            self.consecutive_failures < 0
        ):
            raise SupervisorError("consecutive failure count is malformed")
        for name in (
            "timeout_observed", "stall_observed", "cancellation_observed",
            "stop_attempted", "kill_attempted", "termination_confirmed",
            "cleanup_confirmed", "termination_uncertain",
            "cleanup_uncertain", "retry_eligible",
        ):
            if type(getattr(self, name)) is not bool:
                raise SupervisorError(f"{name} is malformed")
        if self.kill_attempted and not self.stop_attempted:
            raise SupervisorError("kill attempt requires stop escalation")
        if self.termination_uncertain == self.termination_confirmed:
            raise SupervisorError("termination certainty is contradictory")
        if self.cleanup_uncertain == self.cleanup_confirmed:
            raise SupervisorError("cleanup certainty is contradictory")
        if self.retry_eligible and (
            self.final_classification not in _RETRYABLE
            or self.circuit_breaker_state != "closed"
            or self.retry_count >= self.retry_cap
            or self.termination_uncertain
            or self.cleanup_uncertain
        ):
            raise SupervisorError("retry eligibility is unsafe")
        if self.policy_version != POLICY_VERSION:
            raise SupervisorError("supervision receipt policy is unsupported")
        _bounded_reason(self.reason_code)
        if any(
            value is not False
            for value in (
                self.worker_output_trusted,
                self.result_verified,
                self.patch_verified,
                self.externally_verified,
                self.publication_authorized,
                self.queue_transition_authorized,
                self.github_authorized,
            )
        ):
            raise SupervisorError("supervision receipt promotes authority")
        if self.receipt_sha256 != _digest(self._payload()):
            raise SupervisorError("supervision receipt digest mismatch")
        if len(self.canonical_bytes()) > MAX_RECEIPT_BYTES:
            raise SupervisorError("supervision receipt exceeds bound")

    def _body(self):
        return {
            "artifact_intake_receipt_digest": (
                self.artifact_intake_receipt_digest
            ),
            "attempt_id": self.attempt_id,
            "breaker_snapshot_digest": self.breaker_snapshot_digest,
            "cancellation_observed": self.cancellation_observed,
            "circuit_breaker_state": self.circuit_breaker_state,
            "cleanup_confirmed": self.cleanup_confirmed,
            "cleanup_uncertain": self.cleanup_uncertain,
            "consecutive_failures": self.consecutive_failures,
            "execution_id": self.execution_id,
            "execution_receipt_digest": self.execution_receipt_digest,
            "externally_verified": False,
            "final_classification": self.final_classification,
            "github_authorized": False,
            "kill_attempted": self.kill_attempted,
            "observation_digest": self.observation_digest,
            "observed_runtime_lifecycle_state": (
                self.observed_runtime_lifecycle_state
            ),
            "patch_verified": False,
            "policy_version": POLICY_VERSION,
            "publication_authorized": False,
            "queue_transition_authorized": False,
            "reason_code": self.reason_code,
            "request_digest": self.request_digest,
            "result_verified": False,
            "retry_cap": self.retry_cap,
            "retry_count": self.retry_count,
            "retry_eligible": self.retry_eligible,
            "runtime_policy_digest": self.runtime_policy_digest,
            "stall_observed": self.stall_observed,
            "stop_attempted": self.stop_attempted,
            "supervision_policy_digest": self.supervision_policy_digest,
            "termination_confirmed": self.termination_confirmed,
            "termination_uncertain": self.termination_uncertain,
            "timeout_observed": self.timeout_observed,
            "worker_output_trusted": False,
            "worker_provider_id": self.worker_provider_id,
        }

    def _payload(self):
        return _canonical(self._body())

    def canonical_bytes(self):
        value = self._body()
        value["receipt_sha256"] = self.receipt_sha256
        return _canonical(value)


@dataclass(frozen=True)
class SupervisionDecision:
    receipt: SupervisionReceipt
    circuit_breaker: CircuitBreakerSnapshot

    def __post_init__(self):
        if not isinstance(self.receipt, SupervisionReceipt) or not isinstance(
            self.circuit_breaker, CircuitBreakerSnapshot
        ):
            raise SupervisorError("supervision decision is malformed")
        if self.receipt.breaker_snapshot_digest != (
            self.circuit_breaker.snapshot_sha256
        ):
            raise SupervisorError("supervision decision binding mismatch")


def supervise_execution(
    execution_receipt,
    policy,
    *,
    observation=None,
    artifact_intake_receipt=None,
    prior_circuit_breaker=None,
    retry_count=0,
):
    """Classify one execution and return bounded, non-executing advice."""
    _validate_execution(execution_receipt)
    _validate_policy(policy)
    if type(retry_count) is not int or retry_count < 0:
        raise SupervisorError("retry count is malformed")
    if retry_count > policy.max_retry_attempts:
        raise SupervisorError("retry count exceeds policy cap")

    if observation is None:
        observation = create_supervisor_observation(execution_receipt)
    _validate_observation(execution_receipt, observation)

    if artifact_intake_receipt is not None:
        _validate_artifact(execution_receipt, artifact_intake_receipt)

    if prior_circuit_breaker is None:
        prior_circuit_breaker = create_initial_circuit_breaker(
            execution_receipt, policy
        )
    _validate_breaker(execution_receipt, policy, prior_circuit_breaker)

    classification, stall_observed, cleanup_uncertain = _classify(
        execution_receipt,
        observation,
        artifact_intake_receipt,
        policy,
    )

    if classification in {"succeeded", "cancelled"}:
        failures = 0
    else:
        failures = min(prior_circuit_breaker.consecutive_failures + 1, 64)

    immediate_open = classification in _IMMEDIATE_OPEN
    threshold_open = failures >= policy.circuit_breaker_failures
    breaker_open = (
        policy.kill_switch_engaged
        or prior_circuit_breaker.state == "open"
        or immediate_open
        or threshold_open
    )
    if classification in {"succeeded", "cancelled"} and not (
        policy.kill_switch_engaged
    ):
        breaker_open = False

    breaker = _breaker_snapshot(
        execution_receipt,
        policy,
        state="open" if breaker_open else "closed",
        consecutive_failures=failures,
        last_failure_class=classification,
    )

    retry_eligible = (
        classification in _RETRYABLE
        and retry_count < policy.max_retry_attempts
        and breaker.state == "closed"
        and not cleanup_uncertain
        and not execution_receipt.termination_uncertain
    )
    reason = _reason_code(
        classification,
        retry_eligible,
        retry_count,
        policy,
        breaker,
    )

    artifact_digest = ""
    if artifact_intake_receipt is not None:
        artifact_digest = artifact_intake_receipt.receipt_sha256
    values = {
        "attempt_id": execution_receipt.attempt_id,
        "execution_id": execution_receipt.execution_id,
        "request_digest": execution_receipt.request_digest,
        "execution_receipt_digest": execution_receipt.receipt_sha256,
        "worker_provider_id": execution_receipt.worker_provider_id,
        "runtime_policy_digest": execution_receipt.policy_digest,
        "supervision_policy_digest": policy.policy_sha256,
        "observation_digest": observation.observation_sha256,
        "artifact_intake_receipt_digest": artifact_digest,
        "final_classification": classification,
        "observed_runtime_lifecycle_state": execution_receipt.final_state,
        "timeout_observed": bool(
            execution_receipt.timeout_observed
            or observation.absolute_deadline_exceeded
        ),
        "stall_observed": stall_observed,
        "cancellation_observed": bool(
            execution_receipt.cancellation_requested
            or observation.cancellation_observed
        ),
        "stop_attempted": observation.stop_attempted_observed,
        "kill_attempted": observation.kill_attempted_observed,
        "termination_confirmed": not execution_receipt.termination_uncertain,
        "cleanup_confirmed": not cleanup_uncertain,
        "termination_uncertain": execution_receipt.termination_uncertain,
        "cleanup_uncertain": cleanup_uncertain,
        "retry_eligible": retry_eligible,
        "retry_count": retry_count,
        "retry_cap": policy.max_retry_attempts,
        "circuit_breaker_state": breaker.state,
        "consecutive_failures": breaker.consecutive_failures,
        "reason_code": reason,
        "breaker_snapshot_digest": breaker.snapshot_sha256,
    }
    provisional = object.__new__(SupervisionReceipt)
    for name, value in values.items():
        object.__setattr__(provisional, name, value)
    object.__setattr__(provisional, "policy_version", POLICY_VERSION)
    receipt = SupervisionReceipt(
        **values,
        receipt_sha256=_digest(provisional._payload()),
        _receipt_token=_RECEIPT_TOKEN,
    )
    return SupervisionDecision(receipt, breaker)


def _validate_policy(policy):
    if not isinstance(policy, SupervisionPolicy):
        raise SupervisorError("supervision policy is invalid")
    replace(policy)


def _validate_execution(receipt):
    if not isinstance(receipt, WorkerExecutionReceipt):
        raise SupervisorError("worker execution receipt is invalid")
    try:
        replace(receipt.materialization_receipt)
        replace(receipt.enforcement_evidence)
        replace(receipt)
    except WorkerRuntimeError as error:
        raise SupervisorError(
            "worker execution receipt failed authoritative validation"
        ) from error
    if receipt.execution_performed is not True or any(
        value is not False
        for value in (
            receipt.worker_output_trusted,
            receipt.result_verified,
            receipt.patch_verified,
            receipt.externally_verified,
            receipt.publication_authorized,
            receipt.queue_transition_authorized,
            receipt.github_authorized,
        )
    ):
        raise SupervisorError("execution receipt overstates authority")


def _validate_observation(receipt, observation):
    if not isinstance(observation, SupervisorObservation):
        raise SupervisorError("supervisor observation is invalid")
    replace(observation)
    expected = (
        (observation.execution_receipt_digest, receipt.receipt_sha256),
        (observation.attempt_id, receipt.attempt_id),
        (observation.execution_id, receipt.execution_id),
        (observation.request_digest, receipt.request_digest),
        (observation.worker_provider_id, receipt.worker_provider_id),
        (observation.runtime_policy_digest, receipt.policy_digest),
    )
    if any(actual != wanted for actual, wanted in expected):
        raise SupervisorError("supervisor observation binding mismatch")


def _validate_artifact(receipt, artifact):
    if not isinstance(artifact, ArtifactIntakeReceipt):
        raise SupervisorError("artifact intake receipt is invalid")
    try:
        replace(artifact)
    except WorkerArtifactError as error:
        raise SupervisorError(
            "artifact intake receipt failed authoritative validation"
        ) from error
    expected = (
        (artifact.execution_receipt_digest, receipt.receipt_sha256),
        (artifact.attempt_id, receipt.attempt_id),
        (artifact.execution_id, receipt.execution_id),
        (artifact.request_digest, receipt.request_digest),
        (artifact.policy_digest, receipt.policy_digest),
        (
            artifact.materialization_receipt_digest,
            receipt.materialization_receipt_digest,
        ),
    )
    if any(actual != wanted for actual, wanted in expected):
        raise SupervisorError("artifact supervision binding mismatch")


def _validate_breaker(receipt, policy, breaker):
    if not isinstance(breaker, CircuitBreakerSnapshot):
        raise SupervisorError("circuit breaker snapshot is invalid")
    replace(breaker)
    expected = (
        (breaker.worker_provider_id, receipt.worker_provider_id),
        (breaker.request_digest, receipt.request_digest),
        (breaker.supervision_policy_digest, policy.policy_sha256),
    )
    if any(actual != wanted for actual, wanted in expected):
        raise SupervisorError("circuit breaker binding mismatch")


def _classify(receipt, observation, artifact, policy):
    cleanup_uncertain = not receipt.cleanup_confirmed
    if artifact is not None and artifact.teardown_uncertain:
        cleanup_uncertain = True

    if observation.containment_violation_observed:
        return "containment_violation", False, cleanup_uncertain
    if artifact is not None and artifact.status == "rejected_secret_material":
        return "artifact_security_rejected", False, cleanup_uncertain
    if receipt.termination_uncertain or receipt.final_state == (
        "termination_uncertain"
    ):
        return "termination_uncertain", False, cleanup_uncertain
    if cleanup_uncertain:
        return "cleanup_uncertain", False, True
    if receipt.cancellation_confirmed or receipt.final_state == "cancelled":
        return "cancelled", False, False

    stall = (
        receipt.timeout_observed
        and observation.liveness_observed
        and observation.seconds_since_liveness
        < policy.liveness_timeout_seconds
        and observation.seconds_since_progress
        >= policy.stall_timeout_seconds
    )
    if stall:
        return "stalled", True, False
    if receipt.timeout_observed or observation.absolute_deadline_exceeded or (
        receipt.final_state == "timed_out"
    ):
        return "timed_out", False, False
    if receipt.final_state == "crashed":
        return "crashed", False, False
    if receipt.final_state == "failed" or (
        receipt.exit_code is not None and receipt.exit_code != 0
    ):
        return "failed", False, False
    if receipt.final_state == "succeeded" and receipt.exit_code == 0:
        return "succeeded", False, False
    return "unknown_failure", False, False


def _breaker_snapshot(
    receipt,
    policy,
    *,
    state,
    consecutive_failures,
    last_failure_class,
):
    values = {
        "worker_provider_id": receipt.worker_provider_id,
        "request_digest": receipt.request_digest,
        "state": state,
        "consecutive_failures": consecutive_failures,
        "last_failure_class": last_failure_class,
        "supervision_policy_digest": policy.policy_sha256,
    }
    provisional = object.__new__(CircuitBreakerSnapshot)
    for name, value in values.items():
        object.__setattr__(provisional, name, value)
    return CircuitBreakerSnapshot(
        **values,
        snapshot_sha256=_digest(provisional._payload()),
        _breaker_token=_BREAKER_TOKEN,
    )


def _reason_code(classification, retry_eligible, retry_count, policy, breaker):
    if policy.kill_switch_engaged:
        return "kill_switch_active"
    if classification == "succeeded":
        return "execution_succeeded"
    if classification == "cancelled":
        return "execution_cancelled"
    if classification == "termination_uncertain":
        return "termination_uncertain_fail_closed"
    if classification == "cleanup_uncertain":
        return "cleanup_uncertain_fail_closed"
    if classification == "containment_violation":
        return "containment_violation_fail_closed"
    if classification == "artifact_security_rejected":
        return "artifact_security_rejection_fail_closed"
    if classification == "unknown_failure":
        return "unknown_failure_fail_closed"
    if breaker.state == "open":
        return "circuit_breaker_open"
    if retry_count >= policy.max_retry_attempts:
        return "retry_cap_exhausted"
    if retry_eligible:
        return "bounded_retry_eligible"
    return "retry_not_authorized"
