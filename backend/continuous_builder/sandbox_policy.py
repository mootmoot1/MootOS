"""Deny-by-default, execution-inert Continuous Builder sandbox policy."""

import hashlib
import json
import re
from dataclasses import dataclass

from .sandbox_provider import (
    ISOLATION_CAPABILITIES,
    SandboxProviderDescriptor,
    SandboxProviderRequirement,
    probe_sandbox_providers,
)
from .sandbox_repository import DisposableRepositoryPlan
from .text_safety import utf8_length


class SandboxPolicyError(ValueError):
    """Raised when inert containment policy cannot be proven exactly."""


POLICY_VERSION = "cb-sandbox-policy-v1"
NETWORK_MODES = ("deny_all",)
CREDENTIAL_MODES = ("none",)
MOUNT_KINDS = ("disposable_workspace", "read_only_source")
MOUNT_TARGETS = ("workspace_root", "source_root")
MOUNT_MODES = ("read_write", "read_only")
MAX_ITEMS = 64
MAX_POLICY_BYTES = 64 * 1024
MAX_RECEIPT_BYTES = 64 * 1024
_IDENTITY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$")
_ENV_NAME = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")
_SENSITIVE_ENV = re.compile(
    r"(?i)(token|key|password|secret|auth|credential|cookie|session|ssh|aws|"
    r"github|gitlab|azure|gcp)"
)


def _identity(value, name):
    if (
        not isinstance(value, str)
        or _IDENTITY.fullmatch(value or "") is None
        or utf8_length(value) > 256
    ):
        raise SandboxPolicyError(f"{name} is malformed")
    return value


def _canonical(value):
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")


def _identities(values, name, *, required=False):
    if not isinstance(values, (list, tuple)):
        raise SandboxPolicyError(f"{name} must be a collection")
    values = tuple(_identity(value, name) for value in values)
    if len(values) > MAX_ITEMS or len(values) != len(set(values)):
        raise SandboxPolicyError(f"{name} is duplicate or excessive")
    if required and not values:
        raise SandboxPolicyError(f"{name} is required")
    return tuple(sorted(values))


@dataclass(frozen=True)
class SandboxMountPolicy:
    mount_kind: str
    source_identity: str
    target: str
    mode: str

    def __post_init__(self):
        if self.mount_kind not in MOUNT_KINDS:
            raise SandboxPolicyError("mount kind is unsupported")
        object.__setattr__(
            self,
            "source_identity",
            _identity(self.source_identity, "mount source identity"),
        )
        if self.target not in MOUNT_TARGETS or self.mode not in MOUNT_MODES:
            raise SandboxPolicyError("mount target or mode is unsupported")
        expected = {
            "disposable_workspace": ("workspace_root", "read_write"),
            "read_only_source": ("source_root", "read_only"),
        }[self.mount_kind]
        if (self.target, self.mode) != expected:
            raise SandboxPolicyError("mount semantics are inconsistent")

    def to_dict(self):
        return {
            "mode": self.mode,
            "mount_kind": self.mount_kind,
            "source_identity": self.source_identity,
            "target": self.target,
        }


@dataclass(frozen=True)
class SandboxResourceLimits:
    max_wall_seconds: int
    max_cpu_millis: int
    max_memory_bytes: int
    max_output_bytes: int
    max_log_bytes: int
    max_processes: int
    max_files: int
    max_file_bytes: int

    def __post_init__(self):
        bounds = {
            "max_wall_seconds": (1, 3600),
            "max_cpu_millis": (100, 16000),
            "max_memory_bytes": (64 * 1024 * 1024, 16 * 1024 * 1024 * 1024),
            "max_output_bytes": (1024, 10 * 1024 * 1024),
            "max_log_bytes": (1024, 10 * 1024 * 1024),
            "max_processes": (1, 128),
            "max_files": (1, 100000),
            "max_file_bytes": (1024, 64 * 1024 * 1024),
        }
        for name, (minimum, maximum) in bounds.items():
            value = getattr(self, name)
            if type(value) is not int or not minimum <= value <= maximum:
                raise SandboxPolicyError(f"{name} is outside its hard bound")

    def to_dict(self):
        return {
            "max_cpu_millis": self.max_cpu_millis,
            "max_file_bytes": self.max_file_bytes,
            "max_files": self.max_files,
            "max_log_bytes": self.max_log_bytes,
            "max_memory_bytes": self.max_memory_bytes,
            "max_output_bytes": self.max_output_bytes,
            "max_processes": self.max_processes,
            "max_wall_seconds": self.max_wall_seconds,
        }


