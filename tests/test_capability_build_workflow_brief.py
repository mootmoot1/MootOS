"""Tests for V0.4B Slice 7 guarded workflow-to-brief rendering."""

import ast
import json
from dataclasses import FrozenInstanceError, replace
from pathlib import Path

import pytest

from scripts.capability_build.brief import render_worker_brief
from scripts.capability_build.job_binding import BuildJobBinding
from scripts.capability_build.request import CapabilityBuildRequest
from scripts.capability_build.request_workflow import (
    start_workflow_from_request,
)
from scripts.capability_build.workflow import (
    STEP_BRIEF_READY,
    STEP_JOB_CREATED,
    STEP_REQUEST_RECEIVED,
    STEP_SCOPE_FROZEN,
    STEP_WORKER_RETURNED,
)
from scripts.capability_build.workflow_brief import (
    MAX_WORKFLOW_BRIEF_SUMMARY_BYTES,
    STATUS_BRIEF_READY,
    STATUS_NOT_READY,
    WorkflowBriefError,
    WorkflowBriefReady,
    render_brief_from_workflow_scope,
)
from scripts.capability_build.workflow_job import (
    create_job_from_workflow_start,
)
from scripts.capability_build.workflow_scope import (
    freeze_scope_from_workflow_job,
)


SPEC_SHA256 = "a" * 64
BASE_SHA = "b" * 40
RAW_REQUEST_GOAL = "RAW_REQUEST_GOAL_MUST_NOT_APPEAR"
RAW_REQUEST_BEHAVIOR = "RAW_REQUEST_BEHAVIOR_MUST_NOT_APPEAR"
RAW_REQUEST_CONSTRAINT = "RAW_REQUEST_CONSTRAINT_MUST_NOT_APPEAR"
RAW_BINDING_NOTE = "RAW_BINDING_NOTE_MUST_NOT_APPEAR"
RAW_JUSTIFICATION = "RAW_JUSTIFICATION_MUST_NOT_APPEAR"
APPROVED_GOAL = "EXPLICIT_APPROVED_BRIEF_GOAL"
APPROVED_CONSTRAINT = "EXPLICIT_APPROVED_BRIEF_CONSTRAINT"


def _request(**overrides):
    values = {
        "request_id": "request-007",
        "capability_name": "Project insight",
        "user_goal": RAW_REQUEST_GOAL,
        "requested_behavior_summary": RAW_REQUEST_BEHAVIOR,
        "constraints": (RAW_REQUEST_CONSTRAINT,),
    }
    values.update(overrides)
    return CapabilityBuildRequest(**values)


def _binding(**overrides):
    values = {
        "job_id": "job-v04b-slice-7",
        "capability_id": "projects.insight",
        "spec_sha256": SPEC_SHA256,
        "base_sha": BASE_SHA,
        "actor": "human:reviewer",
        "note": RAW_BINDING_NOTE,
    }
    values.update(overrides)
    return BuildJobBinding(**values)


def _scope_data(**overrides):
    values = {
        "allowed_new_files": ("frontend/widgets/panel.js",),
        "allowed_existing_files": ("frontend/app.js",),
        "protected_files": ("ops/protected/**",),
        "forbidden_paths": ("private/**",),
        "justifications": {
            "frontend/widgets/panel.js": RAW_JUSTIFICATION,
            "frontend/app.js": "Update the approved entrypoint.",
        },
    }
    values.update(overrides)
    return values


def _scope_freeze(
    request_overrides=None,
    binding_overrides=None,
    scope_data=None,
):
    request = _request(**(request_overrides or {}))
    start = start_workflow_from_request(request)
    binding = _binding(**(binding_overrides or {}))
    creation = create_job_from_workflow_start(start, binding)
    approved_scope = _scope_data() if scope_data is None else scope_data
    return freeze_scope_from_workflow_job(creation, approved_scope)


def _render(scope_freeze=None, goal=APPROVED_GOAL, constraints=None):
    actual_scope = scope_freeze or _scope_freeze()
    actual_constraints = (
        (APPROVED_CONSTRAINT,) if constraints is None else constraints
    )
    return render_brief_from_workflow_scope(
        actual_scope,
        goal,
        actual_constraints,
    )


def test_frozen_scope_and_approved_input_render_worker_brief():
    scope_freeze = _scope_freeze()

    result = _render(scope_freeze)

    assert isinstance(result, WorkflowBriefReady)
    assert result.schema_version == 1
    assert result.status == STATUS_BRIEF_READY
    assert result.ready is True
    assert result.blocking_reasons == ()
    assert isinstance(result.brief, str)
    assert result.brief == render_worker_brief(
        scope_freeze.creation.job,
        scope_freeze.scope,
        APPROVED_GOAL,
        (APPROVED_CONSTRAINT,),
    )
    assert result.offline_only is True
    assert result.autonomous is False
    assert result.runtime_authority is False


