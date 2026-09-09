"""CB-028F adversarial suite — System Model v1 items 1–28."""

import dataclasses
from pathlib import Path

import pytest

from backend.continuous_builder.system_model import (
    AUTHORITY_FLAGS,
    DependencyEdge,
    OwnershipRecord,
    RepositoryFileRecord,
    SystemComponent,
    SystemModel,
    SystemModelError,
    UncertaintyRecord,
    build_repository_inventory,
    build_system_model,
    changed_components,
    component_for_path,
    impacted_components,
    model_tcb_classification,
    system_model_is_descriptive_only,
)
from backend.continuous_builder.trusted_policy import (
    create_mootos_tcb_registry_v1,
    is_tcb_path,
)


BASE = "e" * 64


def _write(path, text="x\n"):
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


def _fields(instance):
    return {
        field.name: getattr(instance, field.name)
        for field in dataclasses.fields(instance)
    }


def test_01_fake_component_cannot_be_trusted(tmp_path):
    with pytest.raises(SystemModelError):
        SystemComponent(
            component_id="evil",
            kind="python_package",
            root_path="evil.py",
            file_paths=("evil.py",),
            ownership_state="owned",
            component_sha256="a" * 64,
        )


def test_02_cannot_override_ownership(tmp_path):
    root = tmp_path / "repo"
    _write(root / "backend" / "a.py", "a\n")
    model = build_system_model(root, base_sha=BASE)
    owned = next(item for item in model.ownership if item.state == "owned")
    forged = _forge(owned, component_id="evil_component")
    with pytest.raises(SystemModelError):
        OwnershipRecord(**_fields(forged))


def test_03_cannot_downgrade_tcb(tmp_path):
    root = tmp_path / "repo"
    path = "backend/continuous_builder/trusted_policy.py"
    _write(root / path, "#\n")
    model = build_system_model(root, base_sha=BASE)
    record = next(item for item in model.inventory.files if item.path == path)
    forged = _forge(record, is_tcb=False)
    with pytest.raises(SystemModelError):
        RepositoryFileRecord(**_fields(forged))
    assert model_tcb_classification(model, path)["is_tcb"] is True


def test_04_normalization_cannot_hide_protected(tmp_path):
    root = tmp_path / "repo"
    path = "backend/continuous_builder/verifier_core.py"
    _write(root / path, "#\n")
    model = build_system_model(root, base_sha=BASE)
    # Non-canonical / dotted forms are rejected or do not hide TCB.
    for probe in (
        "backend/continuous_builder/./verifier_core.py",
        "backend//continuous_builder/verifier_core.py",
    ):
        result = model_tcb_classification(model, probe)
        assert result["state"] == "uncertain" or result["is_tcb"] is True


def test_05_symlink_escape_rejected(tmp_path):
    root = tmp_path / "repo"
    outside = tmp_path / "secret.txt"
    outside.write_text("secret\n", encoding="utf-8")
    _write(root / "ok.py", "ok\n")
    try:
        (root / "leak.py").symlink_to(outside)
        (root / "out").symlink_to(tmp_path)
    except OSError:
        pytest.skip("symlinks unavailable")
    inv = build_repository_inventory(root)
    paths = {item.path for item in inv.files}
    assert "ok.py" in paths
    assert "leak.py" not in paths
    assert not any("secret" in p for p in paths)


def test_06_ambiguous_not_promoted_to_certain(tmp_path):
    root = tmp_path / "repo"
    _write(root / "backend" / "continuous_builder" / "rel.py", "from . import x\n")
    model = build_system_model(root, base_sha=BASE)
    amb = [
        item for item in model.uncertainties
        if item.kind in ("ambiguous_import", "unresolved_import")
    ]
    assert amb
    for edge in model.dependency_edges:
        if edge.kind in ("ambiguous_import", "unresolved_import"):
            assert edge.target_component_id is None


def test_07_unresolved_not_silently_resolved(tmp_path):
    root = tmp_path / "repo"
    _write(
        root / "backend" / "m.py",
        "import totally_unknown_pkg_zzz\nfrom . import relative_mystery\n",
    )
    model = build_system_model(root, base_sha=BASE)
    # External unknown top-level stays external (not silently internalized).
    ext = [
        edge for edge in model.dependency_edges
        if edge.imported_name == "totally_unknown_pkg_zzz"
    ]
    assert ext
    assert ext[0].kind == "external_import"
    assert ext[0].target_component_id is None
    # Relative import remains unresolved/ambiguous — never silently resolved.
    rel = [
        edge for edge in model.dependency_edges
        if edge.imported_name.startswith(".")
    ]
    assert rel
    assert all(
        edge.kind in ("unresolved_import", "ambiguous_import")
        and edge.target_component_id is None
        for edge in rel
    )
    assert any(
        item.kind in ("unresolved_import", "ambiguous_import")
        for item in model.uncertainties
    )


