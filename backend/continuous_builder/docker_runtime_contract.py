"""Inert identities for the future supervisor-owned Docker runtime.

This module intentionally has no Docker client or execution facility.  It
binds the runtime, image, and fixed offline worker entrypoint that CB-022 must
revalidate before it is permitted to perform any operation.
"""

import hashlib
import json
import re
from dataclasses import dataclass

from .text_safety import utf8_length


class DockerRuntimeContractError(ValueError):
    """Raised when a Docker runtime or image contract is unsafe."""


POLICY_VERSION = "cb-docker-runtime-contract-v1"
BACKEND_TYPE = "docker"
WORKER_KIND = "mootos_offline_fixture_worker_v1"
ENTRYPOINT_ID = "mootos.offline_fixture_worker.v1"
ENTRYPOINT_ARGV = ("/opt/mootos/bin/offline-fixture-worker",)
ARGUMENT_CONTRACT = (
    "attempt_id",
    "request_digest",
    "workspace_root",
)
MAX_CONTRACT_BYTES = 32 * 1024
_IDENTITY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:+/-]{0,255}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_IMAGE_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_IMAGE_REPOSITORY = re.compile(
    r"^[a-z0-9]+(?:[._/-][a-z0-9]+)*(?:/[a-z0-9]+(?:[._-][a-z0-9]+)*)*$"
)


def _identity(value, name):
    if (
        not isinstance(value, str)
        or _IDENTITY.fullmatch(value or "") is None
        or utf8_length(value) > 256
    ):
        raise DockerRuntimeContractError(f"{name} is malformed")
    return value


def _sha256(value, name):
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise DockerRuntimeContractError(f"{name} is malformed")
    return value


def _canonical(value):
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")


@dataclass(frozen=True)
class TrustedDockerRuntimeDescriptor:
    runtime_backend_id: str
    sandbox_provider_id: str
    engine_identity: str
    engine_version: str
    engine_api_version: str
    platform: str
    architecture: str
    descriptor_sha256: str
    backend_type: str = BACKEND_TYPE
    policy_version: str = POLICY_VERSION
    supervisor_control_only: bool = True
    worker_docker_control_allowed: bool = False
    docker_socket_exposed_to_worker: bool = False
    host_docker_config_exposed: bool = False
    network_default_deny: bool = True
    credential_default_none: bool = True
    host_home_exposed: bool = False
    host_repository_writable: bool = False
    device_mounts_allowed: bool = False
    privileged_container_allowed: bool = False
    host_pid_namespace_allowed: bool = False
    host_network_namespace_allowed: bool = False
    host_ipc_namespace_allowed: bool = False
    nested_container_control_allowed: bool = False
    arbitrary_mounts_allowed: bool = False
    runtime_execution_verified: bool = False
    launch_authorized: bool = False
    execution_performed: bool = False

    def __post_init__(self):
        for name in (
            "runtime_backend_id", "sandbox_provider_id", "engine_identity",
            "engine_version", "engine_api_version", "platform",
            "architecture",
        ):
            object.__setattr__(
                self, name, _identity(getattr(self, name), name)
            )
        if (
            self.backend_type != BACKEND_TYPE
            or self.policy_version != POLICY_VERSION
        ):
            raise DockerRuntimeContractError(
                "Docker runtime policy is unsupported"
            )
        required_true = (
            self.supervisor_control_only,
            self.network_default_deny,
            self.credential_default_none,
        )
        required_false = (
            self.worker_docker_control_allowed,
            self.docker_socket_exposed_to_worker,
            self.host_docker_config_exposed,
            self.host_home_exposed,
            self.host_repository_writable,
            self.device_mounts_allowed,
            self.privileged_container_allowed,
            self.host_pid_namespace_allowed,
            self.host_network_namespace_allowed,
            self.host_ipc_namespace_allowed,
            self.nested_container_control_allowed,
            self.arbitrary_mounts_allowed,
            self.runtime_execution_verified,
            self.launch_authorized,
            self.execution_performed,
        )
        if any(value is not True for value in required_true) or any(
            value is not False for value in required_false
        ):
            raise DockerRuntimeContractError(
                "Docker runtime contract grants authority"
            )
        _sha256(self.descriptor_sha256, "runtime descriptor digest")
        if self.descriptor_sha256 != hashlib.sha256(
            self._payload()
        ).hexdigest():
            raise DockerRuntimeContractError(
                "runtime descriptor digest mismatch"
            )
        if len(self.canonical_bytes()) > MAX_CONTRACT_BYTES:
            raise DockerRuntimeContractError(
                "runtime descriptor exceeds byte bound"
            )

    def _body(self):
        return {
            "architecture": self.architecture,
            "arbitrary_mounts_allowed": False,
            "backend_type": BACKEND_TYPE,
            "credential_default_none": True,
            "device_mounts_allowed": False,
            "docker_socket_exposed_to_worker": False,
            "engine_api_version": self.engine_api_version,
            "engine_identity": self.engine_identity,
            "engine_version": self.engine_version,
            "execution_performed": False,
            "host_docker_config_exposed": False,
            "host_home_exposed": False,
            "host_ipc_namespace_allowed": False,
            "host_network_namespace_allowed": False,
            "host_pid_namespace_allowed": False,
            "host_repository_writable": False,
            "launch_authorized": False,
            "nested_container_control_allowed": False,
            "network_default_deny": True,
            "platform": self.platform,
            "policy_version": POLICY_VERSION,
            "privileged_container_allowed": False,
            "runtime_backend_id": self.runtime_backend_id,
            "runtime_execution_verified": False,
            "sandbox_provider_id": self.sandbox_provider_id,
            "supervisor_control_only": True,
            "worker_docker_control_allowed": False,
        }

    def _payload(self):
        return _canonical(self._body())

    def canonical_bytes(self):
        value = self._body()
        value["descriptor_sha256"] = self.descriptor_sha256
        return _canonical(value)


