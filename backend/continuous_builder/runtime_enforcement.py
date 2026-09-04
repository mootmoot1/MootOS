"""Inert Docker enforcement, readiness, handle, and cancellation contracts.

The structures record what CB-022 must prove.  They cannot contact Docker,
materialize a repository, launch a process, or authorize launch.
"""

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Optional

from .docker_runtime_contract import (
    PinnedOfflineWorkerImage,
    TrustedDockerRuntimeDescriptor,
)
from .repository_materialization import RepositoryMaterializationReceipt
from .sandbox_policy import ContainmentPreflightReceipt, SandboxPolicy
from .text_safety import utf8_length
from .worker_action import InertWorkerLaunchAction


class RuntimeEnforcementError(ValueError):
    """Raised when a runtime-foundation contract is malformed or forged."""


POLICY_VERSION = "cb-runtime-enforcement-v1"
ENFORCEMENT_CLASSES = (
    "post_run_verified",
    "runtime_hard",
    "supervisor_hard",
    "unsupported",
)
CONTROL_POLICIES = {
    "arbitrary_mounts_denied": ("runtime_hard",),
    "bounded_output_capture": ("supervisor_hard",),
    "cpu_limit": ("runtime_hard",),
    "credential_mounts_denied": ("runtime_hard",),
    "credentials_absent": ("runtime_hard",),
    "device_mounts_denied": ("runtime_hard",),
    "docker_control_absent": ("runtime_hard",),
    "environment_allowlist": ("runtime_hard",),
    "file_count_limit": ("post_run_verified", "supervisor_hard"),
    "file_size_limit": ("post_run_verified", "supervisor_hard"),
    "host_home_denied": ("runtime_hard",),
    "host_ipc_denied": ("runtime_hard",),
    "host_network_denied": ("runtime_hard",),
    "host_pid_denied": ("runtime_hard",),
    "host_repository_write_denied": ("runtime_hard",),
    "memory_limit": ("runtime_hard",),
    "network_disabled": ("runtime_hard",),
    "nested_container_control_denied": ("runtime_hard",),
    "non_privileged": ("runtime_hard",),
    "pid_limit": ("runtime_hard",),
    "read_only_source_mount": ("runtime_hard",),
    "ssh_agent_denied": ("runtime_hard",),
    "wall_time_limit": ("supervisor_hard",),
    "writable_storage_limit": ("runtime_hard", "supervisor_hard"),
    "writable_workspace_isolation": ("runtime_hard",),
}
CONTROL_IDS = tuple(sorted(CONTROL_POLICIES))
LIFECYCLE_STATES = (
    "prepared",
    "launching",
    "running",
    "cancel_requested",
    "cancelled",
    "succeeded",
    "failed",
    "timed_out",
    "crashed",
    "termination_uncertain",
)
MAX_CONTRACT_BYTES = 128 * 1024
_IDENTITY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@-]{0,255}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _identity(value, name):
    if (
        not isinstance(value, str)
        or _IDENTITY.fullmatch(value or "") is None
        or utf8_length(value) > 256
    ):
        raise RuntimeEnforcementError(f"{name} is malformed")
    return value


def _sha256(value, name):
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise RuntimeEnforcementError(f"{name} is malformed")
    return value


def _canonical(value):
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")


@dataclass(frozen=True)
class EnforcementControl:
    control_id: str
    enforcement_class: str

    def __post_init__(self):
        if self.control_id not in CONTROL_POLICIES:
            raise RuntimeEnforcementError("enforcement control is unsupported")
        if self.enforcement_class not in ENFORCEMENT_CLASSES:
            raise RuntimeEnforcementError("enforcement class is unsupported")

    def to_dict(self):
        return {
            "control_id": self.control_id,
            "enforcement_class": self.enforcement_class,
        }


