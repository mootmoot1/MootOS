"""Inert worker launch, cancellation, and untrusted result contracts."""

import hashlib
import json
import re
from dataclasses import dataclass

from .text_safety import utf8_length
from .worker_authorization import WorkerDispatchAuthorization


class WorkerActionError(ValueError):
    """Raised when an inert worker action or receipt is malformed."""


OPERATION = "launch_bounded_worker"
MAX_ACTION_BYTES = 32 * 1024
MAX_RESULT_BYTES = 64 * 1024
MAX_OUTPUT_BYTES = 32 * 1024
_IDENTITY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@-]{0,255}$")
_SECRET = re.compile(
    r"(?i)(?:password|secret|api[_-]?key|authorization|bearer)\s*[:=]"
)


def _identity(value, name):
    if (
        not isinstance(value, str) or _IDENTITY.fullmatch(value) is None
        or utf8_length(value) > 256
    ):
        raise WorkerActionError(f"{name} is malformed")
    return value


def _text(value, name, limit=MAX_OUTPUT_BYTES, *, allow_empty=False):
    if not isinstance(value, str) or (not allow_empty and not value.strip()):
        raise WorkerActionError(f"{name} is malformed")
    if utf8_length(value) > limit or _SECRET.search(value):
        raise WorkerActionError(f"{name} is unsafe or excessive")
    if any(ord(character) < 32 and character not in "\n\t"
           for character in value):
        raise WorkerActionError(f"{name} contains control characters")
    return value.strip()


def _canonical(value):
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")


@dataclass(frozen=True)
class InertWorkerLaunchAction:
    authorization: WorkerDispatchAuthorization
    operation: str
    authorization_digest: str
    request_digest: str
    attempt_id: str
    worker_descriptor_digest: str
    action_digest: str
    action_prepared: bool = True
    executed: bool = False
    execution_performed: bool = False

    def __post_init__(self):
        if not isinstance(self.authorization, WorkerDispatchAuthorization):
            raise WorkerActionError("dispatch authorization is invalid")
        if not self.authorization.authorized:
            raise WorkerActionError("dispatch is not authorized")
        if self.operation != OPERATION:
            raise WorkerActionError("worker operation is unsupported")
        expected_values = (
            (self.authorization_digest,
             self.authorization.authorization_digest),
            (self.request_digest, self.authorization.request_digest),
            (self.attempt_id, self.authorization.attempt_id),
            (self.worker_descriptor_digest,
             self.authorization.worker_descriptor_digest),
        )
        if any(actual != expected for actual, expected in expected_values):
            raise WorkerActionError("action source binding mismatch")
        if self.action_prepared is not True or self.executed is not False or (
            self.execution_performed is not False
        ):
            raise WorkerActionError("inert action cannot claim execution")
        if self.action_digest != hashlib.sha256(self._payload()).hexdigest():
            raise WorkerActionError("action digest mismatch")
        if len(self.canonical_bytes()) > MAX_ACTION_BYTES:
            raise WorkerActionError("worker action exceeds byte bound")

    def _body(self):
        return {
            "action_prepared": True,
            "attempt_id": self.attempt_id,
            "authorization_digest": self.authorization_digest,
            "executed": False,
            "execution_performed": False,
            "operation": self.operation,
            "request_digest": self.request_digest,
            "worker_descriptor_digest": self.worker_descriptor_digest,
        }

    def _payload(self):
        return _canonical(self._body())

    def canonical_bytes(self):
        value = self._body()
        value["action_digest"] = self.action_digest
        return _canonical(value)


def prepare_worker_launch_action(authorization):
    if not isinstance(authorization, WorkerDispatchAuthorization):
        raise WorkerActionError("dispatch authorization is invalid")
    provisional = object.__new__(InertWorkerLaunchAction)
    values = {
        "authorization": authorization,
        "operation": OPERATION,
        "authorization_digest": authorization.authorization_digest,
        "request_digest": authorization.request_digest,
        "attempt_id": authorization.attempt_id,
        "worker_descriptor_digest": authorization.worker_descriptor_digest,
        "action_prepared": True,
        "executed": False,
        "execution_performed": False,
    }
    for name, value in values.items():
        object.__setattr__(provisional, name, value)
    digest = hashlib.sha256(provisional._payload()).hexdigest()
    return InertWorkerLaunchAction(**values, action_digest=digest)