def test_worker_brief_identity_matches_created_job():
    scope_freeze = _scope_freeze()

    result = _render(scope_freeze)

    job = scope_freeze.creation.job
    assert result.job_id == job.job_id
    assert result.capability_id == job.capability_id
    assert result.spec_sha256 == job.spec_sha256
    assert result.base_sha == job.base_sha
    for value in (
        job.job_id,
        job.capability_id,
        job.spec_sha256,
        job.base_sha,
        str(job.fix_round),
    ):
        assert value in result.brief


def test_worker_brief_scope_matches_frozen_scope():
    scope_freeze = _scope_freeze()

    result = _render(scope_freeze)

    scope = scope_freeze.scope
    for path in (
        *scope.allowed_new_files,
        *scope.allowed_existing_files,
        *scope.protected_files,
        *scope.forbidden_paths,
    ):
        assert path in result.brief
    for justification in scope.justifications.values():
        assert justification in result.brief


def test_workflow_advances_exactly_one_step_to_brief_ready():
    scope_freeze = _scope_freeze()
    original_workflow = scope_freeze.workflow

    result = _render(scope_freeze)

    assert scope_freeze.workflow is original_workflow
    assert scope_freeze.workflow.completed_steps == (
        STEP_REQUEST_RECEIVED,
        STEP_JOB_CREATED,
        STEP_SCOPE_FROZEN,
    )
    assert result.workflow.completed_steps == (
        STEP_REQUEST_RECEIVED,
        STEP_JOB_CREATED,
        STEP_SCOPE_FROZEN,
        STEP_BRIEF_READY,
    )
    assert result.workflow.current_step == STEP_BRIEF_READY
    assert result.next_allowed_steps == (STEP_WORKER_RETURNED,)
    assert result.workflow.next_allowed_steps == (STEP_WORKER_RETURNED,)


def test_not_frozen_scope_does_not_render_or_advance():
    scope_freeze = _scope_freeze(scope_data={})

    result = _render(scope_freeze)

    assert result.status == STATUS_NOT_READY
    assert result.ready is False
    assert result.brief is None
    assert result.workflow is scope_freeze.workflow
    assert result.blocking_reasons == scope_freeze.blocking_reasons
    assert result.blocking_reasons == (
        "Approved scope input is invalid.",
    )


def test_blocked_job_creation_does_not_render_or_advance():
    scope_freeze = _scope_freeze(binding_overrides={"note": ""})

    result = _render(scope_freeze)

    assert result.status == STATUS_NOT_READY
    assert result.brief is None
    assert result.workflow is scope_freeze.workflow
    assert result.workflow.completed_steps == (STEP_REQUEST_RECEIVED,)
    assert result.blocking_reasons == ("note is required.",)


@pytest.mark.parametrize(
    "goal,constraints",
    [
        (None, (APPROVED_CONSTRAINT,)),
        ("", (APPROVED_CONSTRAINT,)),
        ("   ", (APPROVED_CONSTRAINT,)),
        (APPROVED_GOAL, None),
        (APPROVED_GOAL, "one constraint"),
        (APPROVED_GOAL, ("",)),
        (APPROVED_GOAL, (object(),)),
    ],
)
def test_invalid_brief_input_blocks_without_rendering_or_advancing(
    goal,
    constraints,
):
    scope_freeze = _scope_freeze()

    first = render_brief_from_workflow_scope(
        scope_freeze,
        goal,
        constraints,
    )
    second = render_brief_from_workflow_scope(
        scope_freeze,
        goal,
        constraints,
    )

    assert first.status == STATUS_NOT_READY
    assert first.ready is False
    assert first.brief is None
    assert first.workflow is scope_freeze.workflow
    assert first.blocking_reasons == (
        "Approved worker brief input is invalid.",
    )
    assert first.to_dict() == second.to_dict()
    assert first.summary() == second.summary()


@pytest.mark.parametrize("invalid", [None, {}, "scope", object()])
def test_invalid_workflow_scope_input_is_rejected_deterministically(invalid):
    with pytest.raises(WorkflowBriefError, match="WorkflowScopeFreeze"):
        render_brief_from_workflow_scope(
            invalid,
            APPROVED_GOAL,
            (APPROVED_CONSTRAINT,),
        )


def test_result_is_immutable_and_inputs_are_not_mutated():
    scope_freeze = _scope_freeze()
    before = scope_freeze.to_dict()

    result = _render(scope_freeze)

    assert scope_freeze.to_dict() == before
    with pytest.raises(FrozenInstanceError):
        result.status = STATUS_NOT_READY
    with pytest.raises(FrozenInstanceError):
        result.workflow.completed_steps = ()
    with pytest.raises(FrozenInstanceError):
        result.scope_freeze.scope.allowed_new_files = ()