def _controls(values):
    if not isinstance(values, (list, tuple)):
        raise RuntimeEnforcementError(
            "enforcement controls must be a collection"
        )
    values = tuple(values)
    if any(not isinstance(value, EnforcementControl) for value in values):
        raise RuntimeEnforcementError("enforcement controls are invalid")
    identities = tuple(value.control_id for value in values)
    if len(identities) != len(set(identities)) or set(identities) != set(
        CONTROL_IDS
    ):
        raise RuntimeEnforcementError(
            "the exact required enforcement control set is required"
        )
    return tuple(sorted(values, key=lambda value: value.control_id))


def _blocking_controls(controls):
    return tuple(
        control.control_id
        for control in controls
        if control.enforcement_class == "unsupported"
        or control.enforcement_class
        not in CONTROL_POLICIES[control.control_id]
    )


@dataclass(frozen=True)
class DockerEnforcementContract:
    runtime_descriptor: TrustedDockerRuntimeDescriptor
    worker_image: PinnedOfflineWorkerImage
    sandbox_policy: SandboxPolicy
    controls: tuple
    status: str
    blocking_controls: tuple
    runtime_descriptor_digest: str
    image_contract_digest: str
    policy_digest: str
    contract_sha256: str
    policy_version: str = POLICY_VERSION
    requirements_structurally_satisfied: bool = True
    runtime_enforcement_verified: bool = False
    runtime_backend_executed: bool = False
    launch_authorized: bool = False
    execution_performed: bool = False

    def __post_init__(self):
        if not isinstance(
            self.runtime_descriptor, TrustedDockerRuntimeDescriptor
        ) or not isinstance(self.worker_image, PinnedOfflineWorkerImage):
            raise RuntimeEnforcementError(
                "runtime or image contract is invalid"
            )
        if not isinstance(self.sandbox_policy, SandboxPolicy):
            raise RuntimeEnforcementError("sandbox policy is invalid")
        controls = _controls(self.controls)
        object.__setattr__(self, "controls", controls)
        blocking = _blocking_controls(controls)
        if tuple(self.blocking_controls) != blocking:
            raise RuntimeEnforcementError(
                "blocking enforcement controls are forged"
            )
        expected_status = (
            "contract_satisfied" if not blocking else "contract_blocked"
        )
        if self.status != expected_status:
            raise RuntimeEnforcementError(
                "enforcement contract status is forged"
            )
        expected = (
            (
                self.runtime_descriptor_digest,
                self.runtime_descriptor.descriptor_sha256,
            ),
            (self.image_contract_digest, self.worker_image.contract_sha256),
            (self.policy_digest, self.sandbox_policy.policy_sha256),
        )
        if any(actual != wanted for actual, wanted in expected):
            raise RuntimeEnforcementError(
                "enforcement source binding mismatch"
            )
        platform = (
            f"{self.runtime_descriptor.platform}-"
            f"{self.runtime_descriptor.architecture}"
        )
        if (
            platform != self.sandbox_policy.required_platform
            or self.worker_image.platform != self.runtime_descriptor.platform
            or self.worker_image.architecture
            != self.runtime_descriptor.architecture
            or "container" not in self.sandbox_policy.allowed_backend_types
        ):
            raise RuntimeEnforcementError("runtime platform binding mismatch")
        if self.policy_version != POLICY_VERSION:
            raise RuntimeEnforcementError("enforcement policy is unsupported")
        structurally_satisfied = not blocking
        if (
            self.requirements_structurally_satisfied
            is not structurally_satisfied
        ):
            raise RuntimeEnforcementError("structural satisfaction is forged")
        if any(
            value is not False
            for value in (
                self.runtime_enforcement_verified,
                self.runtime_backend_executed,
                self.launch_authorized,
                self.execution_performed,
            )
        ):
            raise RuntimeEnforcementError(
                "enforcement contract fabricates runtime authority"
            )
        _sha256(self.contract_sha256, "enforcement contract digest")
        if self.contract_sha256 != hashlib.sha256(
            self._payload()
        ).hexdigest():
            raise RuntimeEnforcementError(
                "enforcement contract digest mismatch"
            )
        if len(self.canonical_bytes()) > MAX_CONTRACT_BYTES:
            raise RuntimeEnforcementError(
                "enforcement contract exceeds byte bound"
            )

    def _body(self):
        return {
            "blocking_controls": list(self.blocking_controls),
            "controls": [control.to_dict() for control in self.controls],
            "execution_performed": False,
            "image_contract_digest": self.image_contract_digest,
            "launch_authorized": False,
            "policy_digest": self.policy_digest,
            "policy_version": POLICY_VERSION,
            "requirements_structurally_satisfied": (
                self.requirements_structurally_satisfied
            ),
            "runtime_backend_executed": False,
            "runtime_descriptor_digest": self.runtime_descriptor_digest,
            "runtime_enforcement_verified": False,
            "status": self.status,
        }

    def _payload(self):
        return _canonical(self._body())

    def canonical_bytes(self):
        value = self._body()
        value["contract_sha256"] = self.contract_sha256
        return _canonical(value)


