"""CB-028F integration Cases A–J on real MootOS tree evidence."""

from pathlib import Path

import pytest

from backend.continuous_builder.system_model import (
    AUTHORITY_FLAGS,
    MODEL_VERSION,
    build_system_model,
    changed_components,
    component_for_path,
    create_system_model_snapshot,
    dependencies_of,
    files_for_component,
    impacted_components,
    model_tcb_classification,
    system_model_is_descriptive_only,
)
from backend.continuous_builder.trusted_policy import (
    create_mootos_tcb_registry_v1,
    is_tcb_path,
)


TRUSTED_BASE = "a43272719ceeade643569976aa82aa874f6d7d06"


def _repo_root():
    # tests/ -> repo root
    return Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def real_model():
    root = _repo_root()
    assert (root / "backend" / "continuous_builder").is_dir()
    return build_system_model(root, base_sha=TRUSTED_BASE)


def test_case_a_real_inventory_builds(real_model):
    assert real_model.model_version == MODEL_VERSION
    assert real_model.base_sha == TRUSTED_BASE
    assert real_model.inventory.file_count > 50
    assert real_model.inventory.total_bytes > 0


def test_case_b_cb_package_ownership(real_model):
    cid = component_for_path(
        real_model, "backend/continuous_builder/system_model.py"
    )
    assert cid == "backend.continuous_builder"
    files = files_for_component(real_model, "backend.continuous_builder")
    assert "backend/continuous_builder/system_model.py" in files
    assert "backend/continuous_builder/trusted_policy.py" in files


def test_case_c_tcb_paths_classified(real_model):
    registry = create_mootos_tcb_registry_v1()
    assert real_model.tcb_registry_sha256 == registry.registry_sha256
    for path in registry.protected_paths:
        hit = model_tcb_classification(real_model, path)
        assert hit["is_tcb"] is True
        assert hit["state"] == "tcb"
        record = next(
            item for item in real_model.inventory.files if item.path == path
        )
        assert record.is_tcb is True


def test_case_d_system_model_outside_tcb(real_model):
    assert system_model_is_descriptive_only() is True
    path = "backend/continuous_builder/system_model.py"
    assert is_tcb_path(path) is False
    assert model_tcb_classification(real_model, path)["is_tcb"] is False


def test_case_e_static_deps_for_system_model(real_model):
    deps = dependencies_of(real_model, "backend.continuous_builder")
    imported = {edge["imported_name"] for edge in deps}
    # system_model imports trusted_policy / paths / stdlib — evidence present
    assert any(
        name.startswith("backend.continuous_builder") or name in (
            "json", "hashlib", "ast", "dataclasses"
        )
        for name in imported
    )


def test_case_f_impact_ordinary_vs_tcb_paths(real_model):
    ordinary = impacted_components(
        real_model, ("backend/continuous_builder/system_model.py",)
    )
    assert "backend.continuous_builder" in ordinary.changed_components
    assert ordinary.impact_state in ("impacted", "possible_impact")
    tcb_change = changed_components(
        real_model, ("backend/continuous_builder/verifier_core.py",)
    )
    assert "backend.continuous_builder" in tcb_change
    # Model does not authorize — classification remains evidence.
    assert model_tcb_classification(
        real_model, "backend/continuous_builder/verifier_core.py"
    )["is_tcb"] is True


def test_case_g_snapshot_binds_identities(real_model):
    snap = create_system_model_snapshot(real_model)
    assert snap.model_sha256 == real_model.model_sha256
    assert snap.tcb_registry_sha256 == real_model.tcb_registry_sha256
    assert snap.base_sha == TRUSTED_BASE
    for name in AUTHORITY_FLAGS:
        assert getattr(snap, name) is False


def test_case_h_exclusions_on_real_tree(real_model):
    paths = {item.path for item in real_model.inventory.files}
    assert not any(p.startswith(".git/") for p in paths)
    assert not any("__pycache__" in p for p in paths)
    assert not any(p.endswith(".pyc") for p in paths)


def test_case_i_zero_authority_on_real_model(real_model):
    for name in AUTHORITY_FLAGS:
        assert getattr(real_model, name) is False
    assert not hasattr(real_model, "authorize_publication")
    assert not hasattr(real_model, "merge")


def test_case_j_cb027_behavior_intact(real_model):
    registry = create_mootos_tcb_registry_v1()
    assert len(registry.protected_paths) == 17
    assert registry.registry_sha256 == (
        "b23b086b640bbde70cb73f23ee4a3b1ff6973888e8dbe69359fed928dcbfa9bf"
    )
    # Missing-protected uncertainties should be empty on real checkout.
    missing = [
        item for item in real_model.uncertainties
        if item.kind == "missing_protected_path"
    ]
    assert missing == []
