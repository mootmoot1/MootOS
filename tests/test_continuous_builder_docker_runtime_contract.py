import ast
from dataclasses import FrozenInstanceError, replace
from pathlib import Path

import pytest

from backend.continuous_builder.docker_runtime_contract import (
    DockerRuntimeContractError,
    FixedWorkerEntrypoint,
    create_docker_runtime_descriptor,
    create_pinned_offline_worker_image,
)


def _runtime(**changes):
    values = {
        "runtime_backend_id": "docker-local-v1",
        "sandbox_provider_id": "sandbox-provider",
        "engine_identity": "mootos-supervisor-docker",
        "engine_version": "27.1.1",
        "engine_api_version": "1.46",
        "platform": "linux",
        "architecture": "amd64",
    }
    values.update(changes)
    return create_docker_runtime_descriptor(**values)


def _image(**changes):
    values = {
        "image_repository": "mootos/offline-fixture-worker",
        "image_digest": "sha256:" + "a" * 64,
        "platform": "linux",
        "architecture": "amd64",
        "config_sha256": "b" * 64,
    }
    values.update(changes)
    return create_pinned_offline_worker_image(**values)


def test_runtime_descriptor_is_exact_bounded_inert_and_deterministic():
    first = _runtime()
    second = _runtime()
    assert first.backend_type == "docker"
    assert first.supervisor_control_only is True
    assert first.worker_docker_control_allowed is False
    assert first.docker_socket_exposed_to_worker is False
    assert first.runtime_execution_verified is False
    assert first.launch_authorized is False
    assert first.execution_performed is False
    assert first.canonical_bytes() == second.canonical_bytes()
    assert len(first.canonical_bytes()) < 32 * 1024
    with pytest.raises(FrozenInstanceError):
        first.launch_authorized = True


@pytest.mark.parametrize(
    "field",
    (
        "worker_docker_control_allowed",
        "docker_socket_exposed_to_worker",
        "host_docker_config_exposed",
        "host_home_exposed",
        "host_repository_writable",
        "device_mounts_allowed",
        "privileged_container_allowed",
        "host_pid_namespace_allowed",
        "host_network_namespace_allowed",
        "host_ipc_namespace_allowed",
        "nested_container_control_allowed",
        "arbitrary_mounts_allowed",
        "runtime_execution_verified",
        "launch_authorized",
        "execution_performed",
    ),
)
def test_runtime_descriptor_rejects_authority_flags(field):
    with pytest.raises(DockerRuntimeContractError, match="grants authority"):
        replace(_runtime(), **{field: True})


def test_worker_image_requires_digest_and_fixed_offline_entrypoint():
    image = _image()
    assert image.image_reference.endswith("@sha256:" + "a" * 64)
    assert image.offline_capable is True
    assert image.network_required is False
    assert image.credentials_required is False
    assert image.entrypoint.argv == (
        "/opt/mootos/bin/offline-fixture-worker",
    )
    assert image.entrypoint.shell_enabled is False
    assert image.entrypoint.host_executable_allowed is False
    assert len(image.canonical_bytes()) < 32 * 1024


@pytest.mark.parametrize(
    "digest",
    ("", "latest", "sha256:short", "a" * 64, "sha512:" + "a" * 64),
)
def test_missing_or_malformed_image_digest_rejected(digest):
    with pytest.raises(DockerRuntimeContractError):
        _image(image_digest=digest)


def test_mutable_or_tag_only_image_references_cannot_be_constructed():
    image = _image()
    for reference in (
        "mootos/offline-fixture-worker:latest",
        "mootos/offline-fixture-worker:main",
        "mootos/offline-fixture-worker:stable",
        "mootos/offline-fixture-worker:rolling",
        "mootos/offline-fixture-worker:v1",
    ):
        with pytest.raises(DockerRuntimeContractError, match="pinned"):
            replace(image, image_reference=reference)


def test_arbitrary_executable_shell_and_arguments_are_rejected():
    entrypoint = FixedWorkerEntrypoint()
    for changes in (
        {"argv": ("/bin/sh", "-c", "anything")},
        {"argv": "worker --run"},
        {"shell_enabled": True},
        {"host_executable_allowed": True},
        {"arbitrary_arguments_allowed": True},
        {"argument_contract": ("command",)},
    ):
        with pytest.raises(DockerRuntimeContractError, match="not fixed"):
            replace(entrypoint, **changes)


@pytest.mark.parametrize(
    "field,value",
    (
        ("network_required", True),
        ("credentials_required", True),
        ("offline_capable", False),
        ("disposable_workspace_only", False),
        ("mutable_tag_allowed", True),
        ("launch_authorized", True),
        ("execution_performed", True),
    ),
)
def test_worker_image_cannot_request_network_credentials_or_authority(
    field, value,
):
    with pytest.raises(DockerRuntimeContractError):
        replace(_image(), **{field: value})


def test_contract_module_has_no_runtime_or_network_facility():
    source = Path(
        "backend/continuous_builder/docker_runtime_contract.py"
    ).read_text(encoding="utf-8")
    tree = ast.parse(source)
    imports = {
        alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {
        node.module.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }
    assert not imports & {
        "subprocess", "socket", "requests", "httpx", "urllib", "docker",
        "podman", "kubernetes", "paramiko", "fabric", "pexpect", "os",
        "pathlib", "shutil", "keyring",
    }