def create_docker_enforcement_contract(
    runtime_descriptor, worker_image, sandbox_policy, controls,
):
    controls = _controls(controls)
    blocking = _blocking_controls(controls)
    values = {
        "runtime_descriptor": runtime_descriptor,
        "worker_image": worker_image,
        "sandbox_policy": sandbox_policy,
        "controls": controls,
        "status": "contract_satisfied" if not blocking else "contract_blocked",
        "blocking_controls": blocking,
        "runtime_descriptor_digest": runtime_descriptor.descriptor_sha256,
        "image_contract_digest": worker_image.contract_sha256,
        "policy_digest": sandbox_policy.policy_sha256,
        "requirements_structurally_satisfied": not blocking,
    }
    provisional = object.__new__(DockerEnforcementContract)
    for name, value in values.items():
        object.__setattr__(provisional, name, value)
    return DockerEnforcementContract(
        **values,
        contract_sha256=hashlib.sha256(provisional._payload()).hexdigest(),
    )


def default_docker_enforcement_controls():
    """Return the approved future enforcement strategy, not proof of it."""
    post_run = {"file_count_limit", "file_size_limit"}
    supervisor = {
        "bounded_output_capture",
        "wall_time_limit",
        "writable_storage_limit",
    }
    return tuple(
        EnforcementControl(
            control_id,
            "post_run_verified"
            if control_id in post_run
            else (
                "supervisor_hard"
                if control_id in supervisor
                else "runtime_hard"
            ),
        )
        for control_id in CONTROL_IDS
    )


