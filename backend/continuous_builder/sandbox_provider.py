"""Provider-neutral, execution-inert sandbox capability evidence."""

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Optional

from .text_safety import utf8_length


class SandboxProviderError(ValueError):
    """Raised when sandbox-provider claims are malformed or excessive."""


POLICY_VERSION = "cb-sandbox-provider-v1"
BACKEND_TYPES = ("container", "microvm", "os_sandbox")
AVAILABILITY_CLASSES = ("available", "limited", "unavailable")
ISOLATION_CAPABILITIES = (
    "cleanup",
    "cpu_limit",
    "disposable_workspace",
    "filesystem_isolation",
    "memory_limit",
    "network_deny",
    "process_count_limit",
    "process_isolation",
    "read_only_mount",
    "wall_time_limit",
)
MAX_ITEMS = 32
MAX_TEXT_BYTES = 256
MAX_DESCRIPTOR_BYTES = 32 * 1024
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


def _identity(value, name):
    if (
        not isinstance(value, str)
        or _IDENTIFIER.fullmatch(value or "") is None
        or utf8_length(value) > MAX_TEXT_BYTES
    ):
        raise SandboxProviderError(f"{name} is malformed")
    return value


def _identities(values, name, *, allowed=None, required=False):
    if not isinstance(values, (list, tuple)):
        raise SandboxProviderError(f"{name} must be a collection")
    items = tuple(_identity(value, name) for value in values)
    if len(items) > MAX_ITEMS or len(items) != len(set(items)):
        raise SandboxProviderError(f"{name} is duplicate or excessive")
    if required and not items:
        raise SandboxProviderError(f"{name} is required")
    if allowed is not None and not set(items).issubset(allowed):
        raise SandboxProviderError(f"{name} contains unsupported values")
    return tuple(sorted(items))


def _canonical(value):
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")


@dataclass(frozen=True)
class SandboxProviderDescriptor:
    provider_id: str
    backend_type: str
    isolation_capabilities: tuple
    supported_platforms: tuple
    supported_runtimes: tuple
    availability_class: str
    policy_version: str = POLICY_VERSION
    execution_authorized: bool = False
    credentials_authorized: bool = False
    network_authorized: bool = False
    host_filesystem_write_authorized: bool = False
    github_authorized: bool = False
    approval_granted: bool = False
    queue_transition_authorized: bool = False
    scope_growth_allowed: bool = False
    budget_growth_allowed: bool = False
    runtime_isolation_verified: bool = False

    def __post_init__(self):
        object.__setattr__(
            self, "provider_id", _identity(self.provider_id, "provider ID")
        )
        if self.backend_type not in BACKEND_TYPES:
            raise SandboxProviderError("backend type is unsupported")
        object.__setattr__(
            self,
            "isolation_capabilities",
            _identities(
                self.isolation_capabilities,
                "isolation capabilities",
                allowed=set(ISOLATION_CAPABILITIES),
                required=True,
            ),
        )
        object.__setattr__(
            self,
            "supported_platforms",
            _identities(
                self.supported_platforms, "supported platforms", required=True
            ),
        )
        object.__setattr__(
            self,
            "supported_runtimes",
            _identities(
                self.supported_runtimes, "supported runtimes", required=True
            ),
        )
        if self.availability_class not in AVAILABILITY_CLASSES:
            raise SandboxProviderError("availability class is unsupported")
        if self.policy_version != POLICY_VERSION:
            raise SandboxProviderError(
                "provider policy version is unsupported"
            )
        authority_flags = (
            self.execution_authorized,
            self.credentials_authorized,
            self.network_authorized,
            self.host_filesystem_write_authorized,
            self.github_authorized,
            self.approval_granted,
            self.queue_transition_authorized,
            self.scope_growth_allowed,
            self.budget_growth_allowed,
            self.runtime_isolation_verified,
        )
        if any(value is not False for value in authority_flags):
            raise SandboxProviderError(
                "sandbox-provider metadata cannot grant authority"
            )
        if len(self.canonical_bytes()) > MAX_DESCRIPTOR_BYTES:
            raise SandboxProviderError(
                "provider descriptor exceeds byte bound"
            )

    @property
    def descriptor_sha256(self):
        return hashlib.sha256(self.canonical_bytes()).hexdigest()

    def to_dict(self):
        return {
            "approval_granted": False,
            "availability_class": self.availability_class,
            "backend_type": self.backend_type,
            "budget_growth_allowed": False,
            "credentials_authorized": False,
            "execution_authorized": False,
            "github_authorized": False,
            "host_filesystem_write_authorized": False,
            "isolation_capabilities": list(self.isolation_capabilities),
            "network_authorized": False,
            "policy_version": self.policy_version,
            "provider_id": self.provider_id,
            "queue_transition_authorized": False,
            "runtime_isolation_verified": False,
            "scope_growth_allowed": False,
            "supported_platforms": list(self.supported_platforms),
            "supported_runtimes": list(self.supported_runtimes),
        }

    def canonical_bytes(self):
        return _canonical(self.to_dict())