def _environment_names(values):
    if not isinstance(values, (list, tuple)):
        raise SandboxPolicyError(
            "environment allowlist must be a collection"
        )
    values = tuple(values)
    if len(values) > MAX_ITEMS or len(values) != len(set(values)):
        raise SandboxPolicyError(
            "environment allowlist is duplicate or excessive"
        )
    for value in values:
        if (
            not isinstance(value, str)
            or _ENV_NAME.fullmatch(value) is None
            or _SENSITIVE_ENV.search(value)
        ):
            raise SandboxPolicyError(
                "environment allowlist contains an unsafe name"
            )
    return tuple(sorted(values))


def _mounts(values, workspace_id, source_id):
    if not isinstance(values, (list, tuple)):
        raise SandboxPolicyError("mount policies must be a collection")
    values = tuple(values)
    if len(values) != 2 or any(
        not isinstance(value, SandboxMountPolicy) for value in values
    ):
        raise SandboxPolicyError(
            "exactly two policy-owned mounts are required"
        )
    expected = (
        SandboxMountPolicy(
            "disposable_workspace", workspace_id,
            "workspace_root", "read_write",
        ),
        SandboxMountPolicy(
            "read_only_source", source_id, "source_root", "read_only"
        ),
    )
    ordered = tuple(sorted(values, key=lambda value: value.mount_kind))
    if ordered != tuple(sorted(expected, key=lambda value: value.mount_kind)):
        raise SandboxPolicyError("mount policy does not bind reconstruction")
    return ordered


