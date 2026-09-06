"""Focused tests for CB-027A trusted policy / TCB registry."""

import dataclasses
import hashlib
import json

import pytest

from backend.continuous_builder.trusted_policy import (
    AUTHORITY_FLAGS,
    CATEGORIES,
    CHANGE_POLICIES,
    POLICY_VERSION,
    REGISTRY_VERSION,
    TCBPathClassification,
    TrustedComponent,
    TrustedPolicyError,
    TrustedPolicyRegistry,
    TrustedPolicySnapshot,
    classify_tcb_path,
    create_mootos_tcb_registry_v1,
    create_trusted_policy_snapshot,
    is_tcb_path,
)


def _digest(value):
    return hashlib.sha256(value).hexdigest()


def _canonical(value):
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")


def _forge(instance, **changes):
    forged = object.__new__(type(instance))
    for item in dataclasses.fields(instance):
        object.__setattr__(
            forged,
            item.name,
            changes.get(item.name, getattr(instance, item.name)),
        )
    return forged


def test_canonical_construct_is_immutable_and_versioned():
    registry = create_mootos_tcb_registry_v1()
    assert registry.version == REGISTRY_VERSION
    assert registry.policy_version == POLICY_VERSION
    assert registry.components
    assert registry.protected_paths
    with pytest.raises(dataclasses.FrozenInstanceError):
        registry.version = "mutated"


def test_digest_stability_across_repeated_construction():
    first = create_mootos_tcb_registry_v1()
    second = create_mootos_tcb_registry_v1()
    assert first.registry_sha256 == second.registry_sha256
    assert first.protected_paths == second.protected_paths
    assert first.canonical_bytes() == second.canonical_bytes()
    snap_a = create_trusted_policy_snapshot()
    snap_b = create_trusted_policy_snapshot()
    assert snap_a.snapshot_sha256 == snap_b.snapshot_sha256
    assert snap_a.registry_sha256 == first.registry_sha256


def test_self_protection_includes_trusted_policy_module():
    registry = create_mootos_tcb_registry_v1()
    self_path = "backend/continuous_builder/trusted_policy.py"
    assert self_path in registry.protected_paths
    component = registry.component_for_path(self_path)
    assert component is not None
    assert component.category == "trusted_policy"
    assert component.change_policy == "human_only"
    assert is_tcb_path(self_path) is True


@pytest.mark.parametrize(
    "path",
    [
        "backend/continuous_builder/adversarial_verifier.py",
        "backend/continuous_builder/verifier_core.py",
        "backend/continuous_builder/check_runner.py",
        "backend/continuous_builder/check_runtime.py",
    ],
)
def test_verifier_and_check_paths_are_protected(path):
    classification = classify_tcb_path(path)
    assert classification is not None
    assert classification.category == "verifier"
    assert is_tcb_path(path) is True


def test_sandbox_policy_path_is_protected():
    path = "backend/continuous_builder/sandbox_policy.py"
    classification = classify_tcb_path(path)
    assert classification is not None
    assert classification.category == "sandbox"
    assert classification.component_id == "cb_sandbox_policy"


def test_worker_authorization_path_is_protected():
    path = "backend/continuous_builder/worker_authorization.py"
    classification = classify_tcb_path(path)
    assert classification is not None
    assert classification.category == "worker_authorization"


def test_approval_and_publication_paths_are_protected():
    approval = classify_tcb_path(
        "backend/continuous_builder/chief_builder.py"
    )
    publication = classify_tcb_path(
        "scripts/capability_build/pr_publication_authorization.py"
    )
    assert approval is not None
    assert approval.category == "approval_authority"
    assert publication is not None
    assert publication.category == "publication_authority"


def test_runtime_enforcement_and_artifact_intake_are_protected():
    runtime = classify_tcb_path(
        "backend/continuous_builder/runtime_enforcement.py"
    )
    artifact = classify_tcb_path(
        "backend/continuous_builder/worker_artifact.py"
    )
    assert runtime is not None
    assert runtime.category == "execution_policy"
    assert artifact is not None
    assert artifact.category == "artifact_intake"


def test_ordinary_app_path_is_not_tcb():
    assert is_tcb_path("backend/memory.py") is False
    assert classify_tcb_path("backend/memory.py") is None
    assert is_tcb_path("backend/tasks.py") is False
    assert is_tcb_path("frontend/app.js") is False


@pytest.mark.parametrize(
    "path",
    [
        "../secrets.txt",
        "../../etc/passwd",
        "/etc/passwd",
        "backend/../backend/memory.py",
        ".git/config",
        "backend/.git/hooks/pre-commit",
        ".env",
        "backend/.env",
        "backend/**/*.py",
        "backend/continuous_builder/*.py",
        "backend/continuous_builder/?",
    ],
)
def test_traversal_absolute_git_env_and_globs_rejected(path):
    assert is_tcb_path(path) is False
    assert classify_tcb_path(path) is None