@dataclass(frozen=True)
class RuntimeFoundationReadinessReceipt:
    action: InertWorkerLaunchAction
    provider_preflight: ContainmentPreflightReceipt
    materialization_receipt: RepositoryMaterializationReceipt
    enforcement_contract: DockerEnforcementContract
    action_digest: str
    authorization_digest: str
    request_digest: str
    attempt_id: str
    worker_provider_id: str
    worker_descriptor_digest: str
    sandbox_provider_id: str
    sandbox_provider_descriptor_digest: str
    policy_digest: str
    reconstruction_plan_digest: str
    materialization_receipt_digest: str
    runtime_descriptor_digest: str
    image_contract_digest: str
    enforcement_contract_digest: str
    pinned_base_sha: str
    receipt_sha256: str
    status: str = "foundation_ready_unverified"
    runtime_contract_valid: bool = True
    materialization_contract_valid: bool = True
    enforcement_requirements_structurally_satisfied: bool = True
    provider_claims_only: bool = True
    runtime_backend_executed: bool = False
    runtime_isolation_verified: bool = False
    materialization_verified: bool = False
    launch_authorized: bool = False
    safe_to_execute: bool = False
    execution_performed: bool = False
    network_authorized: bool = False
    credentials_granted: bool = False
    github_authorized: bool = False
    queue_transition_authorized: bool = False
    publication_authorized: bool = False

    def __post_init__(self):
        if not isinstance(self.action, InertWorkerLaunchAction):
            raise RuntimeEnforcementError("worker action is invalid")
        if not isinstance(
            self.provider_preflight, ContainmentPreflightReceipt
        ):
            raise RuntimeEnforcementError("provider preflight is invalid")
        if not isinstance(
            self.materialization_receipt, RepositoryMaterializationReceipt
        ) or not isinstance(
            self.enforcement_contract, DockerEnforcementContract
        ):
            raise RuntimeEnforcementError("foundation evidence is invalid")
        authorization = self.action.authorization
        request = authorization.request
        preflight = self.provider_preflight
        plan = preflight.repository_plan
        provider = preflight.provider_descriptor
        materialization = self.materialization_receipt
        enforcement = self.enforcement_contract
        runtime = enforcement.runtime_descriptor
        image = enforcement.worker_image
        if (
            preflight.status != "preflight_compatible"
            or not preflight.provider_claims_compatible
            or enforcement.status != "contract_satisfied"
            or not enforcement.requirements_structurally_satisfied
        ):
            raise RuntimeEnforcementError(
                "foundation preconditions are blocked"
            )
        if (
            plan.worker_request != request
            or preflight.policy != enforcement.sandbox_policy
            or materialization.contract.reconstruction_plan != plan
            or runtime.sandbox_provider_id != provider.provider_id
        ):
            raise RuntimeEnforcementError("foundation object binding mismatch")
        expected = (
            (self.action_digest, self.action.action_digest),
            (self.authorization_digest, authorization.authorization_digest),
            (self.request_digest, request.request_digest),
            (self.attempt_id, request.attempt_id),
            (self.worker_provider_id, authorization.worker.provider_id),
            (
                self.worker_descriptor_digest,
                authorization.worker_descriptor_digest,
            ),
            (self.sandbox_provider_id, provider.provider_id),
            (
                self.sandbox_provider_descriptor_digest,
                provider.descriptor_sha256,
            ),
            (self.policy_digest, preflight.policy.policy_sha256),
            (self.reconstruction_plan_digest, plan.plan_sha256),
            (
                self.materialization_receipt_digest,
                materialization.receipt_sha256,
            ),
            (self.runtime_descriptor_digest, runtime.descriptor_sha256),
            (self.image_contract_digest, image.contract_sha256),
            (self.enforcement_contract_digest, enforcement.contract_sha256),
            (self.pinned_base_sha, request.job.base_sha),
        )
        if any(actual != wanted for actual, wanted in expected):
            raise RuntimeEnforcementError("runtime readiness binding mismatch")
        if self.status != "foundation_ready_unverified":
            raise RuntimeEnforcementError("runtime readiness status is forged")
        required_true = (
            self.runtime_contract_valid,
            self.materialization_contract_valid,
            self.enforcement_requirements_structurally_satisfied,
            self.provider_claims_only,
        )
        required_false = (
            self.runtime_backend_executed,
            self.runtime_isolation_verified,
            self.materialization_verified,
            self.launch_authorized,
            self.safe_to_execute,
            self.execution_performed,
            self.network_authorized,
            self.credentials_granted,
            self.github_authorized,
            self.queue_transition_authorized,
            self.publication_authorized,
        )
        if any(value is not True for value in required_true) or any(
            value is not False for value in required_false
        ):
            raise RuntimeEnforcementError(
                "runtime readiness receipt overstates authority"
            )
        _sha256(self.receipt_sha256, "runtime readiness receipt digest")
        if self.receipt_sha256 != hashlib.sha256(
            self._payload()
        ).hexdigest():
            raise RuntimeEnforcementError("runtime readiness digest mismatch")
        if len(self.canonical_bytes()) > MAX_CONTRACT_BYTES:
            raise RuntimeEnforcementError(
                "runtime readiness exceeds byte bound"
            )

    def _body(self):
        return {
            "action_digest": self.action_digest,
            "attempt_id": self.attempt_id,
            "authorization_digest": self.authorization_digest,
            "credentials_granted": False,
            "enforcement_contract_digest": self.enforcement_contract_digest,
            "enforcement_requirements_structurally_satisfied": True,
            "execution_performed": False,
            "github_authorized": False,
            "image_contract_digest": self.image_contract_digest,
            "launch_authorized": False,
            "materialization_contract_valid": True,
            "materialization_receipt_digest": (
                self.materialization_receipt_digest
            ),
            "materialization_verified": False,
            "network_authorized": False,
            "pinned_base_sha": self.pinned_base_sha,
            "policy_digest": self.policy_digest,
            "provider_claims_only": True,
            "publication_authorized": False,
            "queue_transition_authorized": False,
            "reconstruction_plan_digest": self.reconstruction_plan_digest,
            "request_digest": self.request_digest,
            "runtime_backend_executed": False,
            "runtime_contract_valid": True,
            "runtime_descriptor_digest": self.runtime_descriptor_digest,
            "runtime_isolation_verified": False,
            "safe_to_execute": False,
            "sandbox_provider_descriptor_digest": (
                self.sandbox_provider_descriptor_digest
            ),
            "sandbox_provider_id": self.sandbox_provider_id,
            "status": "foundation_ready_unverified",
            "worker_descriptor_digest": self.worker_descriptor_digest,
            "worker_provider_id": self.worker_provider_id,
        }

    def _payload(self):
        return _canonical(self._body())

    def canonical_bytes(self):
        value = self._body()
        value["receipt_sha256"] = self.receipt_sha256
        return _canonical(value)