def create_docker_runtime_descriptor(
    runtime_backend_id,
    sandbox_provider_id,
    engine_identity,
    engine_version,
    engine_api_version,
    platform,
    architecture,
):
    values = {
        "runtime_backend_id": runtime_backend_id,
        "sandbox_provider_id": sandbox_provider_id,
        "engine_identity": engine_identity,
        "engine_version": engine_version,
        "engine_api_version": engine_api_version,
        "platform": platform,
        "architecture": architecture,
    }
    provisional = object.__new__(TrustedDockerRuntimeDescriptor)
    for name, value in values.items():
        object.__setattr__(provisional, name, value)
    return TrustedDockerRuntimeDescriptor(
        **values,
        descriptor_sha256=hashlib.sha256(provisional._payload()).hexdigest(),
    )


@dataclass(frozen=True)
class FixedWorkerEntrypoint:
    entrypoint_id: str = ENTRYPOINT_ID
    worker_kind: str = WORKER_KIND
    argv: tuple = ENTRYPOINT_ARGV
    argument_contract: tuple = ARGUMENT_CONTRACT
    shell_enabled: bool = False
    host_executable_allowed: bool = False
    arbitrary_arguments_allowed: bool = False

    def __post_init__(self):
        if (
            self.entrypoint_id != ENTRYPOINT_ID
            or self.worker_kind != WORKER_KIND
            or type(self.argv) is not tuple
            or self.argv != ENTRYPOINT_ARGV
            or type(self.argument_contract) is not tuple
            or self.argument_contract != ARGUMENT_CONTRACT
            or self.shell_enabled is not False
            or self.host_executable_allowed is not False
            or self.arbitrary_arguments_allowed is not False
        ):
            raise DockerRuntimeContractError("worker entrypoint is not fixed")

    def to_dict(self):
        return {
            "arbitrary_arguments_allowed": False,
            "argument_contract": list(ARGUMENT_CONTRACT),
            "argv": list(ENTRYPOINT_ARGV),
            "entrypoint_id": ENTRYPOINT_ID,
            "host_executable_allowed": False,
            "shell_enabled": False,
            "worker_kind": WORKER_KIND,
        }