def test_direct_registry_construction_without_token_is_rejected():
    with pytest.raises(TrustedPolicyError, match="trusted system construction"):
        TrustedPolicyRegistry(
            version=REGISTRY_VERSION,
            components=(),
            protected_paths=(),
            registry_sha256="0" * 64,
        )


def test_direct_component_construction_without_token_is_rejected():
    with pytest.raises(TrustedPolicyError, match="trusted system construction"):
        TrustedComponent(
            component_id="forged",
            category="verifier",
            paths=("backend/memory.py",),
            rationale_code="forged_rationale",
            change_policy="human_only",
            registry_version=REGISTRY_VERSION,
            component_sha256="0" * 64,
        )


def test_duplicate_component_id_rejected():
    registry = create_mootos_tcb_registry_v1()
    first = registry.components[0]
    forged_components = registry.components + (first,)
    with pytest.raises(TrustedPolicyError, match="component IDs"):
        TrustedPolicyRegistry(
            version=registry.version,
            components=forged_components,
            protected_paths=registry.protected_paths,
            registry_sha256=registry.registry_sha256,
            policy_version=registry.policy_version,
            _token=getattr(registry, "_token"),
        )


def test_duplicate_path_ownership_rejected():
    registry = create_mootos_tcb_registry_v1()
    a = registry.components[0]
    b = registry.components[1]
    stolen = _forge(b, paths=a.paths, component_sha256=a.component_sha256)
    components = tuple(
        stolen if component.component_id == b.component_id else component
        for component in registry.components
    )
    with pytest.raises(TrustedPolicyError, match="overlapping"):
        TrustedPolicyRegistry(
            version=registry.version,
            components=components,
            protected_paths=registry.protected_paths,
            registry_sha256=registry.registry_sha256,
            policy_version=registry.policy_version,
            _token=getattr(registry, "_token"),
        )


def test_unknown_category_rejected():
    registry = create_mootos_tcb_registry_v1()
    component = registry.components[0]
    with pytest.raises(TrustedPolicyError, match="category"):
        TrustedComponent(
            component_id=component.component_id,
            category="not_a_real_category",
            paths=component.paths,
            rationale_code=component.rationale_code,
            change_policy=component.change_policy,
            registry_version=component.registry_version,
            component_sha256=component.component_sha256,
            _token=getattr(component, "_token"),
        )


def test_unknown_change_policy_rejected():
    registry = create_mootos_tcb_registry_v1()
    component = registry.components[0]
    with pytest.raises(TrustedPolicyError, match="change policy"):
        TrustedComponent(
            component_id=component.component_id,
            category=component.category,
            paths=component.paths,
            rationale_code=component.rationale_code,
            change_policy="unreviewed_free_for_all",
            registry_version=component.registry_version,
            component_sha256=component.component_sha256,
            _token=getattr(component, "_token"),
        )


def test_empty_component_paths_rejected():
    registry = create_mootos_tcb_registry_v1()
    component = registry.components[0]
    with pytest.raises(TrustedPolicyError, match="non-empty"):
        TrustedComponent(
            component_id=component.component_id,
            category=component.category,
            paths=(),
            rationale_code=component.rationale_code,
            change_policy=component.change_policy,
            registry_version=component.registry_version,
            component_sha256=component.component_sha256,
            _token=getattr(component, "_token"),
        )


def test_forged_component_digest_rejected():
    registry = create_mootos_tcb_registry_v1()
    component = registry.components[0]
    with pytest.raises(TrustedPolicyError, match="digest"):
        TrustedComponent(
            component_id=component.component_id,
            category=component.category,
            paths=component.paths,
            rationale_code=component.rationale_code,
            change_policy=component.change_policy,
            registry_version=component.registry_version,
            component_sha256="ab" * 32,
            _token=getattr(component, "_token"),
        )


def test_forged_registry_digest_rejected():
    registry = create_mootos_tcb_registry_v1()
    with pytest.raises(TrustedPolicyError, match="digest"):
        TrustedPolicyRegistry(
            version=registry.version,
            components=registry.components,
            protected_paths=registry.protected_paths,
            registry_sha256="cd" * 32,
            policy_version=registry.policy_version,
            _token=getattr(registry, "_token"),
        )


