import ast
from dataclasses import FrozenInstanceError, replace
from pathlib import Path

import pytest

from backend.continuous_builder.docker_runtime_contract import (
    create_docker_runtime_descriptor,
    create_pinned_offline_worker_image,
)
from backend.continuous_builder.repository_materialization import (
    create_planned_materialization_receipt,
    create_repository_materialization_contract,
)
from backend.continuous_builder.runtime_enforcement import (
    CONTROL_IDS,
    EnforcementControl,
    RuntimeEnforcementError,
    create_docker_enforcement_contract,
    create_prepared_execution_handle_contract,
    create_runtime_cancellation_semantics,
    create_runtime_foundation_readiness,
    default_docker_enforcement_controls,
)
from backend.continuous_builder.sandbox_policy import (
    evaluate_containment_preflight,
)
from tests.test_continuous_builder_sandbox_policy import _policy, _provider
from tests.test_continuous_builder_sandbox_repository import _plan, _source
from tests.test_continuous_builder_worker_action import _action


def _runtime(provider_id="sandbox-provider"):
    return create_docker_runtime_descriptor(
        "docker-local-v1",
        provider_id,
        "mootos-supervisor-docker",
        "27.1.1",
        "1.46",
        "linux",
        "amd64",
    )


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


def _foundation(*, runtime=None, controls=None, provider=None):
    action = _action()
    request = action.authorization.request
    plan = _plan(request=request, source=_source(request))
    policy = _policy(plan)
    provider = provider or _provider()
    preflight = evaluate_containment_preflight(provider, plan, policy)
    materialization = create_planned_materialization_receipt(
        create_repository_materialization_contract(
            plan, "materialization-attempt-1"
        )
    )
    enforcement = create_docker_enforcement_contract(
        runtime or _runtime(),
        _image(),
        policy,
        controls or default_docker_enforcement_controls(),
    )
    receipt = create_runtime_foundation_readiness(
        action, preflight, materialization, enforcement
    )
    return {
        "action": action,
        "plan": plan,
        "policy": policy,
        "provider": provider,
        "preflight": preflight,
        "materialization": materialization,
        "enforcement": enforcement,
        "readiness": receipt,
    }


def test_exact_control_set_is_deterministic_and_structurally_satisfied():
    controls = default_docker_enforcement_controls()
    assert tuple(control.control_id for control in controls) == CONTROL_IDS
    assert all(
        control.enforcement_class != "unsupported" for control in controls
    )
    values = _foundation(controls=controls)
    first = values["enforcement"]
    second = create_docker_enforcement_contract(
        first.runtime_descriptor,
        first.worker_image,
        values["policy"],
        tuple(reversed(controls)),
    )
    assert first.status == "contract_satisfied"
    assert first.requirements_structurally_satisfied is True
    assert first.runtime_enforcement_verified is False
    assert first.canonical_bytes() == second.canonical_bytes()


def test_unsupported_required_enforcement_blocks_future_readiness():
    controls = list(default_docker_enforcement_controls())
    controls[0] = EnforcementControl(controls[0].control_id, "unsupported")
    action = _action()
    request = action.authorization.request
    plan = _plan(request=request, source=_source(request))
    policy = _policy(plan)
    provider = _provider()
    preflight = evaluate_containment_preflight(provider, plan, policy)
    materialization = create_planned_materialization_receipt(
        create_repository_materialization_contract(plan, "materialization-1")
    )
    enforcement = create_docker_enforcement_contract(
        _runtime(), _image(), policy, controls
    )
    assert enforcement.status == "contract_blocked"
    assert enforcement.requirements_structurally_satisfied is False
    with pytest.raises(RuntimeEnforcementError, match="blocked"):
        create_runtime_foundation_readiness(
            action, preflight, materialization, enforcement
        )


def test_file_controls_are_honestly_supervisor_or_post_run_controls():
    controls = {item.control_id: item for item in (
        default_docker_enforcement_controls()
    )}
    assert controls["file_count_limit"].enforcement_class == (
        "post_run_verified"
    )
    assert controls["file_size_limit"].enforcement_class == (
        "post_run_verified"
    )
    changed = tuple(
        EnforcementControl(item.control_id, "post_run_verified")
        if item.control_id in {"file_count_limit", "file_size_limit"}
        else item
        for item in controls.values()
    )
    assert create_docker_enforcement_contract(
        _runtime(), _image(), _foundation()["policy"], changed
    ).status == "contract_satisfied"