@dataclass(frozen=True)
class WorkerCancellationIntent:
    cancellation_id: str
    action_digest: str
    attempt_id: str
    supplied_actor_identity: str
    bounded_reason: str
    cancellation_requested: bool = True
    cancellation_performed: bool = False
    cancellation_verified: bool = False

    def __post_init__(self):
        for value, name in (
            (self.cancellation_id, "cancellation ID"),
            (self.attempt_id, "attempt ID"),
            (self.supplied_actor_identity, "actor identity"),
        ):
            _identity(value, name)
        if not re.fullmatch(r"[0-9a-f]{64}", self.action_digest):
            raise WorkerActionError("action digest is malformed")
        object.__setattr__(self, "bounded_reason", _text(
            self.bounded_reason, "cancellation reason", 2048,
        ))
        if self.cancellation_requested is not True or (
            self.cancellation_performed is not False
            or self.cancellation_verified is not False
        ):
            raise WorkerActionError("cancellation intent cannot claim result")


@dataclass(frozen=True)
class WorkerResultInput:
    receipt_id: str
    action_digest: str
    attempt_id: str
    worker_descriptor_digest: str
    reported_status: str
    bounded_output: str

    def __post_init__(self):
        _identity(self.receipt_id, "receipt ID")
        _identity(self.attempt_id, "attempt ID")
        for value, name in (
            (self.action_digest, "action digest"),
            (self.worker_descriptor_digest, "worker descriptor digest"),
        ):
            if not isinstance(value, str) or not re.fullmatch(
                r"[0-9a-f]{64}", value
            ):
                raise WorkerActionError(f"{name} is malformed")
        if self.reported_status not in (
            "reported_success", "reported_failure", "reported_cancelled",
            "not_attempted",
        ):
            raise WorkerActionError("reported result status is unsupported")
        output = _text(
            self.bounded_output, "provider output", allow_empty=(
                self.reported_status == "not_attempted"
            ),
        )
        object.__setattr__(self, "bounded_output", output)


@dataclass(frozen=True)
class WorkerResultReceipt:
    action: InertWorkerLaunchAction
    supplied_result: WorkerResultInput
    status: str
    result_digest: str
    result_recorded: bool = True
    provider_output_trusted: bool = False
    externally_verified: bool = False
    execution_performed_by_this_module: bool = False

    def __post_init__(self):
        if not isinstance(
            self.action, InertWorkerLaunchAction
        ) or not isinstance(self.supplied_result, WorkerResultInput):
            raise WorkerActionError("result source is invalid")
        source = self.supplied_result
        if (
            source.action_digest != self.action.action_digest
            or source.attempt_id != self.action.attempt_id
            or source.worker_descriptor_digest
            != self.action.worker_descriptor_digest
        ):
            raise WorkerActionError("result source binding mismatch")
        if self.status != source.reported_status:
            raise WorkerActionError("reported status binding mismatch")
        if self.result_recorded is not True or any(
            value is not False for value in (
                self.provider_output_trusted, self.externally_verified,
                self.execution_performed_by_this_module,
            )
        ):
            raise WorkerActionError("receipt overstates reported evidence")
        if self.result_digest != hashlib.sha256(self._payload()).hexdigest():
            raise WorkerActionError("result digest mismatch")
        if len(self.canonical_bytes()) > MAX_RESULT_BYTES:
            raise WorkerActionError("worker result exceeds byte bound")

    def _body(self):
        source = self.supplied_result
        return {
            "action_digest": self.action.action_digest,
            "attempt_id": self.action.attempt_id,
            "bounded_output": source.bounded_output,
            "execution_performed_by_this_module": False,
            "externally_verified": False,
            "provider_output_trusted": False,
            "receipt_id": source.receipt_id,
            "result_recorded": True,
            "status": self.status,
            "worker_descriptor_digest": self.action.worker_descriptor_digest,
        }

    def _payload(self):
        return _canonical(self._body())

    def canonical_bytes(self):
        value = self._body()
        value["result_digest"] = self.result_digest
        return _canonical(value)


def record_worker_result(action, supplied_result):
    if not isinstance(action, InertWorkerLaunchAction) or not isinstance(
        supplied_result, WorkerResultInput
    ):
        raise WorkerActionError("worker result sources are invalid")
    provisional = object.__new__(WorkerResultReceipt)
    values = {
        "action": action,
        "supplied_result": supplied_result,
        "status": supplied_result.reported_status,
        "result_recorded": True,
        "provider_output_trusted": False,
        "externally_verified": False,
        "execution_performed_by_this_module": False,
    }
    for name, value in values.items():
        object.__setattr__(provisional, name, value)
    digest = hashlib.sha256(provisional._payload()).hexdigest()
    return WorkerResultReceipt(**values, result_digest=digest)
