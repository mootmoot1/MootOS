"""Focused tests for V0.4A Slice 2 scope, workspace, and brief."""

import ast
import json
from pathlib import Path

import pytest

from scripts.capability_build.brief import render_worker_brief
from scripts.capability_build.job import new_job
from scripts.capability_build.scope import FrozenScope, ScopeError
from scripts.capability_build.workspace import (
    WorkspaceError,
    create_workspace_dirs,
    plan_workspace_paths,
)


SPEC_SHA256 = "a" * 64
BASE_SHA = "be386fa"
JOB_ID = "slice-2-test-job"


def _job():
    return new_job(
        "projects.insight",
        SPEC_SHA256,
        BASE_SHA,
        actor="human:tester",
        note="Approve Slice 2 fixture",
        job_id=JOB_ID,
    )


def _scope():
    return FrozenScope(
        allowed_new_files=(
            "tests/test_widget.py",
            "backend/tools_widget.py",
        ),
        allowed_existing_files=("backend/widgets.py",),
        protected_files=("ops/protected/**",),
        forbidden_paths=("private/**",),
        justifications={
            "tests/test_widget.py": "Add focused regression coverage.",
            "backend/tools_widget.py": "Add the approved tool adapter.",
            "backend/widgets.py": "Expose the existing domain query.",
        },
    )


def test_frozen_scope_round_trips_and_has_stable_ordering():
    scope = _scope()
    data = scope.to_dict()
    loaded = FrozenScope.from_dict(json.loads(json.dumps(data)))

    assert loaded.to_dict() == data
    assert loaded.allowed_new_files == (
        "backend/tools_widget.py",
        "tests/test_widget.py",
    )
    assert list(loaded.justifications) == list(
        loaded.allowed_new_files + loaded.allowed_existing_files
    )


@pytest.mark.parametrize(
    "unsafe_path",
    [
        "/absolute/file.py",
        "../escape.py",
        "safe/../../escape.py",
        "C:\\absolute\\file.py",
        "safe/./file.py",
    ],
)
def test_frozen_scope_rejects_unsafe_paths(unsafe_path):
    with pytest.raises(ScopeError):
        FrozenScope(
            allowed_new_files=(unsafe_path,),
            justifications={unsafe_path: "Must be rejected."},
        )


def test_paths_are_normalized_to_forward_slashes():
    scope = FrozenScope(
        allowed_new_files=("frontend\\widget.js",),
        justifications={
            "frontend\\widget.js": "Add the approved frontend module."
        },
    )
    assert scope.allowed_new_files == ("frontend/widget.js",)
    assert scope.can_create("frontend/widget.js") is True


@pytest.mark.parametrize("note", [None, "", "   "])
def test_every_allowed_path_requires_a_non_blank_justification(note):
    justifications = {} if note is None else {"frontend/widget.js": note}
    with pytest.raises(ScopeError, match="justification"):
        FrozenScope(
            allowed_new_files=("frontend/widget.js",),
            justifications=justifications,
        )


@pytest.mark.parametrize(
    "allowed,denied_field,denied",
    [
        (
            "private/new.py",
            "forbidden_paths",
            ("private/**",),
        ),
        (
            "ops/protected/config.py",
            "protected_files",
            ("ops/protected/**",),
        ),
        (
            "backend/tool_registry.py",
            "protected_files",
            (),
        ),
        (
            "data/generated.json",
            "forbidden_paths",
            (),
        ),
    ],
)
def test_allowed_scope_cannot_overlap_forbidden_or_protected(
    allowed, denied_field, denied
):
    arguments = {
        "allowed_new_files": (allowed,),
        "justifications": {allowed: "Invalid overlap."},
        denied_field: denied,
    }
    with pytest.raises(ScopeError, match="overlaps denied"):
        FrozenScope(**arguments)


def test_create_and_modify_decisions_are_distinct_and_fail_closed():
    scope = _scope()

    assert scope.can_create("backend/tools_widget.py") is True
    assert scope.can_modify("backend/tools_widget.py") is False
    assert scope.can_modify("backend/widgets.py") is True
    assert scope.can_create("backend/widgets.py") is False
    assert scope.can_create("backend/other.py") is False
    assert scope.can_create("Backend/tools_widget.py") is False
    assert "approved only for create" in scope.explain_modify(
        "backend/tools_widget.py"
    )
    assert "outside the frozen approved scope" in scope.explain_create(
        "backend/other.py"
    )


