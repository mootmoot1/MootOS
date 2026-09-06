"""CB-028D — TCB integration via canonical trusted-policy only."""

from pathlib import Path

import pytest

from backend.continuous_builder.system_model import (
    SystemModel,
    SystemModelError,
    build_system_model,
    model_tcb_classification,
    system_model_is_descriptive_only,
)
from backend.continuous_builder.trusted_policy import (
    create_mootos_tcb_registry_v1,
    is_tcb_path,
)
import dataclasses


BASE = "c" * 64


def _write(path, text="#\n"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _forge(instance, **changes):
    forged = object.__new__(type(instance))
    for item in dataclasses.fields(instance):
        object.__setattr__(
            forged,
            item.name,
            changes.get(item.name, getattr(instance, item.name)),
        )
    return forged


def test_trust_review_system_model_stays_outside_tcb():
    """Descriptive evidence only — no enforcement power — not in TCB."""
    assert system_model_is_descriptive_only() is True
    registry = create_mootos_tcb_registry_v1()
    assert len(registry.protected_paths) == 12
    path = "backend/continuous_builder/system_model.py"
    assert path not in registry.protected_paths
    assert is_tcb_path(path) is False


def test_file_tcb_membership_binds_registry_digest(tmp_path):
    root = tmp_path / "repo"
    registry = create_mootos_tcb_registry_v1()
    for path in registry.protected_paths:
        _write(root / path, "# protected\n")
    _write(root / "backend" / "ordinary.py", "x=1\n")
    model = build_system_model(root, base_sha=BASE)
    assert model.tcb_registry_sha256 == registry.registry_sha256
    by_path = {item.path: item for item in model.inventory.files}
    for path in registry.protected_paths:
        assert by_path[path].is_tcb is True
    assert by_path["backend/ordinary.py"].is_tcb is False
    hit = model_tcb_classification(
        model, "backend/continuous_builder/verifier_core.py"
    )
    assert hit["is_tcb"] is True
    assert hit["state"] == "tcb"
    assert hit["registry_sha256"] == registry.registry_sha256
    miss = model_tcb_classification(model, "backend/ordinary.py")
    assert miss["is_tcb"] is False
    assert miss["state"] == "non_tcb"


def test_missing_protected_paths_detected(tmp_path):
    root = tmp_path / "repo"
    _write(root / "backend" / "ordinary.py", "x=1\n")
    # Omit all TCB paths.
    model = build_system_model(root, base_sha=BASE)
    missing = [
        item for item in model.uncertainties
        if item.kind == "missing_protected_path"
    ]
    registry = create_mootos_tcb_registry_v1()
    assert len(missing) == len(registry.protected_paths)
    subjects = {item.subject for item in missing}
    assert subjects == set(registry.protected_paths)


def test_registry_mismatch_fail_closed_on_model(tmp_path):
    root = tmp_path / "repo"
    _write(root / "a.py", "a\n")
    model = build_system_model(root, base_sha=BASE)
    forged = _forge(model, tcb_registry_sha256="f" * 64)
    with pytest.raises(SystemModelError, match="tcb registry digest mismatch"):
        SystemModel(
            **{
                field.name: getattr(forged, field.name)
                for field in dataclasses.fields(model)
            }
        )


def test_classification_uncertain_on_stale_model_registry(tmp_path):
    root = tmp_path / "repo"
    _write(root / "backend" / "continuous_builder" / "verifier_core.py", "x\n")
    model = build_system_model(root, base_sha=BASE)
    # Simulate stale binding without reconstructing (bypass seal via forge
    # only for the query helper input shape — helper checks live registry).
    stale = _forge(model, tcb_registry_sha256="a" * 64)
    # Do not re-enter SystemModel ctor; query helper accepts instance fields.
    result = model_tcb_classification(
        stale, "backend/continuous_builder/verifier_core.py"
    )
    assert result["state"] == "uncertain"
    assert result["detail_code"] == "tcb_registry_mismatch"
    assert result["is_tcb"] is None


def test_cannot_downgrade_protected_via_worker_metadata(tmp_path):
    root = tmp_path / "repo"
    path = "backend/continuous_builder/trusted_policy.py"
    _write(root / path, "# tcb\n")
    model = build_system_model(root, base_sha=BASE)
    record = next(item for item in model.inventory.files if item.path == path)
    assert record.is_tcb is True
    # Forging is_tcb False on a file record cannot pass seal.
    forged_file = _forge(record, is_tcb=False)
    with pytest.raises(SystemModelError):
        from backend.continuous_builder.system_model import RepositoryFileRecord
        RepositoryFileRecord(
            **{
                field.name: getattr(forged_file, field.name)
                for field in dataclasses.fields(record)
            }
        )
    # Classification always defers to live registry for protected hits.
    hit = model_tcb_classification(model, path)
    assert hit["is_tcb"] is True
    assert hit["change_policy"] == "human_only"


def test_malformed_path_classification_uncertain(tmp_path):
    root = tmp_path / "repo"
    _write(root / "a.py", "a\n")
    model = build_system_model(root, base_sha=BASE)
    result = model_tcb_classification(model, "../escape.py")
    assert result["state"] == "uncertain"
    assert result["is_tcb"] is None


def test_cb027_registry_unchanged():
    registry = create_mootos_tcb_registry_v1()
    assert len(registry.protected_paths) == 12
    assert registry.registry_sha256 == (
        "b7a686ac087f4d1756d7a28293301e430221b77a4d16e07ee89ace85cbb7f3d4"
    )