@dataclass(frozen=True)
class SandboxPolicy:
    repository_plan: DisposableRepositoryPlan
    policy_id: str
    repository_plan_digest: str
    writable_workspace_id: str
    read_only_source_ids: tuple
    mounts: tuple
    network_mode: str
    credential_mode: str
    credential_reference_ids: tuple
    environment_allowlist: tuple
    resources: SandboxResourceLimits
    required_platform: str
    required_runtime: str
    allowed_backend_types: tuple
    policy_sha256: str
    policy_version: str = POLICY_VERSION
    inherit_host_environment: bool = False
    host_home_mounted: bool = False
    host_repository_writable: bool = False
    arbitrary_absolute_mounts: bool = False
    device_mounts: bool = False
    container_socket_mounted: bool = False
    ssh_agent_socket_mounted: bool = False
    credential_directories_mounted: bool = False
    host_temp_reused: bool = False
    launch_authorized: bool = False
    queue_transition_authorized: bool = False
    approval_granted: bool = False
    budget_growth_allowed: bool = False

    def __post_init__(self):
        if not isinstance(self.repository_plan, DisposableRepositoryPlan):
            raise SandboxPolicyError("repository plan is invalid")
        _identity(self.policy_id, "policy ID")
        _identity(self.writable_workspace_id, "writable workspace ID")
        if not re.fullmatch(
            r"[0-9a-f]{64}", self.repository_plan_digest or ""
        ):
            raise SandboxPolicyError("repository plan digest is malformed")
        if self.repository_plan_digest != self.repository_plan.plan_sha256:
            raise SandboxPolicyError("repository plan digest mismatch")
        if (
            self.writable_workspace_id
            != self.repository_plan.disposable_workspace_id
            or self.repository_plan.source_evidence.repository_id
            not in self.read_only_source_ids
        ):
            raise SandboxPolicyError("policy does not bind reconstruction")
        sources = _identities(
            self.read_only_source_ids, "read-only source IDs", required=True
        )
        object.__setattr__(self, "read_only_source_ids", sources)
        if len(sources) != 1:
            raise SandboxPolicyError(
                "exactly one read-only source is required"
            )
        object.__setattr__(
            self,
            "mounts",
            _mounts(
                self.mounts, self.writable_workspace_id, sources[0]
            ),
        )
        if self.network_mode not in NETWORK_MODES:
            raise SandboxPolicyError("Phase 4A network mode must deny all")
        if self.credential_mode not in CREDENTIAL_MODES:
            raise SandboxPolicyError("Phase 4A credential mode must be none")
        references = _identities(
            self.credential_reference_ids, "credential reference IDs"
        )
        if references:
            raise SandboxPolicyError(
                "Phase 4A cannot carry credential references"
            )
        object.__setattr__(self, "credential_reference_ids", references)
        object.__setattr__(
            self,
            "environment_allowlist",
            _environment_names(self.environment_allowlist),
        )
        if not isinstance(self.resources, SandboxResourceLimits):
            raise SandboxPolicyError("resource limits are invalid")
        request = self.repository_plan.worker_request
        if self.resources.max_wall_seconds > (
            request.slice_blueprint.budget.max_minutes * 60
        ) or self.resources.max_output_bytes > min(
            request.slice_blueprint.budget.max_output_bytes,
            request.job.budgets.max_bytes_per_diff,
        ):
            raise SandboxPolicyError(
                "containment resources grow request budget"
            )
        for name in ("required_platform", "required_runtime"):
            object.__setattr__(
                self, name, _identity(getattr(self, name), name)
            )
        backends = _identities(
            self.allowed_backend_types, "allowed backend types", required=True
        )
        if not set(backends).issubset({"container", "microvm", "os_sandbox"}):
            raise SandboxPolicyError("allowed backend type is unsupported")
        object.__setattr__(self, "allowed_backend_types", backends)
        if self.policy_version != POLICY_VERSION:
            raise SandboxPolicyError("sandbox policy version is unsupported")
        prohibited = (
            self.inherit_host_environment,
            self.host_home_mounted,
            self.host_repository_writable,
            self.arbitrary_absolute_mounts,
            self.device_mounts,
            self.container_socket_mounted,
            self.ssh_agent_socket_mounted,
            self.credential_directories_mounted,
            self.host_temp_reused,
            self.launch_authorized,
            self.queue_transition_authorized,
            self.approval_granted,
            self.budget_growth_allowed,
        )
        if any(value is not False for value in prohibited):
            raise SandboxPolicyError(
                "sandbox policy grants forbidden authority"
            )
        if self.policy_sha256 != hashlib.sha256(self._payload()).hexdigest():
            raise SandboxPolicyError("sandbox policy digest mismatch")
        if len(self.canonical_bytes()) > MAX_POLICY_BYTES:
            raise SandboxPolicyError("sandbox policy exceeds byte bound")

    def _body(self):
        return {
            "allowed_backend_types": list(self.allowed_backend_types),
            "approval_granted": False,
            "arbitrary_absolute_mounts": False,
            "budget_growth_allowed": False,
            "container_socket_mounted": False,
            "credential_directories_mounted": False,
            "credential_mode": self.credential_mode,
            "credential_reference_ids": [],
            "device_mounts": False,
            "environment_allowlist": list(self.environment_allowlist),
            "host_home_mounted": False,
            "host_repository_writable": False,
            "host_temp_reused": False,
            "inherit_host_environment": False,
            "launch_authorized": False,
            "mounts": [value.to_dict() for value in self.mounts],
            "network_mode": self.network_mode,
            "policy_id": self.policy_id,
            "policy_version": self.policy_version,
            "queue_transition_authorized": False,
            "read_only_source_ids": list(self.read_only_source_ids),
            "repository_plan_digest": self.repository_plan_digest,
            "required_platform": self.required_platform,
            "required_runtime": self.required_runtime,
            "resources": self.resources.to_dict(),
            "ssh_agent_socket_mounted": False,
            "writable_workspace_id": self.writable_workspace_id,
        }

    def _payload(self):
        return _canonical(self._body())

    def canonical_bytes(self):
        value = self._body()
        value["policy_sha256"] = self.policy_sha256
        return _canonical(value)