def create_runtime_foundation_readiness(
    action, provider_preflight, materialization_receipt,
    enforcement_contract,
):
    authorization = action.authorization
    request = authorization.request
    provider = provider_preflight.provider_descriptor
    values = {
        "action": action,
        "provider_preflight": provider_preflight,
        "materialization_receipt": materialization_receipt,
        "enforcement_contract": enforcement_contract,
        "action_digest": action.action_digest,
        "authorization_digest": authorization.authorization_digest,
        "request_digest": request.request_digest,
        "attempt_id": request.attempt_id,
        "worker_provider_id": authorization.worker.provider_id,
        "worker_descriptor_digest": authorization.worker_descriptor_digest,
        "sandbox_provider_id": provider.provider_id,
        "sandbox_provider_descriptor_digest": provider.descriptor_sha256,
        "policy_digest": provider_preflight.policy.policy_sha256,
        "reconstruction_plan_digest": (
            provider_preflight.repository_plan.plan_sha256
        ),
        "materialization_receipt_digest": (
            materialization_receipt.receipt_sha256
        ),
        "runtime_descriptor_digest": (
            enforcement_contract.runtime_descriptor.descriptor_sha256
        ),
        "image_contract_digest": (
            enforcement_contract.worker_image.contract_sha256
        ),
        "enforcement_contract_digest": enforcement_contract.contract_sha256,
        "pinned_base_sha": request.job.base_sha,
    }
    provisional = object.__new__(RuntimeFoundationReadinessReceipt)
    for name, value in values.items():
        object.__setattr__(provisional, name, value)
    return RuntimeFoundationReadinessReceipt(
        **values,
        receipt_sha256=hashlib.sha256(provisional._payload()).hexdigest(),
    )


