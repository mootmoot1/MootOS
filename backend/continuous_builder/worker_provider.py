"""Provider-neutral, execution-inert worker descriptions and matching."""

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Optional

from .text_safety import utf8_length


class WorkerProviderError(ValueError):
    """Raised when descriptive worker facts cannot be safely represented."""


POLICY_VERSION = "cb-worker-match-v1"
AVAILABILITY_CLASSES = ("available", "limited", "unavailable")
MAX_TEXT_BYTES = 256
MAX_ITEMS = 64
MAX_DESCRIPTOR_BYTES = 32 * 1024
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


def _identity(value, name):
    if (
        not isinstance(value, str) or not value
        or utf8_length(value) > MAX_TEXT_BYTES
        or _IDENTIFIER.fullmatch(value) is None
    ):
        raise WorkerProviderError(f"{name} is malformed")
    return value


def _text(value, name):
    if (
        not isinstance(value, str) or not value.strip()
        or utf8_length(value) > MAX_TEXT_BYTES
        or any(ord(character) < 32 or ord(character) == 127
               for character in value)
    ):
        raise WorkerProviderError(f"{name} is malformed")
    return value.strip()


def _identities(values, name, *, required=False):
    if not isinstance(values, (list, tuple)):
        raise WorkerProviderError(f"{name} must be a collection")
    values = tuple(_identity(value, name) for value in values)
    if len(values) > MAX_ITEMS or len(values) != len(set(values)):
        raise WorkerProviderError(f"{name} is duplicate or excessive")
    if required and not values:
        raise WorkerProviderError(f"{name} is required")
    return tuple(sorted(values))


@dataclass(frozen=True)
class WorkerDescriptor:
    provider_id: str
    worker_id: str
    model_id: str
    supported_task_classes: tuple
    supported_capabilities: tuple
    max_context_bytes: int
    max_output_bytes: int
    availability_class: str
    policy_version: str = POLICY_VERSION
    execution_authorized: bool = False
    authenticated: bool = False
    credentials_available: bool = False
    scope_growth_allowed: bool = False
    budget_growth_allowed: bool = False
    queue_transition_allowed: bool = False
    approval_granted: bool = False

    def __post_init__(self):
        for name in ("provider_id", "worker_id"):
            object.__setattr__(
                self, name, _identity(getattr(self, name), name)
            )
        object.__setattr__(self, "model_id", _text(self.model_id, "model_id"))
        object.__setattr__(self, "supported_task_classes", _identities(
            self.supported_task_classes, "task classes", required=True,
        ))
        object.__setattr__(self, "supported_capabilities", _identities(
            self.supported_capabilities, "capabilities", required=True,
        ))
        for name in ("max_context_bytes", "max_output_bytes"):
            value = getattr(self, name)
            if type(value) is not int or not (
                1024 <= value <= 100 * 1024 * 1024
            ):
                raise WorkerProviderError(f"{name} is outside its bound")
        if self.availability_class not in AVAILABILITY_CLASSES:
            raise WorkerProviderError("availability class is unsupported")
        if self.policy_version != POLICY_VERSION:
            raise WorkerProviderError("matching policy version is unsupported")
        authority = (
            self.execution_authorized, self.authenticated,
            self.credentials_available, self.scope_growth_allowed,
            self.budget_growth_allowed, self.queue_transition_allowed,
            self.approval_granted,
        )
        if any(value is not False for value in authority):
            raise WorkerProviderError(
                "provider metadata cannot grant authority"
            )
        if len(self.canonical_bytes()) > MAX_DESCRIPTOR_BYTES:
            raise WorkerProviderError("worker descriptor exceeds byte bound")

    @property
    def descriptor_sha256(self):
        return hashlib.sha256(self.canonical_bytes()).hexdigest()

    def to_dict(self):
        return {
            "approval_granted": False,
            "authenticated": False,
            "availability_class": self.availability_class,
            "budget_growth_allowed": False,
            "credentials_available": False,
            "execution_authorized": False,
            "max_context_bytes": self.max_context_bytes,
            "max_output_bytes": self.max_output_bytes,
            "model_id": self.model_id,
            "policy_version": self.policy_version,
            "provider_id": self.provider_id,
            "queue_transition_allowed": False,
            "scope_growth_allowed": False,
            "supported_capabilities": list(self.supported_capabilities),
            "supported_task_classes": list(self.supported_task_classes),
            "worker_id": self.worker_id,
        }

    def canonical_bytes(self):
        return json.dumps(
            self.to_dict(), ensure_ascii=False, sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")


@dataclass(frozen=True)
class WorkerRequirement:
    task_class: str
    required_capabilities: tuple
    required_context_bytes: int
    required_output_bytes: int

    def __post_init__(self):
        object.__setattr__(self, "task_class", _identity(
            self.task_class, "task class",
        ))
        object.__setattr__(self, "required_capabilities", _identities(
            self.required_capabilities, "required capabilities", required=True,
        ))
        for name in ("required_context_bytes", "required_output_bytes"):
            value = getattr(self, name)
            if type(value) is not int or not 1 <= value <= 100 * 1024 * 1024:
                raise WorkerProviderError(f"{name} is outside its bound")


@dataclass(frozen=True)
class WorkerMatch:
    status: str
    requirement: WorkerRequirement
    worker: Optional[WorkerDescriptor]
    considered_descriptor_digests: tuple
    policy_version: str = POLICY_VERSION

    def __post_init__(self):
        if self.status not in ("matched", "not_matched"):
            raise WorkerProviderError("match status is unsupported")
        if not isinstance(self.requirement, WorkerRequirement):
            raise WorkerProviderError("worker requirement is invalid")
        if self.status == "matched" and not isinstance(
            self.worker, WorkerDescriptor
        ):
            raise WorkerProviderError("matched result requires a worker")
        if self.status == "not_matched" and self.worker is not None:
            raise WorkerProviderError(
                "unmatched result cannot contain a worker"
            )
        object.__setattr__(self, "considered_descriptor_digests", _identities(
            self.considered_descriptor_digests, "descriptor digests",
        ))
        if self.policy_version != POLICY_VERSION:
            raise WorkerProviderError("matching policy version is unsupported")


def match_worker(requirement, descriptors):
    """Choose the lexically first exact-capability-compatible worker."""
    if not isinstance(requirement, WorkerRequirement):
        raise WorkerProviderError("worker requirement is invalid")
    if not isinstance(descriptors, (list, tuple)):
        raise WorkerProviderError("worker descriptors must be a collection")
    descriptors = tuple(descriptors)
    if len(descriptors) > MAX_ITEMS or any(
        not isinstance(item, WorkerDescriptor) for item in descriptors
    ):
        raise WorkerProviderError(
            "worker descriptors are invalid or excessive"
        )
    identities = tuple(
        (item.provider_id, item.worker_id) for item in descriptors
    )
    if len(identities) != len(set(identities)):
        raise WorkerProviderError("worker descriptor identity is duplicate")
    considered = tuple(sorted(item.descriptor_sha256 for item in descriptors))
    compatible = sorted(
        (
            item for item in descriptors
            if item.availability_class != "unavailable"
            and requirement.task_class in item.supported_task_classes
            and set(requirement.required_capabilities).issubset(
                item.supported_capabilities
            )
            and item.max_context_bytes >= requirement.required_context_bytes
            and item.max_output_bytes >= requirement.required_output_bytes
        ),
        key=lambda item: (item.provider_id, item.worker_id, item.model_id),
    )
    return WorkerMatch(
        "matched" if compatible else "not_matched",
        requirement,
        compatible[0] if compatible else None,
        considered,
    )
