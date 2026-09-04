import ast
from dataclasses import FrozenInstanceError, replace
from pathlib import Path

import pytest

from backend.continuous_builder.sandbox_provider import (
    ISOLATION_CAPABILITIES,
    SandboxProviderDescriptor,
    SandboxProviderError,
    SandboxProviderRequirement,
    probe_sandbox_providers,
)


def _provider(provider_id="provider-b", **changes):
    values = {
        "provider_id": provider_id,
        "backend_type": "container",
        "isolation_capabilities": ISOLATION_CAPABILITIES,
        "supported_platforms": ("linux-amd64",),
        "supported_runtimes": ("python-3.11",),
        "availability_class": "available",
    }
    values.update(changes)
    return SandboxProviderDescriptor(**values)


def _requirement(**changes):
    values = {
        "required_capabilities": ISOLATION_CAPABILITIES,
        "required_platform": "linux-amd64",
        "required_runtime": "python-3.11",
        "allowed_backend_types": ("container", "microvm"),
    }
    values.update(changes)
    return SandboxProviderRequirement(**values)


def test_probe_is_deterministic_and_input_order_independent():
    first = _provider("provider-b")
    second = _provider("provider-a")
    left = probe_sandbox_providers(_requirement(), (first, second))
    right = probe_sandbox_providers(_requirement(), (second, first))
    assert left == right
    assert left.status == "preflight_compatible"
    assert left.provider == second
    assert left.provider_claims_only is True
    assert left.runtime_isolation_verified is False
    assert left.launch_authorized is False


def test_missing_isolation_feature_fails_closed():
    capabilities = tuple(
        value for value in ISOLATION_CAPABILITIES
        if value != "network_deny"
    )
    result = probe_sandbox_providers(
        _requirement(), (_provider(isolation_capabilities=capabilities),)
    )
    assert result.status == "preflight_blocked"
    assert result.provider is None
    assert result.missing_capabilities == ("network_deny",)


def test_compatible_probe_cannot_be_forged_from_incompatible_provider():
    probe = probe_sandbox_providers(_requirement(), (_provider(),))
    incompatible = _provider(
        supported_platforms=("linux-arm64",),
    )
    with pytest.raises(SandboxProviderError, match="not supported"):
        replace(probe, provider=incompatible)


@pytest.mark.parametrize(
    "changes",
    (
        {"provider_id": "../provider"},
        {"isolation_capabilities": ("network_deny", "network_deny")},
        {"isolation_capabilities": ("unknown_isolation",)},
        {"supported_platforms": "linux-amd64"},
        {"supported_runtimes": tuple(str(i) for i in range(33))},
        {"policy_version": "future-policy"},
    ),
)
def test_malformed_duplicate_oversize_and_unknown_values_rejected(changes):
    with pytest.raises(SandboxProviderError):
        _provider(**changes)


@pytest.mark.parametrize(
    "field",
    (
        "execution_authorized",
        "credentials_authorized",
        "network_authorized",
        "host_filesystem_write_authorized",
        "github_authorized",
        "approval_granted",
        "queue_transition_authorized",
        "scope_growth_allowed",
        "budget_growth_allowed",
        "runtime_isolation_verified",
    ),
)
def test_provider_metadata_cannot_manufacture_authority(field):
    with pytest.raises(SandboxProviderError, match="cannot grant authority"):
        _provider(**{field: True})


def test_descriptor_and_probe_are_immutable_and_unicode_bounded():
    provider = _provider()
    probe = probe_sandbox_providers(_requirement(), (provider,))
    assert len(provider.canonical_bytes()) < 32 * 1024
    with pytest.raises(FrozenInstanceError):
        provider.provider_id = "other"
    with pytest.raises(SandboxProviderError):
        replace(probe, launch_authorized=True)
    with pytest.raises(SandboxProviderError):
        _provider(supported_runtimes=("python-π",))
    with pytest.raises(SandboxProviderError):
        _provider(supported_runtimes=("\ud800",))


def test_duplicate_provider_identity_and_string_collection_rejected():
    with pytest.raises(SandboxProviderError, match="duplicate"):
        probe_sandbox_providers(_requirement(), (_provider(), _provider()))
    with pytest.raises(SandboxProviderError, match="collection"):
        probe_sandbox_providers(_requirement(), "providers")


def test_module_has_no_execution_network_or_container_client_facility():
    source = Path(
        "backend/continuous_builder/sandbox_provider.py"
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
        "subprocess", "socket", "requests", "httpx", "docker", "podman",
        "kubernetes", "paramiko", "fabric", "pexpect", "os",
    }
