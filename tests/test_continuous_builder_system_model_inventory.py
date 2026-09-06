"""CB-028B — deterministic trusted-repo inventory."""

import os
from pathlib import Path

import pytest

from backend.continuous_builder.system_model import (
    SystemModelError,
    build_repository_inventory,
    build_system_model,
)
from backend.continuous_builder.trusted_policy import create_mootos_tcb_registry_v1


BASE = "a" * 64


def _write(path, text="x\n"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_inventory_deterministic_and_sorted(tmp_path):
    root = tmp_path / "repo"
    _write(root / "b.py", "b\n")
    _write(root / "a.py", "a\n")
    _write(root / "backend" / "m.py", "m\n")
    first = build_repository_inventory(root)
    second = build_repository_inventory(root)
    assert first.inventory_sha256 == second.inventory_sha256
    assert [item.path for item in first.files] == sorted(
        item.path for item in first.files
    )
    assert first.file_count == 3


def test_excludes_git_caches_db_wal_shm_and_duplicates(tmp_path):
    root = tmp_path / "repo"
    _write(root / "keep.py", "keep\n")
    _write(root / ".git" / "config", "secret\n")
    _write(root / "pkg" / "__pycache__" / "x.pyc", "pyc")
    _write(root / "data" / "mootos.db-wal", "wal")
    _write(root / "data" / "mootos.db-shm", "shm")
    _write(root / "node_modules" / "pkg" / "index.js", "js")
    _write(root / "foo 2.py", "dup\n")
    _write(root / "notes 2.md", "dup\n")
    inv = build_repository_inventory(root)
    paths = {item.path for item in inv.files}
    assert "keep.py" in paths
    assert not any(".git" in p for p in paths)
    assert not any("__pycache__" in p for p in paths)
    assert not any("mootos.db-wal" in p for p in paths)
    assert not any("mootos.db-shm" in p for p in paths)
    assert not any("node_modules" in p for p in paths)
    assert "foo 2.py" not in paths
    assert "notes 2.md" not in paths


def test_symlink_file_and_escape_skipped(tmp_path):
    root = tmp_path / "repo"
    outside = tmp_path / "outside.txt"
    outside.write_text("secret\n", encoding="utf-8")
    _write(root / "real.py", "real\n")
    link = root / "link.py"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("symlinks unavailable")
    escape_dir = root / "escape"
    escape_dir.mkdir()
    escape_link = escape_dir / "out"
    try:
        escape_link.symlink_to(tmp_path)
    except OSError:
        pytest.skip("symlinks unavailable")
    inv = build_repository_inventory(root)
    paths = {item.path for item in inv.files}
    assert "real.py" in paths
    assert "link.py" not in paths
    assert not any(p.startswith("escape/") for p in paths)
    assert all(item.content_sha256 for item in inv.files)


def test_tcb_flag_from_canonical_policy_only(tmp_path):
    root = tmp_path / "repo"
    registry = create_mootos_tcb_registry_v1()
    tcb_path = "backend/continuous_builder/trusted_policy.py"
    assert tcb_path in registry.protected_paths
    _write(root / tcb_path, "# fake tcb copy\n")
    _write(root / "backend" / "ordinary.py", "o\n")
    inv = build_repository_inventory(root)
    by_path = {item.path: item for item in inv.files}
    assert by_path[tcb_path].is_tcb is True
    assert by_path["backend/ordinary.py"].is_tcb is False


def test_categories_and_package_hints(tmp_path):
    root = tmp_path / "repo"
    _write(root / "backend" / "continuous_builder" / "__init__.py", "")
    _write(root / "backend" / "continuous_builder" / "mod.py", "x=1\n")
    _write(root / "tests" / "test_x.py", "def test_x():\n    assert True\n")
    _write(root / "scripts" / "tool.py", "print(1)\n")
    _write(root / "docs" / "a.md", "# a\n")
    inv = build_repository_inventory(root)
    by_path = {item.path: item for item in inv.files}
    assert by_path["backend/continuous_builder/__init__.py"].category == (
        "python_package_init"
    )
    assert by_path["backend/continuous_builder/mod.py"].category == "python_module"
    assert by_path["tests/test_x.py"].category == "test"
    assert by_path["scripts/tool.py"].category == "script"
    assert by_path["docs/a.md"].category == "documentation"
    assert (
        by_path["backend/continuous_builder/mod.py"].python_package_hint
        == "backend.continuous_builder"
    )


def test_worker_inventory_not_accepted_only_repo_root(tmp_path):
    # API requires a filesystem root; there is no worker-inventory intake.
    with pytest.raises(SystemModelError):
        build_repository_inventory("")
    with pytest.raises(SystemModelError):
        build_repository_inventory(tmp_path / "missing")


def test_oversized_file_fail_closed(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    big = root / "big.bin"
    big.parent.mkdir(parents=True)
    big.write_bytes(b"x" * 100)
    import backend.continuous_builder.system_model as sm
    monkeypatch.setattr(sm, "MAX_FILE_BYTES", 50)
    with pytest.raises(SystemModelError, match="exceeds bound"):
        build_repository_inventory(root)


def test_inventory_does_not_import_repo_modules(tmp_path):
    root = tmp_path / "repo"
    # Malicious module that would explode if imported/executed.
    _write(
        root / "backend" / "boom.py",
        "raise RuntimeError('executed')\n",
    )
    inv = build_repository_inventory(root)
    assert any(item.path == "backend/boom.py" for item in inv.files)


def test_exact_paths_no_backslash_or_absolute(tmp_path):
    root = tmp_path / "repo"
    _write(root / "ok.py", "ok\n")
    inv = build_repository_inventory(root)
    for item in inv.files:
        assert "\\" not in item.path
        assert not item.path.startswith("/")
        assert ".." not in item.path.split("/")


def test_model_inventory_digest_binds_root(tmp_path):
    a = tmp_path / "a"
    b = tmp_path / "b"
    _write(a / "f.py", "same\n")
    _write(b / "f.py", "same\n")
    ia = build_repository_inventory(a)
    ib = build_repository_inventory(b)
    # Same relative content but different root fingerprints.
    assert ia.root_fingerprint != ib.root_fingerprint
    assert ia.inventory_sha256 != ib.inventory_sha256
