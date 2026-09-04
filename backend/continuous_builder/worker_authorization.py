"""Inert dispatch authorization bound to one request, attempt, and worker."""

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Optional

from .text_safety import utf8_length
from .worker_provider import WorkerDescriptor
from .worker_request import FrozenWorkerRequest


class WorkerAuthorizationError(ValueError):
    """Raised when dispatch authorization evidence is malformed or forged."""


POLICY_VERSION = "cb-dispatch-authorization-v1"
MAX_AUTHORIZATION_BYTES = 32 * 1024
_IDENTITY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@-]{0,255}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _identity(value, name):
    if (
        not isinstance(value, str) or _IDENTITY.fullmatch(value) is None
        or utf8_length(value) > 256
    ):
        raise WorkerAuthorizationError(f"{name} is malformed")
    return value


def _canonical(value):
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")


@dataclass(frozen=True)
class DispatchAuthorizationInput:
    authorization_id: str
    supplied_authorizer_identity: str
    authenticated: bool
    authentication_evidence_digest: Optional[str]
    authorization_granted: bool
    policy_version: str = POLICY_VERSION

    def __post_init__(self):
        _identity(self.authorization_id, "authorization ID")
        _identity(self.supplied_authorizer_identity, "authorizer identity")
        if type(self.authenticated) is not bool or type(
            self.authorization_granted
        ) is not bool:
            raise WorkerAuthorizationError(
                "authorization flags must be boolean"
            )
        if self.authenticated:
            if (
                not isinstance(self.authentication_evidence_digest, str)
                or _SHA256.fullmatch(
                    self.authentication_evidence_digest
                ) is None
            ):
                raise WorkerAuthorizationError(
                    "authenticated authorizer requires bounded evidence "
                    "identity"
                )
        elif self.authentication_evidence_digest is not None:
            raise WorkerAuthorizationError(
                "unauthenticated identity cannot carry authentication evidence"
            )
        if self.policy_version != POLICY_VERSION:
            raise WorkerAuthorizationError(
                "authorization policy is unsupported"
            )

    def to_dict(self):
        return {
            "authenticated": self.authenticated,
            "authentication_evidence_digest": (
                self.authentication_evidence_digest
            ),
            "authorization_granted": self.authorization_granted,
            "authorization_id": self.authorization_id,
            "policy_version": self.policy_version,
            "supplied_authorizer_identity": self.supplied_authorizer_identity,
        }


@dataclass(frozen=True)
class WorkerDispatchAuthorization:
    request: FrozenWorkerRequest
    worker: WorkerDescriptor
    authorization_input: DispatchAuthorizationInput
    status: str
    blocking_reasons: tuple
    request_digest: str
    attempt_id: str
    worker_descriptor_digest: str
    authorization_digest: str
    action_prepared: bool = False
    launched: bool = False
    execution_performed: bool = False
    credentials_granted: bool = False
    network_granted: bool = False
    github_granted: bool = False
    authentication_independently_verified: bool = False

    def __post_init__(self):
        if not isinstance(self.request, FrozenWorkerRequest):
            raise WorkerAuthorizationError("frozen worker request is invalid")
        if not isinstance(self.worker, WorkerDescriptor):
            raise WorkerAuthorizationError("worker descriptor is invalid")
        if not isinstance(
            self.authorization_input, DispatchAuthorizationInput
        ):
            raise WorkerAuthorizationError("authorization input is invalid")
        if self.status not in ("authorized", "not_authorized"):
            raise WorkerAuthorizationError(
                "authorization status is unsupported"
            )
        reasons = tuple(self.blocking_reasons)
        expected_reasons = _blocking_reasons(
            self.request, self.worker, self.authorization_input,
        )
        if reasons != expected_reasons:
            raise WorkerAuthorizationError("blocking reasons are forged")
        if self.status != ("not_authorized" if reasons else "authorized"):
            raise WorkerAuthorizationError("authorization status is forged")
        if self.request_digest != self.request.request_digest or (
            self.attempt_id != self.request.attempt_id
        ):
            raise WorkerAuthorizationError(
                "request or attempt binding mismatch"
            )
        if self.worker_descriptor_digest != self.worker.descriptor_sha256:
            raise WorkerAuthorizationError("worker binding mismatch")
        authority_claims = (
            self.action_prepared, self.launched, self.execution_performed,
            self.credentials_granted, self.network_granted,
            self.github_granted, self.authentication_independently_verified,
        )
        if any(value is not False for value in authority_claims):
            raise WorkerAuthorizationError(
                "dispatch authorization cannot claim launch or external "
                "authority"
            )
        expected = hashlib.sha256(self._payload()).hexdigest()
        if self.authorization_digest != expected:
            raise WorkerAuthorizationError("authorization digest mismatch")
        if len(self.canonical_bytes()) > MAX_AUTHORIZATION_BYTES:
            raise WorkerAuthorizationError("authorization exceeds byte bound")
        object.__setattr__(self, "blocking_reasons", reasons)

    @property
    def authorized(self):
        return self.status == "authorized"

    def _body(self):
        return {
            "action_prepared": False,
            "attempt_id": self.attempt_id,
            "authentication_independently_verified": False,
            "authorization_input": self.authorization_input.to_dict(),
            "blocking_reasons": list(self.blocking_reasons),
            "credentials_granted": False,
            "execution_performed": False,
            "github_granted": False,
            "launched": False,
            "network_granted": False,
            "request_digest": self.request_digest,
            "status": self.status,
            "worker_descriptor_digest": self.worker_descriptor_digest,
        }

    def _payload(self):
        return _canonical(self._body())

    def canonical_bytes(self):
        value = self._body()
        value["authorization_digest"] = self.authorization_digest
        return _canonical(value)


def _blocking_reasons(request, worker, supplied):
    reasons = []
    if not supplied.authenticated:
        reasons.append("authorizer_not_authenticated")
    if not supplied.authorization_granted:
        reasons.append("authorization_not_granted")
    if supplied.supplied_authorizer_identity in (
        worker.provider_id, worker.worker_id, worker.model_id,
    ):
        reasons.append("worker_or_provider_cannot_self_authorize")
    if request.requested_capability not in worker.supported_capabilities:
        reasons.append("worker_capability_mismatch")
    if worker.availability_class == "unavailable":
        reasons.append("worker_unavailable")
    return tuple(reasons)


def authorize_worker_dispatch(request, worker, authorization_input):
    if not isinstance(request, FrozenWorkerRequest):
        raise WorkerAuthorizationError("frozen worker request is invalid")
    if not isinstance(worker, WorkerDescriptor):
        raise WorkerAuthorizationError("worker descriptor is invalid")
    if not isinstance(authorization_input, DispatchAuthorizationInput):
        raise WorkerAuthorizationError("authorization input is invalid")
    reasons = _blocking_reasons(request, worker, authorization_input)
    provisional = object.__new__(WorkerDispatchAuthorization)
    values = {
        "request": request,
        "worker": worker,
        "authorization_input": authorization_input,
        "status": "not_authorized" if reasons else "authorized",
        "blocking_reasons": reasons,
        "request_digest": request.request_digest,
        "attempt_id": request.attempt_id,
        "worker_descriptor_digest": worker.descriptor_sha256,
        "action_prepared": False,
        "launched": False,
        "execution_performed": False,
        "credentials_granted": False,
        "network_granted": False,
        "github_granted": False,
        "authentication_independently_verified": False,
    }
    for name, value in values.items():
        object.__setattr__(provisional, name, value)
    digest = hashlib.sha256(provisional._payload()).hexdigest()
    return WorkerDispatchAuthorization(
        **values, authorization_digest=digest,
    )