def create_sandbox_policy(
    policy_id,
    repository_plan,
    resources,
    required_platform,
    required_runtime,
    allowed_backend_types=("container", "microvm"),
    environment_allowlist=("LANG", "LC_ALL", "PYTHONHASHSEED"),
):
    if not isinstance(repository_plan, DisposableRepositoryPlan):
        raise SandboxPolicyError("repository plan is invalid")
    workspace = repository_plan.disposable_workspace_id
    source = repository_plan.source_evidence.repository_id
    environment_allowlist = _environment_names(environment_allowlist)
    allowed_backend_types = _identities(
        allowed_backend_types, "allowed backend types", required=True
    )
    values = {
        "repository_plan": repository_plan,
        "policy_id": policy_id,
        "repository_plan_digest": repository_plan.plan_sha256,
        "writable_workspace_id": workspace,
        "read_only_source_ids": (source,),
        "mounts": (
            SandboxMountPolicy(
                "disposable_workspace", workspace,
                "workspace_root", "read_write",
            ),
            SandboxMountPolicy(
                "read_only_source", source, "source_root", "read_only",
            ),
        ),
        "network_mode": "deny_all",
        "credential_mode": "none",
        "credential_reference_ids": (),
        "environment_allowlist": environment_allowlist,
        "resources": resources,
        "required_platform": required_platform,
        "required_runtime": required_runtime,
        "allowed_backend_types": allowed_backend_types,
        "policy_version": POLICY_VERSION,
        "inherit_host_environment": False,
        "host_home_mounted": False,
        "host_repository_writable": False,
        "arbitrary_absolute_mounts": False,
        "device_mounts": False,
        "container_socket_mounted": False,
        "ssh_agent_socket_mounted": False,
        "credential_directories_mounted": False,
        "host_temp_reused": False,
        "launch_authorized": False,
        "queue_transition_authorized": False,
        "approval_granted": False,
        "budget_growth_allowed": False,
    }
    provisional = object.__new__(SandboxPolicy)
    for name, value in values.items():
        object.__setattr__(provisional, name, value)
    digest = hashlib.sha256(provisional._payload()).hexdigest()
    return SandboxPolicy(**values, policy_sha256=digest)


@dataclass(frozen=True)
class ContainmentPreflightReceipt:
    provider_descriptor: SandboxProviderDescriptor
    repository_plan: DisposableRepositoryPlan
    policy: SandboxPolicy
    status: str
    provider_claims_compatible: bool
    missing_provider_capabilities: tuple
    provider_descriptor_digest: str
    repository_plan_digest: str
    policy_digest: str
    receipt_sha256: str
    policy_structurally_valid: bool = True
    reconstruction_contract_valid: bool = True
    provider_claims_only: bool = True
    runtime_isolation_verified: bool = False
    safe_to_execute: bool = False
    launch_authorized: bool = False
    execution_performed: bool = False

    def __post_init__(self):
        if not isinstance(self.provider_descriptor, SandboxProviderDescriptor):
            raise SandboxPolicyError("provider descriptor is invalid")
        if not isinstance(self.repository_plan, DisposableRepositoryPlan):
            raise SandboxPolicyError("repository plan is invalid")
        if not isinstance(self.policy, SandboxPolicy):
            raise SandboxPolicyError("sandbox policy is invalid")
        if (
            self.policy.repository_plan_digest
            != self.repository_plan.plan_sha256
            or self.policy.writable_workspace_id
            != self.repository_plan.disposable_workspace_id
            or self.repository_plan.source_evidence.repository_id
            not in self.policy.read_only_source_ids
        ):
            raise SandboxPolicyError("containment source binding mismatch")
        request = self.repository_plan.worker_request
        if self.policy.resources.max_wall_seconds > (
            request.slice_blueprint.budget.max_minutes * 60
        ) or self.policy.resources.max_output_bytes > min(
            request.slice_blueprint.budget.max_output_bytes,
            request.job.budgets.max_bytes_per_diff,
        ):
            raise SandboxPolicyError(
                "containment resources grow request budget"
            )
        requirement = _provider_requirement(self.policy)
        probe = probe_sandbox_providers(
            requirement, (self.provider_descriptor,)
        )
        compatible = probe.status == "preflight_compatible"
        missing = tuple(probe.missing_capabilities)
        if self.provider_claims_compatible != compatible or (
            tuple(self.missing_provider_capabilities) != missing
        ):
            raise SandboxPolicyError("provider compatibility result is forged")
        expected_status = (
            "preflight_compatible" if compatible else "preflight_blocked"
        )
        if self.status != expected_status:
            raise SandboxPolicyError("containment preflight status is forged")
        if type(self.provider_claims_compatible) is not bool:
            raise SandboxPolicyError(
                "provider compatibility flag must be boolean"
            )
        if (
            self.provider_descriptor_digest
            != self.provider_descriptor.descriptor_sha256
            or self.repository_plan_digest != self.repository_plan.plan_sha256
            or self.policy_digest != self.policy.policy_sha256
        ):
            raise SandboxPolicyError("containment digest binding mismatch")
        required_true = (
            self.policy_structurally_valid,
            self.reconstruction_contract_valid,
            self.provider_claims_only,
        )
        required_false = (
            self.runtime_isolation_verified,
            self.safe_to_execute,
            self.launch_authorized,
            self.execution_performed,
        )
        if any(value is not True for value in required_true) or any(
            value is not False for value in required_false
        ):
            raise SandboxPolicyError(
                "containment preflight overstates runtime authority"
            )
        if self.receipt_sha256 != hashlib.sha256(self._payload()).hexdigest():
            raise SandboxPolicyError("containment receipt digest mismatch")
        if len(self.canonical_bytes()) > MAX_RECEIPT_BYTES:
            raise SandboxPolicyError("containment receipt exceeds byte bound")
        object.__setattr__(
            self,
            "missing_provider_capabilities",
            tuple(self.missing_provider_capabilities),
        )

    def _body(self):
        return {
            "execution_performed": False,
            "launch_authorized": False,
            "missing_provider_capabilities": list(
                self.missing_provider_capabilities
            ),
            "policy_digest": self.policy_digest,
            "policy_structurally_valid": True,
            "provider_claims_compatible": self.provider_claims_compatible,
            "provider_claims_only": True,
            "provider_descriptor_digest": self.provider_descriptor_digest,
            "reconstruction_contract_valid": True,
            "repository_plan_digest": self.repository_plan_digest,
            "runtime_isolation_verified": False,
            "safe_to_execute": False,
            "status": self.status,
        }

    def _payload(self):
        return _canonical(self._body())

    def canonical_bytes(self):
        value = self._body()
        value["receipt_sha256"] = self.receipt_sha256
        return _canonical(value)