def test_allowed_patterns_are_bounded_and_do_not_match_case_variants():
    scope = FrozenScope(
        allowed_new_files=("frontend/widgets/*.js",),
        justifications={
            "frontend/widgets/*.js": "Add approved widget modules."
        },
    )

    assert scope.can_create("frontend/widgets/panel.js") is True
    assert scope.can_create("frontend/widgets/nested/panel.js") is False
    assert scope.can_create("frontend/widgets/PANEL.JS") is False


def test_env_example_remains_the_documented_secret_pattern_exception():
    scope = FrozenScope(
        allowed_existing_files=(".env.example",),
        justifications={
            ".env.example": "Document a non-secret configuration name."
        },
    )

    assert scope.can_modify(".env.example") is True
    assert scope.is_forbidden(".env.local") is True


def test_forbidden_and_protected_decisions_explain_the_matching_rule():
    scope = _scope()

    protected = scope.decision_for_modify("ops/protected/config.py")
    forbidden = scope.decision_for_create("private/new.py")

    assert protected.allowed is False
    assert protected.category == "protected"
    assert protected.matched_rule == "ops/protected/**"
    assert "protected rule" in protected.explanation
    assert forbidden.allowed is False
    assert forbidden.category == "forbidden"
    assert forbidden.matched_rule == "private/**"
    assert "forbidden rule" in forbidden.explanation
    assert scope.is_forbidden_or_protected("data/mootos.db") is True


def test_workspace_paths_are_deterministic_and_nested_under_the_job():
    first = plan_workspace_paths(JOB_ID)
    second = plan_workspace_paths(JOB_ID)

    assert first == second
    assert first.job_root == Path("build_jobs") / JOB_ID
    assert first.workspace == first.job_root / "workspace"
    assert first.source == first.workspace / "source"
    assert first.returned == first.workspace / "returned"
    assert first.evidence == first.workspace / "evidence"
    assert first.brief == first.workspace / "brief.md"


@pytest.mark.parametrize(
    "job_id", ["../escape", "/absolute", "", ".hidden"]
)
def test_workspace_planning_rejects_unsafe_job_ids(job_id):
    with pytest.raises(WorkspaceError):
        plan_workspace_paths(job_id)


def test_create_workspace_dirs_only_makes_expected_empty_dirs(tmp_path):
    build_root = tmp_path / "build_jobs"
    paths = create_workspace_dirs(JOB_ID, build_root)

    assert paths.workspace.is_dir()
    assert paths.source.is_dir()
    assert paths.returned.is_dir()
    assert paths.evidence.is_dir()
    assert not paths.brief.exists()
    assert list(paths.source.iterdir()) == []
    assert list(paths.returned.iterdir()) == []
    assert list(paths.evidence.iterdir()) == []
    assert sorted(item.name for item in paths.workspace.iterdir()) == [
        "evidence",
        "returned",
        "source",
    ]
    with pytest.raises(WorkspaceError, match="already exists"):
        create_workspace_dirs(JOB_ID, build_root)


def test_worker_brief_is_deterministic_and_contains_all_safety_contracts():
    job = _job()
    scope = _scope()
    goal = "Add a bounded project insight helper."
    constraints = (
        "Run only the requested focused tests.",
        "Keep the implementation offline.",
    )

    first = render_worker_brief(job, scope, goal, constraints)
    second = render_worker_brief(job, scope, goal, constraints)

    assert first == second
    for identifier in (
        job.job_id,
        job.capability_id,
        job.base_sha,
        job.spec_sha256,
        str(job.fix_round),
    ):
        assert identifier in first
    for path in (
        *scope.allowed_new_files,
        *scope.allowed_existing_files,
        *scope.protected_files,
        *scope.forbidden_paths,
    ):
        assert path in first
    for instruction in (
        "Do not touch anything outside scope.",
        "Do not read or expose secrets.",
        "Do not modify `data/`.",
        "Do not commit, push, merge, or deploy.",
        "Summary of implementation",
        "Changed files",
        "Tests run with exact results",
        "Risks or questions",
    ):
        assert instruction in first


def test_slice_2_modules_import_no_runtime_or_execution_authority():
    repo_root = Path(__file__).parents[1]
    forbidden_modules = {
        "backend",
        "git",
        "pygit2",
        "dulwich",
        "subprocess",
    }
    for relative in (
        "scripts/capability_build/scope.py",
        "scripts/capability_build/workspace.py",
        "scripts/capability_build/brief.py",
    ):
        tree = ast.parse((repo_root / relative).read_text(encoding="utf-8"))
        imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imports.append(node.module or "")
        assert not any(
            imported.split(".")[0] in forbidden_modules
            for imported in imports
        ), relative