@dataclass(frozen=True)
class RuntimeExecutionHandleContract:
    readiness_receipt: RuntimeFoundationReadinessReceipt
    execution_id: str
    supervisor_owner_id: str
    runtime_descriptor_digest: str
    action_digest: str
    authorization_digest: str
    request_digest: str
    policy_digest: str
    reconstruction_plan_digest: str
    materialization_receipt_digest: str
    image_contract_digest: str
    attempt_id: str
    handle_contract_sha256: str
    lifecycle_state: str = "prepared"
    start_time: Optional[str] = None
    container_identifier_reference: Optional[str] = None
    runtime_handle_created: bool = False
    container_disappearance_observed: bool = False
    completion_confirmed: bool = False
    execution_performed: bool = False

    def __post_init__(self):
        if not isinstance(
            self.readiness_receipt, RuntimeFoundationReadinessReceipt
        ):
            raise RuntimeEnforcementError(
                "runtime readiness receipt is invalid"
            )
        _identity(self.execution_id, "execution ID")
        _identity(self.supervisor_owner_id, "supervisor owner ID")
        receipt = self.readiness_receipt
        expected = (
            (
                self.runtime_descriptor_digest,
                receipt.runtime_descriptor_digest,
            ),
            (self.action_digest, receipt.action_digest),
            (self.authorization_digest, receipt.authorization_digest),
            (self.request_digest, receipt.request_digest),
            (self.policy_digest, receipt.policy_digest),
            (
                self.reconstruction_plan_digest,
                receipt.reconstruction_plan_digest,
            ),
            (
                self.materialization_receipt_digest,
                receipt.materialization_receipt_digest,
            ),
            (self.image_contract_digest, receipt.image_contract_digest),
            (self.attempt_id, receipt.attempt_id),
        )
        if any(actual != wanted for actual, wanted in expected):
            raise RuntimeEnforcementError("execution handle binding mismatch")
        if self.lifecycle_state not in LIFECYCLE_STATES:
            raise RuntimeEnforcementError(
                "runtime lifecycle state is unsupported"
            )
        if (
            self.lifecycle_state != "prepared"
            or self.start_time is not None
            or self.container_identifier_reference is not None
            or self.runtime_handle_created is not False
            or self.container_disappearance_observed is not False
            or self.completion_confirmed is not False
            or self.execution_performed is not False
        ):
            raise RuntimeEnforcementError(
                "foundation cannot fabricate a runtime execution handle"
            )
        _sha256(
            self.handle_contract_sha256,
            "execution handle contract digest",
        )
        if self.handle_contract_sha256 != hashlib.sha256(
            self._payload()
        ).hexdigest():
            raise RuntimeEnforcementError("execution handle contract mismatch")

    def _body(self):
        return {
            "action_digest": self.action_digest,
            "attempt_id": self.attempt_id,
            "authorization_digest": self.authorization_digest,
            "completion_confirmed": False,
            "container_disappearance_observed": False,
            "container_identifier_reference": None,
            "execution_id": self.execution_id,
            "execution_performed": False,
            "image_contract_digest": self.image_contract_digest,
            "lifecycle_state": "prepared",
            "materialization_receipt_digest": (
                self.materialization_receipt_digest
            ),
            "policy_digest": self.policy_digest,
            "reconstruction_plan_digest": self.reconstruction_plan_digest,
            "request_digest": self.request_digest,
            "runtime_descriptor_digest": self.runtime_descriptor_digest,
            "runtime_handle_created": False,
            "start_time": None,
            "supervisor_owner_id": self.supervisor_owner_id,
        }

    def _payload(self):
        return _canonical(self._body())

    def canonical_bytes(self):
        value = self._body()
        value["handle_contract_sha256"] = self.handle_contract_sha256
        return _canonical(value)


