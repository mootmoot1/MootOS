import ast
from dataclasses import FrozenInstanceError, replace
from pathlib import Path

import pytest

from backend.continuous_builder.sandbox_repository import (
    DisposableRepositoryPlan,
    RepositoryManifestEntry,
    SandboxRepositoryError,
    create_disposable_repository_plan,
    create_repository_source_evidence,
)
from tests.test_continuous_builder_worker_request import _request


def _entry(path="backend/widget.py", **changes):
    values = {
        "path": path,
        "entry_type": "regular_file",
        "content_sha256": "a" * 64,
        "size_bytes": 100,
        "executable": False,
    }
    values.update(changes)
    return RepositoryManifestEntry(**values)


def _source(request=None, entries=None, **changes):
    request = request or _request()
    values = {
        "repository_id": "mootos-source",
        "pinned_base_sha": request.job.base_sha,
        "manifest_entries": entries or (_entry(),),
    }
    values.update(changes)
    return create_repository_source_evidence(**values)


def _plan(request=None, source=None, **changes):
    request = request or _request()
    source = source or _source(request)
    values = {
        "worker_request": request,
        "source_evidence": source,
        "disposable_workspace_id": "disposable-attempt-1",
    }
    values.update(changes)
    return create_disposable_repository_plan(**values)


def test_plan_binds_exact_request_base_scope_and_disposable_source():
    plan = _plan()
    assert plan.pinned_base_sha == plan.worker_request.job.base_sha
    assert plan.request_digest == plan.worker_request.request_digest
    assert plan.scope_digest == plan.worker_request.scope_digest
    assert plan.workspace_disposable is True
    assert plan.source_read_only is True
    assert plan.shared_git_directory is False
    assert plan.git_hooks_enabled is False
    assert plan.host_repository_writable is False
    assert plan.launch_authorized is False
    assert plan.materialized is False


def test_base_sha_and_bound_identity_mutations_fail_closed():
    plan = _plan()
    for name, value in (
        ("pinned_base_sha", "b" * 40),
        ("request_digest", "0" * 64),
        ("blueprint_digest", "0" * 64),
        ("slice_digest", "0" * 64),
        ("scope_digest", "0" * 64),
        ("plan_sha256", "0" * 64),
    ):
        with pytest.raises(SandboxRepositoryError):
            replace(plan, **{name: value})


@pytest.mark.parametrize(
    "path",
    (
        ".git/config",
        ".GIT/hooks/pre-commit",
        ".gitmodules",
        "../escape",
        "/absolute/path",
        "C:/windows/path",
        "folder\\ambiguous",
        "folder/../../escape",
        "folder/./ambiguous",
        "folder//ambiguous",
        "~/host-home",
    ),
)
def test_git_metadata_path_escape_and_host_path_leakage_rejected(path):
    with pytest.raises(SandboxRepositoryError):
        _entry(path)


@pytest.mark.parametrize(
    "entry_type", ("symlink", "submodule", "archive", "device")
)
def test_symlink_and_dangerous_entry_types_rejected(entry_type):
    with pytest.raises(SandboxRepositoryError, match="regular files"):
        _entry(entry_type=entry_type)


def test_duplicate_case_and_unicode_path_collisions_fail_closed():
    with pytest.raises(SandboxRepositoryError, match="collide"):
        _source(entries=(_entry("A.py"), _entry("a.py")))
    with pytest.raises(SandboxRepositoryError, match="collide"):
        _source(entries=(_entry("K.py"), _entry("K.py")))


def test_manifest_order_is_canonical_and_digest_is_stable():
    request = _request()
    first = _source(
        request, entries=(_entry("z.py"), _entry("a.py"))
    )
    second = _source(
        request, entries=(_entry("a.py"), _entry("z.py"))
    )
    assert first == second
    assert first.manifest_sha256 == second.manifest_sha256
    assert _plan(request, first).canonical_bytes() == _plan(
        request, second
    ).canonical_bytes()


def test_manifest_bounds_malformed_workspace_and_modes_rejected():
    with pytest.raises(SandboxRepositoryError):
        _entry(size_bytes=64 * 1024 * 1024 + 1)
    with pytest.raises(SandboxRepositoryError):
        _source(entries="files")
    with pytest.raises(SandboxRepositoryError):
        _plan(disposable_workspace_id="/tmp/host-workspace")
    with pytest.raises(SandboxRepositoryError):
        _plan(disposable_workspace_id="shared-workspace")
    with pytest.raises(SandboxRepositoryError):
        _plan(materialization_mode="git_worktree")


def test_plan_is_immutable_and_cannot_claim_materialization_or_authority():
    plan = _plan()
    assert isinstance(plan, DisposableRepositoryPlan)
    assert len(plan.canonical_bytes()) < 512 * 1024
    with pytest.raises(FrozenInstanceError):
        plan.materialized = True
    for name, value in (
        ("shared_git_directory", True),
        ("git_hooks_enabled", True),
        ("inherited_git_config", True),
        ("host_repository_writable", True),
        ("symlinks_allowed", True),
        ("host_workspace_reused", True),
        ("launch_authorized", True),
        ("materialized", True),
    ):
        with pytest.raises(SandboxRepositoryError):
            replace(plan, **{name: value})


def test_module_has_no_filesystem_process_network_or_git_execution():
    source = Path(
        "backend/continuous_builder/sandbox_repository.py"
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
        "kubernetes", "paramiko", "fabric", "pexpect", "os", "pathlib",
        "shutil", "git",
    }
