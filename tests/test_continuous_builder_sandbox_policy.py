import ast
from dataclasses import FrozenInstanceError, replace
from pathlib import Path

import pytest

from backend.continuous_builder.sandbox_policy import (
    ContainmentPreflightReceipt,
    SandboxMountPolicy,
    SandboxPolicyError,
    SandboxResourceLimits,
    create_sandbox_policy,
    evaluate_containment_preflight,
)
from backend.continuous_builder.sandbox_provider import (
    ISOLATION_CAPABILITIES, SandboxProviderDescriptor,
)
from tests.test_continuous_builder_sandbox_repository import _plan


def _resources(**changes):
    values = {
        "max_wall_seconds": 600,
        "max_cpu_millis": 2000,
        "max_memory_bytes": 512 * 1024 * 1024,
        "max_output_bytes": 65536,
        "max_log_bytes": 65536,
        "max_processes": 16,
        "max_files": 10000,
        "max_file_bytes": 1024 * 1024,
    }
    values.update(changes)
    return SandboxResourceLimits(**values)


def _provider(**changes):
    values = {
        "provider_id": "sandbox-provider",
        "backend_type": "container",
        "isolation_capabilities": ISOLATION_CAPABILITIES,
        "supported_platforms": ("linux-amd64",),
        "supported_runtimes": ("python-3.11",),
        "availability_class": "available",
    }
    values.update(changes)
    return SandboxProviderDescriptor(**values)


def _policy(plan=None, **changes):
    plan = plan or _plan()
    values = {
        "policy_id": "policy-4a",
        "repository_plan": plan,
        "resources": _resources(),
        "required_platform": "linux-amd64",
        "required_runtime": "python-3.11",
    }
    values.update(changes)
    return create_sandbox_policy(**values)


def test_policy_is_deny_by_default_bounded_and_exactly_mounted():
    plan = _plan()
    policy = _policy(plan)
    assert policy.network_mode == "deny_all"
    assert policy.credential_mode == "none"
    assert policy.credential_reference_ids == ()
    assert policy.inherit_host_environment is False
    assert policy.host_home_mounted is False
    assert policy.host_repository_writable is False
    assert policy.container_socket_mounted is False
    assert policy.ssh_agent_socket_mounted is False
    assert policy.launch_authorized is False
    assert policy.writable_workspace_id == plan.disposable_workspace_id
    assert len(policy.mounts) == 2
    assert len(policy.canonical_bytes()) < 64 * 1024


@pytest.mark.parametrize(
    "name",
    (
        "API_TOKEN", "SECRET", "PASSWORD", "AUTH_HEADER", "SSH_AUTH_SOCK",
        "AWS_PROFILE", "GITHUB_TOKEN", "session_cookie", "BAD-NAME",
    ),
)
def test_sensitive_or_malformed_environment_names_rejected(name):
    with pytest.raises(SandboxPolicyError, match="unsafe name"):
        _policy(environment_allowlist=(name,))


def test_environment_is_explicit_deterministic_and_rejects_string_misuse():
    plan = _plan()
    first = _policy(plan, environment_allowlist=("LC_ALL", "LANG"))
    second = _policy(plan, environment_allowlist=("LANG", "LC_ALL"))
    assert first.environment_allowlist == second.environment_allowlist
    assert first.canonical_bytes() == second.canonical_bytes()
    with pytest.raises(SandboxPolicyError, match="collection"):
        _policy(environment_allowlist="LANG")


@pytest.mark.parametrize(
    "changes",
    (
        {"max_wall_seconds": 0},
        {"max_wall_seconds": 3601},
        {"max_cpu_millis": None},
        {"max_memory_bytes": 16 * 1024 * 1024},
        {"max_output_bytes": 10 * 1024 * 1024 + 1},
        {"max_processes": 0},
        {"max_files": 0},
        {"max_file_bytes": 64 * 1024 * 1024 + 1},
    ),
)
def test_resource_limits_are_finite_and_hard_bounded(changes):
    with pytest.raises(SandboxPolicyError):
        _resources(**changes)


