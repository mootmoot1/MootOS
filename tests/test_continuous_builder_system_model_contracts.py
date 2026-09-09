"""CB-028A — System Model immutable contracts and seal identity."""

import dataclasses
import hashlib
import json
from pathlib import Path

import pytest

from backend.continuous_builder.system_model import (
    AUTHORITY_FLAGS,
    MODEL_VERSION,
    DependencyEdge,
    OwnershipRecord,
    RepositoryFileRecord,
    SystemComponent,
    SystemModel,
    SystemModelError,
    SystemModelSnapshot,
    UncertaintyRecord,
    build_system_model,
    create_system_model_snapshot,
)
from backend.continuous_builder.trusted_policy import create_mootos_tcb_registry_v1


def _digest(value):
    if isinstance(value, str):
        value = value.encode("utf-8")
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


def _tiny_repo(tmp_path):
    root = tmp_path / "repo"
    (root / "backend" / "continuous_builder").mkdir(parents=True)
    (root / "backend" / "__init__.py").write_text("# pkg\n", encoding="utf-8")
    (root / "backend" / "continuous_builder" / "__init__.py").write_text(
        "# cb\n", encoding="utf-8"
    )
    (root / "backend" / "continuous_builder" / "hello.py").write_text(
        "import json\nfrom backend.continuous_builder import x\n",
        encoding="utf-8",
    )
    (root / "README.md").write_text("# tiny\n", encoding="utf-8")
    return root


def _base_sha():
    return "a" * 64


def test_model_version_constant():
    assert MODEL_VERSION == "cb-system-model-v1"


def test_direct_construction_without_token_fails():
    with pytest.raises(SystemModelError, match="trusted system construction"):
        RepositoryFileRecord(
            path="README.md",
            content_sha256="a" * 64,
            size_bytes=1,
            category="documentation",
            python_package_hint=None,
            is_tcb=False,
            excluded=False,
            record_sha256="b" * 64,
        )
    with pytest.raises(SystemModelError, match="trusted system construction"):
        SystemComponent(
            component_id="root",
            kind="root",
            root_path="README.md",
            file_paths=("README.md",),
            ownership_state="owned",
            component_sha256="a" * 64,
        )
    with pytest.raises(SystemModelError, match="trusted system construction"):
        DependencyEdge(
            source_component_id="backend",
            target_component_id=None,
            source_path="backend/x.py",
            imported_name="json",
            kind="external_import",
            edge_sha256="a" * 64,
        )
    with pytest.raises(SystemModelError, match="trusted system construction"):
        OwnershipRecord(
            path="README.md",
            component_id="root",
            state="owned",
            ownership_sha256="a" * 64,
        )
    with pytest.raises(SystemModelError, match="trusted system construction"):
        UncertaintyRecord(
            kind="unknown",
            subject="x",
            detail_code="y",
            uncertainty_sha256="a" * 64,
        )


def test_build_model_immutable_versioned_bound(tmp_path):
    root = _tiny_repo(tmp_path)
    model = build_system_model(root, base_sha=_base_sha())
    assert model.model_version == MODEL_VERSION
    assert model.base_sha == _base_sha()
    assert model.tcb_registry_sha256 == create_mootos_tcb_registry_v1().registry_sha256
    with pytest.raises(dataclasses.FrozenInstanceError):
        model.model_version = "mutated"
    for name in AUTHORITY_FLAGS:
        assert getattr(model, name) is False


def test_digest_stable_and_order_sensitive(tmp_path):
    root = _tiny_repo(tmp_path)
    first = build_system_model(root, base_sha=_base_sha())
    second = build_system_model(root, base_sha=_base_sha())
    assert first.model_sha256 == second.model_sha256
    assert first.inventory.inventory_sha256 == second.inventory.inventory_sha256
    assert first.canonical_bytes() == second.canonical_bytes()
    # Payload must not embed timestamps. Protected TCB paths are legitimate
    # digest content and one of them is literally named timestamps.py, so
    # strip the path strings first: this asserts "no wall-clock value", not
    # "no filename spelled like one".
    payload = first.canonical_bytes().decode("utf-8")
    for path in create_mootos_tcb_registry_v1().protected_paths:
        payload = payload.replace(path, "")
    assert "timestamp" not in payload
    assert "created_at" not in payload
    assert "mtime" not in payload


def test_forged_model_digest_rejected(tmp_path):
    root = _tiny_repo(tmp_path)
    model = build_system_model(root, base_sha=_base_sha())
    forged = _forge(model, model_sha256="c" * 64)
    with pytest.raises(SystemModelError, match="digest mismatch"):
        SystemModel(
            **{
                field.name: getattr(forged, field.name)
                for field in dataclasses.fields(model)
            }
        )


def test_wrong_model_version_rejected(tmp_path):
    root = _tiny_repo(tmp_path)
    model = build_system_model(root, base_sha=_base_sha())
    forged = _forge(model, model_version="cb-system-model-v999")
    with pytest.raises(SystemModelError):
        SystemModel(
            **{
                field.name: getattr(forged, field.name)
                for field in dataclasses.fields(model)
            }
        )


def test_authority_flag_true_rejected(tmp_path):
    root = _tiny_repo(tmp_path)
    model = build_system_model(root, base_sha=_base_sha())
    forged = _forge(model, publication_authorized=True)
    with pytest.raises(SystemModelError, match="authority"):
        SystemModel(
            **{
                field.name: getattr(forged, field.name)
                for field in dataclasses.fields(model)
            }
        )


def test_tcb_registry_mismatch_fail_closed(tmp_path):
    root = _tiny_repo(tmp_path)
    model = build_system_model(root, base_sha=_base_sha())
    forged = _forge(model, tcb_registry_sha256="d" * 64)
    with pytest.raises(SystemModelError, match="tcb registry digest mismatch"):
        SystemModel(
            **{
                field.name: getattr(forged, field.name)
                for field in dataclasses.fields(model)
            }
        )


def test_snapshot_evidence_only(tmp_path):
    root = _tiny_repo(tmp_path)
    model = build_system_model(root, base_sha=_base_sha())
    snap = create_system_model_snapshot(model)
    assert isinstance(snap, SystemModelSnapshot)
    assert snap.model_sha256 == model.model_sha256
    assert snap.base_sha == model.base_sha
    for name in AUTHORITY_FLAGS:
        assert getattr(snap, name) is False
    with pytest.raises(SystemModelError, match="trusted derived evidence"):
        SystemModelSnapshot(
            model_sha256=model.model_sha256,
            model_version=MODEL_VERSION,
            base_sha=model.base_sha,
            root_fingerprint=model.root_fingerprint,
            tcb_registry_sha256=model.tcb_registry_sha256,
            file_count=1,
            component_count=1,
            edge_count=0,
            uncertainty_count=0,
            snapshot_sha256="e" * 64,
        )


def test_base_sha_binding_required(tmp_path):
    root = _tiny_repo(tmp_path)
    with pytest.raises(SystemModelError, match="base_sha"):
        build_system_model(root, base_sha="not-a-digest")


def test_components_and_files_canonically_ordered(tmp_path):
    root = _tiny_repo(tmp_path)
    model = build_system_model(root, base_sha=_base_sha())
    ids = [item.component_id for item in model.components]
    assert ids == sorted(ids)
    paths = [item.path for item in model.inventory.files]
    assert paths == sorted(paths)
    ownership_paths = [item.path for item in model.ownership]
    assert ownership_paths == sorted(ownership_paths)