def test_direct_construction_cannot_forge_result_invariants():
    result = _render()

    with pytest.raises(WorkflowBriefError, match="status"):
        replace(result, status=STATUS_NOT_READY)
    with pytest.raises(WorkflowBriefError, match="blocking reasons"):
        replace(result, blocking_reasons=("Forged blocker.",))
    with pytest.raises(WorkflowBriefError, match="blocking reasons"):
        replace(result, brief=None, status=STATUS_NOT_READY)
    with pytest.raises(WorkflowBriefError, match="exactly brief_ready"):
        replace(result, workflow=result.scope_freeze.workflow)


def test_to_dict_and_summary_are_deterministic_without_brief_prose():
    first = _render()
    second = _render()

    assert first.brief == second.brief
    assert first.to_dict() == second.to_dict()
    assert first.summary() == second.summary()
    assert json.loads(first.summary()) == first.to_dict()
    assert first.to_dict()["brief"] == {
        "bytes": len(first.brief.encode("utf-8")),
        "format": "markdown",
        "prose_included": False,
    }


def test_summary_is_bounded_and_excludes_raw_or_operational_fields():
    result = _render()
    summary = result.summary()
    payload = json.loads(summary)

    assert len(summary.encode("utf-8")) <= MAX_WORKFLOW_BRIEF_SUMMARY_BYTES
    assert payload["authority"] == {
        "autonomous": False,
        "offline_only": True,
        "runtime_authority": False,
    }
    for marker in (
        RAW_REQUEST_GOAL,
        RAW_REQUEST_BEHAVIOR,
        RAW_REQUEST_CONSTRAINT,
        RAW_BINDING_NOTE,
        RAW_JUSTIFICATION,
        APPROVED_GOAL,
        APPROVED_CONSTRAINT,
    ):
        assert marker not in summary

    forbidden_keys = {
        "prompt",
        "raw_prompt",
        "secret",
        "secrets",
        "argv",
        "worker_prose",
        "worker_report",
        "returned_content",
        "output_excerpt",
        "environment",
    }

    def all_keys(value):
        if isinstance(value, dict):
            for key, child in value.items():
                yield key
                yield from all_keys(child)
        elif isinstance(value, list):
            for child in value:
                yield from all_keys(child)

    assert not forbidden_keys & set(all_keys(payload))


def test_adapter_stops_before_worker_returned_and_later_artifacts():
    result = _render()

    assert result.workflow.completed_steps == (
        STEP_REQUEST_RECEIVED,
        STEP_JOB_CREATED,
        STEP_SCOPE_FROZEN,
        STEP_BRIEF_READY,
    )
    assert STEP_WORKER_RETURNED not in result.workflow.completed_steps
    assert result.next_allowed_steps == (STEP_WORKER_RETURNED,)


def test_adapter_module_has_only_permitted_brief_authority():
    source_path = (
        Path(__file__).parents[1]
        / "scripts"
        / "capability_build"
        / "workflow_brief.py"
    )
    source = source_path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    forbidden_imports = {
        "backend",
        "git",
        "github",
        "httpx",
        "os",
        "pathlib",
        "pygit2",
        "requests",
        "shutil",
        "subprocess",
    }
    forbidden_calls = {
        "compile",
        "eval",
        "exec",
        "open",
        "read_text",
        "read_bytes",
        "write_text",
        "write_bytes",
        "mkdir",
        "unlink",
        "remove",
        "rename",
        "replace",
        "run",
        "Popen",
        "system",
        "__import__",
        "new_job",
        "transition",
        "create_workspace_dirs",
        "validate_returned_files",
        "evaluate_evidence",
        "build_review_bundle",
        "build_human_handoff",
        "create_pr",
        "open_pr",
        "register",
        "install",
        "deploy",
        "dispatch_worker",
        "execute",
        "verify",
        "sandbox",
    }
    forbidden_definitions = {
        "create_workspace_dirs",
        "validate_returned_files",
        "evaluate_evidence",
        "build_review_bundle",
        "build_human_handoff",
        "create_pr",
        "open_pr",
        "register",
        "install",
        "deploy",
        "dispatch_worker",
        "execute",
        "verify",
        "sandbox",
    }
    imports = []
    calls = []
    definitions = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imports.append(node.module or "")
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            definitions.append(node.name)
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                calls.append(node.func.id)
            elif isinstance(node.func, ast.Attribute):
                calls.append(node.func.attr)

    assert not any(
        imported.split(".")[0] in forbidden_imports
        for imported in imports
    )
    assert not forbidden_calls & set(calls)
    assert not forbidden_definitions & set(definitions)
    assert "render_worker_brief" in calls
    assert "record_workflow_step" in calls
    assert "backend.tool_registry" not in source