def test_authority_promotion_on_snapshot_rejected():
    snapshot = create_trusted_policy_snapshot()
    for flag in AUTHORITY_FLAGS:
        with pytest.raises(TrustedPolicyError, match="authority"):
            TrustedPolicySnapshot(
                registry_sha256=snapshot.registry_sha256,
                protected_path_count=snapshot.protected_path_count,
                protected_paths_sha256=snapshot.protected_paths_sha256,
                component_count=snapshot.component_count,
                policy_version=snapshot.policy_version,
                snapshot_sha256=snapshot.snapshot_sha256,
                **{flag: True},
                _token=getattr(snapshot, "_token"),
            )


def test_forged_snapshot_digest_rejected():
    snapshot = create_trusted_policy_snapshot()
    with pytest.raises(TrustedPolicyError, match="digest"):
        TrustedPolicySnapshot(
            registry_sha256=snapshot.registry_sha256,
            protected_path_count=snapshot.protected_path_count,
            protected_paths_sha256=snapshot.protected_paths_sha256,
            component_count=snapshot.component_count,
            policy_version=snapshot.policy_version,
            snapshot_sha256="ef" * 32,
            _token=getattr(snapshot, "_token"),
        )


def test_deterministic_component_and_path_ordering():
    registry = create_mootos_tcb_registry_v1()
    ids = tuple(component.component_id for component in registry.components)
    assert ids == tuple(sorted(ids))
    assert registry.protected_paths == tuple(sorted(registry.protected_paths))
    for component in registry.components:
        assert component.paths == tuple(sorted(component.paths))
    body = json.loads(registry.canonical_bytes().decode("utf-8"))
    assert body["protected_paths"] == sorted(body["protected_paths"])
    assert [item["component_id"] for item in body["components"]] == sorted(
        item["component_id"] for item in body["components"]
    )


def test_query_helpers_ignore_fake_registry_objects():
    """classify/is_tcb always use the canonical factory, never caller state."""
    fake_path = "backend/memory.py"
    assert is_tcb_path(fake_path) is False
    fake_map = {fake_path: "verifier"}
    assert fake_map.get(fake_path) == "verifier"
    assert classify_tcb_path(fake_path) is None
    local_registry = {"backend/continuous_builder/verifier_core.py": None}
    assert "backend/continuous_builder/verifier_core.py" in local_registry
    result = classify_tcb_path(
        "backend/continuous_builder/verifier_core.py"
    )
    assert isinstance(result, TCBPathClassification)
    assert result.is_tcb is True
    assert result.registry_sha256 == create_mootos_tcb_registry_v1().registry_sha256


def test_snapshot_has_zero_authority():
    snapshot = create_trusted_policy_snapshot()
    for flag in AUTHORITY_FLAGS:
        assert getattr(snapshot, flag) is False
    registry = create_mootos_tcb_registry_v1()
    assert snapshot.registry_sha256 == registry.registry_sha256
    assert snapshot.protected_path_count == len(registry.protected_paths)
    assert snapshot.component_count == len(registry.components)
    assert snapshot.protected_paths_sha256 == _digest(
        _canonical(list(registry.protected_paths))
    )


def test_categories_and_policies_are_bounded():
    registry = create_mootos_tcb_registry_v1()
    for component in registry.components:
        assert component.category in CATEGORIES
        assert component.change_policy in CHANGE_POLICIES
    assert "trusted_policy" in {
        component.category for component in registry.components
    }


def test_omitting_self_path_from_protected_set_fails():
    registry = create_mootos_tcb_registry_v1()
    self_path = "backend/continuous_builder/trusted_policy.py"
    components = tuple(
        component for component in registry.components
        if component.component_id != "cb_trusted_policy"
    )
    reduced = tuple(
        path for path in registry.protected_paths if path != self_path
    )
    with pytest.raises(TrustedPolicyError, match="protect its own path"):
        TrustedPolicyRegistry(
            version=registry.version,
            components=components,
            protected_paths=reduced,
            registry_sha256=registry.registry_sha256,
            policy_version=registry.policy_version,
            _token=getattr(registry, "_token"),
        )


def test_worker_cannot_mark_arbitrary_file_trusted_via_public_api():
    """There is no public constructor that accepts caller paths."""
    import backend.continuous_builder.trusted_policy as module

    public_names = [
        name for name in dir(module)
        if callable(getattr(module, name)) and not name.startswith("_")
    ]
    assert "create_mootos_tcb_registry_v1" in public_names
    assert "create_trusted_component" not in public_names
    assert "create_trusted_policy_registry" not in public_names
    with pytest.raises(TrustedPolicyError):
        module.TrustedPolicyRegistry(
            version=REGISTRY_VERSION,
            components=(),
            protected_paths=("backend/memory.py",),
            registry_sha256="0" * 64,
        )
    assert is_tcb_path("backend/memory.py") is False