def _provider_requirement(policy):
    return SandboxProviderRequirement(
        ISOLATION_CAPABILITIES,
        policy.required_platform,
        policy.required_runtime,
        policy.allowed_backend_types,
    )


def evaluate_containment_preflight(
    provider_descriptor, repository_plan, policy,
):
    """Evaluate inert policy bindings; never claim real runtime isolation."""
    if not isinstance(provider_descriptor, SandboxProviderDescriptor):
        raise SandboxPolicyError("provider descriptor is invalid")
    if not isinstance(repository_plan, DisposableRepositoryPlan):
        raise SandboxPolicyError("repository plan is invalid")
    if not isinstance(policy, SandboxPolicy):
        raise SandboxPolicyError("sandbox policy is invalid")
    probe = probe_sandbox_providers(
        _provider_requirement(policy), (provider_descriptor,)
    )
    compatible = probe.status == "preflight_compatible"
    values = {
        "provider_descriptor": provider_descriptor,
        "repository_plan": repository_plan,
        "policy": policy,
        "status": (
            "preflight_compatible" if compatible else "preflight_blocked"
        ),
        "provider_claims_compatible": compatible,
        "missing_provider_capabilities": probe.missing_capabilities,
        "provider_descriptor_digest": provider_descriptor.descriptor_sha256,
        "repository_plan_digest": repository_plan.plan_sha256,
        "policy_digest": policy.policy_sha256,
        "policy_structurally_valid": True,
        "reconstruction_contract_valid": True,
        "provider_claims_only": True,
        "runtime_isolation_verified": False,
        "safe_to_execute": False,
        "launch_authorized": False,
        "execution_performed": False,
    }
    provisional = object.__new__(ContainmentPreflightReceipt)
    for name, value in values.items():
        object.__setattr__(provisional, name, value)
    digest = hashlib.sha256(provisional._payload()).hexdigest()
    return ContainmentPreflightReceipt(**values, receipt_sha256=digest)