def test_08_model_cannot_authorize_queue_pub_github_main(tmp_path):
    root = tmp_path / "repo"
    _write(root / "a.py", "a\n")
    model = build_system_model(root, base_sha=BASE)
    for name in AUTHORITY_FLAGS:
        assert getattr(model, name) is False
    forged = _forge(model, merge_authorized=True, github_authorized=True)
    with pytest.raises(SystemModelError, match="authority"):
        SystemModel(**_fields(forged))


def test_09_stale_model_cannot_replay_other_repo(tmp_path):
    a = tmp_path / "a"
    b = tmp_path / "b"
    _write(a / "f.py", "same\n")
    _write(b / "f.py", "same\n")
    ma = build_system_model(a, base_sha=BASE)
    mb = build_system_model(b, base_sha=BASE)
    assert ma.root_fingerprint != mb.root_fingerprint
    assert ma.model_sha256 != mb.model_sha256
    # Rebinding model A with B's fingerprint fails seal.
    forged = _forge(ma, root_fingerprint=mb.root_fingerprint)
    with pytest.raises(SystemModelError):
        SystemModel(**_fields(forged))


def test_10_ordering_change_changes_digest(tmp_path):
    root = tmp_path / "repo"
    _write(root / "a.py", "a\n")
    _write(root / "b.py", "b\n")
    model = build_system_model(root, base_sha=BASE)
    # Reverse component order breaks canonicality.
    if len(model.components) >= 2:
        reversed_components = tuple(reversed(model.components))
        forged = _forge(model, components=reversed_components)
        with pytest.raises(SystemModelError):
            SystemModel(**_fields(forged))
    else:
        # Inventory order break
        reversed_files = tuple(reversed(model.inventory.files))
        from backend.continuous_builder.system_model import RepositoryInventory
        inv = model.inventory
        forged_inv = _forge(inv, files=reversed_files)
        with pytest.raises(SystemModelError):
            RepositoryInventory(**_fields(forged_inv))


def test_11_duplicate_case_ambiguous_truth_rejected(tmp_path):
    root = tmp_path / "repo"
    _write(root / "A.py", "a\n")
    # On case-sensitive FS we can create both; on macOS default may collide.
    try:
        _write(root / "a.py", "b\n")
    except Exception:
        pytest.skip("case-insensitive filesystem")
    # If both exist as distinct paths, inventory must fail closed on casefold.
    try:
        build_repository_inventory(root)
    except SystemModelError as error:
        assert "case" in str(error).lower() or "canonical" in str(error).lower()
    else:
        # Case-insensitive FS collapsed to one file — still deterministic.
        inv = build_repository_inventory(root)
        assert len({item.path.casefold() for item in inv.files}) == len(inv.files)


def test_12_inventory_does_not_execute_code(tmp_path):
    root = tmp_path / "repo"
    _write(root / "bomb.py", "raise SystemExit('executed')\n")
    inv = build_repository_inventory(root)
    assert any(item.path == "bomb.py" for item in inv.files)


def test_13_no_network_or_creds_in_model_surface():
    import backend.continuous_builder.system_model as sm
    src = Path(sm.__file__).read_text(encoding="utf-8")
    for banned in (
        "requests.",
        "urllib.request",
        "socket.",
        "http.client",
        "subprocess",
    ):
        assert banned not in src
    for banned in ("API_KEY", "SECRET", "PASSWORD", "Bearer ", "aws_secret"):
        assert banned not in src
    # Construction tokens are in-process integrity controls, not credentials.
    assert "_MODEL_TOKEN" in src