@dataclass(frozen=True)
class PinnedOfflineWorkerImage:
    image_repository: str
    image_digest: str
    image_reference: str
    platform: str
    architecture: str
    entrypoint: FixedWorkerEntrypoint
    config_sha256: str
    contract_sha256: str
    policy_version: str = POLICY_VERSION
    offline_capable: bool = True
    network_required: bool = False
    credentials_required: bool = False
    disposable_workspace_only: bool = True
    mutable_tag_allowed: bool = False
    launch_authorized: bool = False
    execution_performed: bool = False

    def __post_init__(self):
        if (
            not isinstance(self.image_repository, str)
            or _IMAGE_REPOSITORY.fullmatch(self.image_repository) is None
            or utf8_length(self.image_repository) > 256
        ):
            raise DockerRuntimeContractError(
                "image repository is malformed"
            )
        if _IMAGE_DIGEST.fullmatch(self.image_digest or "") is None:
            raise DockerRuntimeContractError("image digest is malformed")
        expected_reference = f"{self.image_repository}@{self.image_digest}"
        if self.image_reference != expected_reference:
            raise DockerRuntimeContractError(
                "image must be pinned by digest"
            )
        for token in (":latest", ":main", ":stable", ":rolling"):
            if token in self.image_reference.casefold():
                raise DockerRuntimeContractError(
                    "mutable image tag is forbidden"
                )
        for name in ("platform", "architecture"):
            object.__setattr__(
                self, name, _identity(getattr(self, name), name)
            )
        if not isinstance(self.entrypoint, FixedWorkerEntrypoint):
            raise DockerRuntimeContractError("worker entrypoint is invalid")
        _sha256(self.config_sha256, "image config digest")
        if self.policy_version != POLICY_VERSION:
            raise DockerRuntimeContractError(
                "worker image policy is unsupported"
            )
        required_true = (self.offline_capable, self.disposable_workspace_only)
        required_false = (
            self.network_required,
            self.credentials_required,
            self.mutable_tag_allowed,
            self.launch_authorized,
            self.execution_performed,
        )
        if any(value is not True for value in required_true) or any(
            value is not False for value in required_false
        ):
            raise DockerRuntimeContractError(
                "worker image grants forbidden authority"
            )
        _sha256(self.contract_sha256, "worker image contract digest")
        if self.contract_sha256 != hashlib.sha256(
            self._payload()
        ).hexdigest():
            raise DockerRuntimeContractError(
                "worker image contract digest mismatch"
            )
        if len(self.canonical_bytes()) > MAX_CONTRACT_BYTES:
            raise DockerRuntimeContractError(
                "worker image contract exceeds byte bound"
            )

    def _body(self):
        return {
            "architecture": self.architecture,
            "config_sha256": self.config_sha256,
            "credentials_required": False,
            "disposable_workspace_only": True,
            "entrypoint": self.entrypoint.to_dict(),
            "execution_performed": False,
            "image_digest": self.image_digest,
            "image_reference": self.image_reference,
            "image_repository": self.image_repository,
            "launch_authorized": False,
            "mutable_tag_allowed": False,
            "network_required": False,
            "offline_capable": True,
            "platform": self.platform,
            "policy_version": POLICY_VERSION,
        }

    def _payload(self):
        return _canonical(self._body())

    def canonical_bytes(self):
        value = self._body()
        value["contract_sha256"] = self.contract_sha256
        return _canonical(value)


def create_pinned_offline_worker_image(
    image_repository, image_digest, platform, architecture, config_sha256,
):
    values = {
        "image_repository": image_repository,
        "image_digest": image_digest,
        "image_reference": f"{image_repository}@{image_digest}",
        "platform": platform,
        "architecture": architecture,
        "entrypoint": FixedWorkerEntrypoint(),
        "config_sha256": config_sha256,
    }
    provisional = object.__new__(PinnedOfflineWorkerImage)
    for name, value in values.items():
        object.__setattr__(provisional, name, value)
    return PinnedOfflineWorkerImage(
        **values,
        contract_sha256=hashlib.sha256(provisional._payload()).hexdigest(),
    )