@dataclass(frozen=True)
class SandboxProviderRequirement:
    required_capabilities: tuple
    required_platform: str
    required_runtime: str
    allowed_backend_types: tuple
    policy_version: str = POLICY_VERSION

    def __post_init__(self):
        object.__setattr__(
            self,
            "required_capabilities",
            _identities(
                self.required_capabilities,
                "required capabilities",
                allowed=set(ISOLATION_CAPABILITIES),
                required=True,
            ),
        )
        for name in ("required_platform", "required_runtime"):
            object.__setattr__(
                self, name, _identity(getattr(self, name), name)
            )
        object.__setattr__(
            self,
            "allowed_backend_types",
            _identities(
                self.allowed_backend_types,
                "allowed backend types",
                allowed=set(BACKEND_TYPES),
                required=True,
            ),
        )
        if self.policy_version != POLICY_VERSION:
            raise SandboxProviderError(
                "provider policy version is unsupported"
            )


@dataclass(frozen=True)
class SandboxPolicyProbe:
    status: str
    requirement: SandboxProviderRequirement
    provider: Optional[SandboxProviderDescriptor]
    missing_capabilities: tuple
    considered_descriptor_digests: tuple
    provider_claims_only: bool = True
    runtime_isolation_verified: bool = False
    launch_authorized: bool = False
    execution_performed: bool = False

    def __post_init__(self):
        if self.status not in ("preflight_compatible", "preflight_blocked"):
            raise SandboxProviderError("probe status is unsupported")
        if not isinstance(self.requirement, SandboxProviderRequirement):
            raise SandboxProviderError("provider requirement is invalid")
        if self.status == "preflight_compatible" and not isinstance(
            self.provider, SandboxProviderDescriptor
        ):
            raise SandboxProviderError("compatible probe requires a provider")
        if self.status == "preflight_blocked" and self.provider is not None:
            raise SandboxProviderError(
                "blocked probe cannot select a provider"
            )
        object.__setattr__(
            self,
            "missing_capabilities",
            _identities(
                self.missing_capabilities,
                "missing capabilities",
                allowed=set(ISOLATION_CAPABILITIES),
            ),
        )
        object.__setattr__(
            self,
            "considered_descriptor_digests",
            _identities(
                self.considered_descriptor_digests, "descriptor digests"
            ),
        )
        if self.status == "preflight_compatible":
            compatible = (
                self.provider.availability_class != "unavailable"
                and self.provider.backend_type
                in self.requirement.allowed_backend_types
                and self.requirement.required_platform
                in self.provider.supported_platforms
                and self.requirement.required_runtime
                in self.provider.supported_runtimes
                and set(self.requirement.required_capabilities).issubset(
                    self.provider.isolation_capabilities
                )
                and not self.missing_capabilities
                and self.provider.descriptor_sha256
                in self.considered_descriptor_digests
            )
            if not compatible:
                raise SandboxProviderError(
                    "compatible probe is not supported by provider claims"
                )
        if self.provider_claims_only is not True or any(
            value is not False
            for value in (
                self.runtime_isolation_verified,
                self.launch_authorized,
                self.execution_performed,
            )
        ):
            raise SandboxProviderError("policy probe overstates authority")


def probe_sandbox_providers(requirement, descriptors):
    """Deterministically evaluate descriptive claims without launching."""
    if not isinstance(requirement, SandboxProviderRequirement):
        raise SandboxProviderError("provider requirement is invalid")
    if not isinstance(descriptors, (list, tuple)):
        raise SandboxProviderError("provider descriptors must be a collection")
    descriptors = tuple(descriptors)
    if len(descriptors) > MAX_ITEMS or any(
        not isinstance(item, SandboxProviderDescriptor)
        for item in descriptors
    ):
        raise SandboxProviderError("provider descriptors are invalid")
    identities = tuple(item.provider_id for item in descriptors)
    if len(identities) != len(set(identities)):
        raise SandboxProviderError("provider identity is duplicate")
    considered = tuple(sorted(
        item.descriptor_sha256 for item in descriptors
    ))
    compatible = sorted(
        (
            item
            for item in descriptors
            if item.availability_class != "unavailable"
            and item.backend_type in requirement.allowed_backend_types
            and requirement.required_platform in item.supported_platforms
            and requirement.required_runtime in item.supported_runtimes
            and set(requirement.required_capabilities).issubset(
                item.isolation_capabilities
            )
        ),
        key=lambda item: (
            item.provider_id, item.backend_type, item.descriptor_sha256
        ),
    )
    if compatible:
        return SandboxPolicyProbe(
            "preflight_compatible", requirement, compatible[0], (), considered
        )
    available_capabilities = set().union(*(
        set(item.isolation_capabilities) for item in descriptors
    )) if descriptors else set()
    missing = tuple(sorted(
        set(requirement.required_capabilities) - available_capabilities
    ))
    return SandboxPolicyProbe(
        "preflight_blocked", requirement, None, missing, considered
    )