def test_14_unbounded_work_rejected(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    _write(root / "a.py", "a\n")
    _write(root / "b.py", "b\n")
    import backend.continuous_builder.system_model as sm
    monkeypatch.setattr(sm, "MAX_FILES", 1)
    with pytest.raises(SystemModelError, match="exceeds"):
        build_repository_inventory(root)


def test_15_unknown_does_not_become_pass_or_safe(tmp_path):
    root = tmp_path / "repo"
    _write(root / "a.py", "a\n")
    model = build_system_model(root, base_sha=BASE)
    assessment = impacted_components(model, ("missing.py",))
    assert assessment.impact_state in ("unknown", "possible_impact")
    assert assessment.impact_state not in ("SAFE", "PASS", "not_impacted")


def test_16_does_not_weaken_cb027():
    registry = create_mootos_tcb_registry_v1()
    assert len(registry.protected_paths) == 28
    assert registry.registry_sha256 == (
        "89faaa9cab36a21d33c792f8692a9f9982c4e83587ac2e9d1c1d64ff117b47eb"
    )
    assert system_model_is_descriptive_only() is True
    assert not is_tcb_path("backend/continuous_builder/system_model.py")


def test_17_traversal_paths_rejected(tmp_path):
    root = tmp_path / "repo"
    _write(root / "a.py", "a\n")
    model = build_system_model(root, base_sha=BASE)
    assert component_for_path(model, "../outside.py") == "UNKNOWN"
    assert model_tcb_classification(model, "../../etc/passwd")["state"] == (
        "uncertain"
    )


def test_18_absolute_paths_rejected(tmp_path):
    root = tmp_path / "repo"
    _write(root / "a.py", "a\n")
    model = build_system_model(root, base_sha=BASE)
    assert component_for_path(model, "/etc/passwd") == "UNKNOWN"


def test_19_no_worker_inventory_intake_api():
    import backend.continuous_builder.system_model as sm
    assert not hasattr(sm, "accept_worker_inventory")
    assert not hasattr(sm, "from_worker_manifest")


def test_20_missing_protected_paths_detected(tmp_path):
    root = tmp_path / "repo"
    _write(root / "only.py", "o\n")
    model = build_system_model(root, base_sha=BASE)
    missing = [
        item for item in model.uncertainties
        if item.kind == "missing_protected_path"
    ]
    assert len(missing) == 28


def test_21_malformed_registry_digest_fail_closed(tmp_path):
    root = tmp_path / "repo"
    _write(root / "a.py", "a\n")
    model = build_system_model(root, base_sha=BASE)
    forged = _forge(model, tcb_registry_sha256="0" * 64)
    with pytest.raises(SystemModelError):
        SystemModel(**_fields(forged))


def test_22_no_timestamps_in_digests(tmp_path):
    root = tmp_path / "repo"
    _write(root / "a.py", "a\n")
    model = build_system_model(root, base_sha=BASE)
    text = model.canonical_bytes().decode("utf-8")
    # Protected TCB paths are legitimate digest content, and one of them is
    # literally named timestamps.py. Strip the path strings first so this
    # still asserts "no wall-clock value", not "no filename spelled like one".
    for path in create_mootos_tcb_registry_v1().protected_paths:
        text = text.replace(path, "")
    for needle in ("timestamp", "created_at", "mtime", "ctime", "time.time"):
        assert needle not in text


def test_23_cannot_supply_alternate_tcb_registry(tmp_path):
    root = tmp_path / "repo"
    _write(root / "a.py", "a\n")
    # build_system_model has no registry= kwarg
    with pytest.raises(TypeError):
        build_system_model(root, base_sha=BASE, registry=object())


def test_24_dot_segment_hide_rejected(tmp_path):
    root = tmp_path / "repo"
    _write(root / "backend" / "continuous_builder" / "verifier_core.py", "#\n")
    model = build_system_model(root, base_sha=BASE)
    result = model_tcb_classification(
        model, "backend/continuous_builder/../continuous_builder/verifier_core.py"
    )
    # canonicalize would normalize, but our API requires already-canonical.
    assert result["state"] == "uncertain"


def test_25_forged_edge_digest_rejected(tmp_path):
    root = tmp_path / "repo"
    _write(root / "backend" / "a.py", "import json\n")
    model = build_system_model(root, base_sha=BASE)
    if not model.dependency_edges:
        pytest.skip("no edges")
    edge = model.dependency_edges[0]
    forged = _forge(edge, edge_sha256="1" * 64)
    with pytest.raises(SystemModelError):
        DependencyEdge(**_fields(forged))


def test_26_huge_file_bounded(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    big = root / "big.bin"
    big.parent.mkdir(parents=True)
    big.write_bytes(b"x" * 200)
    import backend.continuous_builder.system_model as sm
    monkeypatch.setattr(sm, "MAX_FILE_BYTES", 100)
    with pytest.raises(SystemModelError, match="exceeds bound"):
        build_repository_inventory(root)


def test_27_external_dep_stays_external(tmp_path):
    root = tmp_path / "repo"
    _write(root / "backend" / "a.py", "import hashlib\nimport json\n")
    model = build_system_model(root, base_sha=BASE)
    for edge in model.dependency_edges:
        if edge.imported_name in ("hashlib", "json"):
            assert edge.kind == "external_import"
            assert edge.target_component_id is None


def test_28_impact_uncertain_when_graph_incomplete(tmp_path):
    root = tmp_path / "repo"
    _write(
        root / "backend" / "continuous_builder" / "x.py",
        "from . import mystery\n",
    )
    model = build_system_model(root, base_sha=BASE)
    assessment = impacted_components(
        model, ("backend/continuous_builder/x.py",)
    )
    assert assessment.impact_state in ("possible_impact", "impacted", "unknown")
    # Relative import uncertainty should appear somewhere.
    assert assessment.uncertain_subjects or any(
        item.kind in ("ambiguous_import", "unresolved_import")
        for item in model.uncertainties
    )