def test_network_credentials_and_mounts_use_closed_deny_contracts():
    policy = _policy()
    with pytest.raises(SandboxPolicyError):
        replace(policy, network_mode="internet")
    with pytest.raises(SandboxPolicyError):
        replace(policy, credential_mode="github_token")
    with pytest.raises(SandboxPolicyError):
        replace(policy, credential_reference_ids=("credential-1",))
    with pytest.raises(SandboxPolicyError):
        SandboxMountPolicy(
            "read_only_source", "/Users/person/.ssh", "source_root",
            "read_only",
        )
    with pytest.raises(SandboxPolicyError):
        SandboxMountPolicy(
            "disposable_workspace", "disposable-1", "host_home", "read_write"
        )


def test_preflight_reports_compatible_claims_without_execution_readiness():
    plan = _plan()
    policy = _policy(plan)
    receipt = evaluate_containment_preflight(_provider(), plan, policy)
    assert receipt.status == "preflight_compatible"
    assert receipt.policy_structurally_valid is True
    assert receipt.provider_claims_compatible is True
    assert receipt.reconstruction_contract_valid is True
    assert receipt.provider_claims_only is True
    assert receipt.runtime_isolation_verified is False
    assert receipt.safe_to_execute is False
    assert receipt.launch_authorized is False
    assert receipt.execution_performed is False


def test_missing_provider_feature_blocks_preflight_without_shortcut():
    plan = _plan()
    policy = _policy(plan)
    capabilities = tuple(
        value for value in ISOLATION_CAPABILITIES
        if value != "filesystem_isolation"
    )
    receipt = evaluate_containment_preflight(
        _provider(isolation_capabilities=capabilities), plan, policy
    )
    assert receipt.status == "preflight_blocked"
    assert receipt.provider_claims_compatible is False
    assert receipt.missing_provider_capabilities == ("filesystem_isolation",)
    assert receipt.launch_authorized is False


def test_plan_binding_and_budget_growth_fail_closed():
    first_plan = _plan()
    second_plan = _plan(
        disposable_workspace_id="disposable-attempt-other"
    )
    with pytest.raises(SandboxPolicyError, match="source binding"):
        evaluate_containment_preflight(
            _provider(), second_plan, _policy(first_plan)
        )
    with pytest.raises(SandboxPolicyError, match="grow request budget"):
        _policy(first_plan, resources=_resources(max_wall_seconds=1801))


def test_preflight_is_deterministic_immutable_and_forgery_resistant():
    plan = _plan()
    policy = _policy(plan)
    first = evaluate_containment_preflight(_provider(), plan, policy)
    second = evaluate_containment_preflight(_provider(), plan, policy)
    assert isinstance(first, ContainmentPreflightReceipt)
    assert first.canonical_bytes() == second.canonical_bytes()
    assert len(first.canonical_bytes()) < 64 * 1024
    with pytest.raises(FrozenInstanceError):
        first.status = "preflight_blocked"
    for name, value in (
        ("runtime_isolation_verified", True),
        ("safe_to_execute", True),
        ("launch_authorized", True),
        ("execution_performed", True),
        ("provider_claims_compatible", False),
        ("receipt_sha256", "0" * 64),
    ):
        with pytest.raises(SandboxPolicyError):
            replace(first, **{name: value})


@pytest.mark.parametrize(
    "field",
    (
        "inherit_host_environment",
        "host_home_mounted",
        "host_repository_writable",
        "arbitrary_absolute_mounts",
        "device_mounts",
        "container_socket_mounted",
        "ssh_agent_socket_mounted",
        "credential_directories_mounted",
        "host_temp_reused",
        "launch_authorized",
        "queue_transition_authorized",
        "approval_granted",
        "budget_growth_allowed",
    ),
)
def test_policy_cannot_manufacture_authority(field):
    with pytest.raises(SandboxPolicyError, match="forbidden authority"):
        replace(_policy(), **{field: True})


def test_phase4a_modules_have_no_execution_network_or_filesystem_facility():
    forbidden = {
        "subprocess", "socket", "requests", "httpx", "docker", "podman",
        "kubernetes", "paramiko", "fabric", "pexpect", "os", "pathlib",
        "shutil", "git",
    }
    for filename in (
        "sandbox_provider.py", "sandbox_repository.py", "sandbox_policy.py"
    ):
        source = Path(
            "backend/continuous_builder"
        ).joinpath(filename).read_text(encoding="utf-8")
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
        assert not imports & forbidden