def test_runtime_readiness_is_exact_bound_but_explicitly_not_safe_to_execute():
    values = _foundation()
    receipt = values["readiness"]
    request = values["action"].authorization.request
    assert receipt.action_digest == values["action"].action_digest
    assert receipt.request_digest == request.request_digest
    assert receipt.attempt_id == request.attempt_id
    assert receipt.pinned_base_sha == request.job.base_sha
    assert receipt.provider_claims_only is True
    assert receipt.runtime_contract_valid is True
    assert receipt.materialization_contract_valid is True
    assert receipt.enforcement_requirements_structurally_satisfied is True
    assert receipt.runtime_backend_executed is False
    assert receipt.runtime_isolation_verified is False
    assert receipt.materialization_verified is False
    assert receipt.launch_authorized is False
    assert receipt.safe_to_execute is False
    assert receipt.execution_performed is False
    assert receipt.network_authorized is False
    assert receipt.credentials_granted is False
    assert receipt.github_authorized is False
    assert receipt.queue_transition_authorized is False
    assert receipt.publication_authorized is False
    assert len(receipt.canonical_bytes()) < 128 * 1024


@pytest.mark.parametrize(
    "field",
    (
        "runtime_backend_executed",
        "runtime_isolation_verified",
        "materialization_verified",
        "launch_authorized",
        "safe_to_execute",
        "execution_performed",
        "network_authorized",
        "credentials_granted",
        "github_authorized",
        "queue_transition_authorized",
        "publication_authorized",
    ),
)
def test_caller_cannot_promote_foundation_evidence_to_authority(field):
    with pytest.raises(RuntimeEnforcementError, match="overstates authority"):
        replace(_foundation()["readiness"], **{field: True})


@pytest.mark.parametrize(
    "field",
    (
        "runtime_enforcement_verified",
        "runtime_backend_executed",
        "launch_authorized",
        "execution_performed",
    ),
)
def test_enforcement_contract_cannot_claim_actual_runtime_proof(field):
    with pytest.raises(RuntimeEnforcementError, match="runtime authority"):
        replace(_foundation()["enforcement"], **{field: True})


@pytest.mark.parametrize(
    "field",
    (
        "action_digest",
        "authorization_digest",
        "request_digest",
        "policy_digest",
        "reconstruction_plan_digest",
        "materialization_receipt_digest",
        "runtime_descriptor_digest",
        "image_contract_digest",
        "enforcement_contract_digest",
    ),
)
def test_stale_digest_at_every_adjacent_boundary_fails_closed(field):
    with pytest.raises(RuntimeEnforcementError, match="binding"):
        replace(_foundation()["readiness"], **{field: "0" * 64})


@pytest.mark.parametrize(
    "field,value",
    (
        ("attempt_id", "wrong-attempt"),
        ("worker_provider_id", "wrong-provider"),
        ("sandbox_provider_id", "wrong-sandbox-provider"),
        ("pinned_base_sha", "b" * 40),
    ),
)
def test_wrong_attempt_provider_or_base_fails_closed(field, value):
    with pytest.raises(RuntimeEnforcementError, match="binding"):
        replace(_foundation()["readiness"], **{field: value})


def test_runtime_descriptor_must_bind_selected_sandbox_provider():
    with pytest.raises(RuntimeEnforcementError, match="object binding"):
        _foundation(runtime=_runtime("other-sandbox-provider"))


def test_prepared_handle_is_schema_only_and_cannot_claim_execution_success():
    handle = create_prepared_execution_handle_contract(
        _foundation()["readiness"], "execution-1", "supervisor:mootos"
    )
    assert handle.lifecycle_state == "prepared"
    assert handle.start_time is None
    assert handle.container_identifier_reference is None
    assert handle.runtime_handle_created is False
    assert handle.execution_performed is False
    with pytest.raises(FrozenInstanceError):
        handle.lifecycle_state = "running"
    for changes in (
        {"lifecycle_state": "succeeded"},
        {"container_disappearance_observed": True},
        {"completion_confirmed": True},
        {"runtime_handle_created": True},
        {"start_time": "2026-01-01T00:00:00+00:00"},
        {"container_identifier_reference": "container-1"},
        {"execution_performed": True},
    ):
        with pytest.raises(RuntimeEnforcementError, match="cannot fabricate"):
            replace(handle, **changes)


def test_cancellation_targets_one_supervisor_handle_and_remains_uncertain():
    handle = create_prepared_execution_handle_contract(
        _foundation()["readiness"], "execution-1", "supervisor:mootos"
    )
    cancellation = create_runtime_cancellation_semantics(
        "cancellation-1", handle
    )
    assert cancellation.execution_id == "execution-1"
    assert cancellation.graceful_termination_first is True
    assert cancellation.escalation_bounded_to_execution is True
    assert cancellation.cancellation_requested is True
    assert cancellation.cancellation_performed is False
    assert cancellation.termination_confirmed is False
    assert cancellation.cancelled is False
    assert cancellation.termination_uncertain is True
    for changes in (
        {"execution_id": "unrelated-execution"},
        {"supervisor_owner_id": "other-supervisor"},
        {"cancellation_performed": True},
        {"termination_confirmed": True},
        {"cancelled": True},
        {"termination_uncertain": False},
    ):
        with pytest.raises(RuntimeEnforcementError):
            replace(cancellation, **changes)


def test_module_has_no_execution_network_docker_or_credential_facility():
    source = Path(
        "backend/continuous_builder/runtime_enforcement.py"
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
        "pathlib", "shutil", "git", "keyring",
    }
