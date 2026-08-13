"""Filesystem path planning for V0.4A Slice 2 workspaces.

No Git or subprocess operation exists here. Directory creation is explicit
and creates only the empty workspace directory skeleton.
"""

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class WorkspaceError(ValueError):
    """Raised for an unsafe workspace path or creation request."""


_JOB_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


@dataclass(frozen=True)
class WorkspacePaths:
    """Deterministic paths for one build job's workspace skeleton."""

    build_root: Path
    job_root: Path
    workspace: Path
    source: Path
    returned: Path
    evidence: Path
    brief: Path


def _safe_build_root(value: Any) -> Path:
    try:
        raw = os.fspath(value)
    except TypeError as error:
        raise WorkspaceError("build_root must be path-like") from error
    if not isinstance(raw, str) or not raw:
        raise WorkspaceError("build_root must be a non-empty path")
    if "\x00" in raw:
        raise WorkspaceError("build_root cannot contain a NUL byte")
    root = Path(raw)
    if ".." in root.parts:
        raise WorkspaceError("build_root cannot contain parent traversal")
    return root


def _safe_job_id(job_id: Any) -> str:
    if not isinstance(job_id, str) or not _JOB_ID_PATTERN.fullmatch(job_id):
        raise WorkspaceError("Unsafe job_id for workspace path")
    return job_id


def plan_workspace_paths(
    job_id: str, build_root: Any = "build_jobs"
) -> WorkspacePaths:
    """Compute, without creating, the fixed paths for one job workspace."""
    root = _safe_build_root(build_root)
    safe_job_id = _safe_job_id(job_id)
    job_root = root / safe_job_id
    workspace = job_root / "workspace"
    return WorkspacePaths(
        build_root=root,
        job_root=job_root,
        workspace=workspace,
        source=workspace / "source",
        returned=workspace / "returned",
        evidence=workspace / "evidence",
        brief=workspace / "brief.md",
    )


def create_workspace_dirs(
    job_id: str, build_root: Any = "build_jobs"
) -> WorkspacePaths:
    """Create only the empty source, returned, and evidence directories."""
    paths = plan_workspace_paths(job_id, build_root)
    root_resolved = paths.build_root.resolve(strict=False)
    workspace_resolved = paths.workspace.resolve(strict=False)
    try:
        workspace_resolved.relative_to(root_resolved)
    except ValueError as error:
        raise WorkspaceError("Workspace path escapes build_root") from error
    if paths.workspace.exists():
        raise WorkspaceError("Workspace already exists")

    paths.workspace.mkdir(parents=True, exist_ok=False)
    for directory in (paths.source, paths.returned, paths.evidence):
        directory.mkdir()
    return paths