def create_prepared_execution_handle_contract(
    readiness_receipt, execution_id, supervisor_owner_id,
):
    values = {
        "readiness_receipt": readiness_receipt,
        "execution_id": execution_id,
        "supervisor_owner_id": supervisor_owner_id,
        "runtime_descriptor_digest": (
            readiness_receipt.runtime_descriptor_digest
        ),
        "action_digest": readiness_receipt.action_digest,
        "authorization_digest": readiness_receipt.authorization_digest,
        "request_digest": readiness_receipt.request_digest,
        "policy_digest": readiness_receipt.policy_digest,
        "reconstruction_plan_digest": (
            readiness_receipt.reconstruction_plan_digest
        ),
        "materialization_receipt_digest": (
            readiness_receipt.materialization_receipt_digest
        ),
        "image_contract_digest": readiness_receipt.image_contract_digest,
        "attempt_id": readiness_receipt.attempt_id,
    }
    provisional = object.__new__(RuntimeExecutionHandleContract)
    for name, value in values.items():
        object.__setattr__(provisional, name, value)
    return RuntimeExecutionHandleContract(
        **values,
        handle_contract_sha256=hashlib.sha256(
            provisional._payload()
        ).hexdigest(),
    )


@dataclass(frozen=True)
class RuntimeCancellationSemantics:
    cancellation_id: str
    handle_contract: RuntimeExecutionHandleContract
    execution_id: str
    supervisor_owner_id: str
    handle_contract_digest: str
    cancellation_sha256: str
    graceful_termination_first: bool = True
    escalation_bounded_to_execution: bool = True
    cancellation_requested: bool = True
    cancellation_performed: bool = False
    termination_confirmed: bool = False
    cancelled: bool = False
    termination_uncertain: bool = True

    def __post_init__(self):
        if not isinstance(
            self.handle_contract, RuntimeExecutionHandleContract
        ):
            raise RuntimeEnforcementError(
                "execution handle contract is invalid"
            )
        _identity(self.cancellation_id, "cancellation ID")
        expected = (
            (self.execution_id, self.handle_contract.execution_id),
            (
                self.supervisor_owner_id,
                self.handle_contract.supervisor_owner_id,
            ),
            (
                self.handle_contract_digest,
                self.handle_contract.handle_contract_sha256,
            ),
        )
        if any(actual != wanted for actual, wanted in expected):
            raise RuntimeEnforcementError(
                "cancellation target binding mismatch"
            )
        if any(
            value is not True
            for value in (
                self.graceful_termination_first,
                self.escalation_bounded_to_execution,
                self.cancellation_requested,
                self.termination_uncertain,
            )
        ) or any(
            value is not False
            for value in (
                self.cancellation_performed,
                self.termination_confirmed,
                self.cancelled,
            )
        ):
            raise RuntimeEnforcementError(
                "cancellation semantics fabricate confirmed termination"
            )
        _sha256(self.cancellation_sha256, "cancellation contract digest")
        if self.cancellation_sha256 != hashlib.sha256(
            self._payload()
        ).hexdigest():
            raise RuntimeEnforcementError(
                "cancellation contract digest mismatch"
            )

    def _body(self):
        return {
            "cancellation_id": self.cancellation_id,
            "cancellation_performed": False,
            "cancellation_requested": True,
            "cancelled": False,
            "escalation_bounded_to_execution": True,
            "execution_id": self.execution_id,
            "graceful_termination_first": True,
            "handle_contract_digest": self.handle_contract_digest,
            "supervisor_owner_id": self.supervisor_owner_id,
            "termination_confirmed": False,
            "termination_uncertain": True,
        }

    def _payload(self):
        return _canonical(self._body())

    def canonical_bytes(self):
        value = self._body()
        value["cancellation_sha256"] = self.cancellation_sha256
        return _canonical(value)


def create_runtime_cancellation_semantics(
    cancellation_id, handle_contract,
):
    values = {
        "cancellation_id": cancellation_id,
        "handle_contract": handle_contract,
        "execution_id": handle_contract.execution_id,
        "supervisor_owner_id": handle_contract.supervisor_owner_id,
        "handle_contract_digest": handle_contract.handle_contract_sha256,
    }
    provisional = object.__new__(RuntimeCancellationSemantics)
    for name, value in values.items():
        object.__setattr__(provisional, name, value)
    return RuntimeCancellationSemantics(
        **values,
        cancellation_sha256=hashlib.sha256(
            provisional._payload()
        ).hexdigest(),
    )
