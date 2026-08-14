"""Tests for V0.4B Slice 6 guarded workflow-to-scope freezing."""

import ast
import json
from dataclasses import FrozenInstanceError, replace
from pathlib import Path

import pytest

from scripts.capability_build.job_binding import BuildJobBinding
from scripts.capability_build.request import CapabilityBuildRequest
from scripts.capability_build.request_workflow import (
    start_workflow_from_request,
)
from scripts.capability_build.scope import FrozenScope
from scripts.capability_build.workflow import (
    STEP_BRIEF_READY,
    STEP_JOB_CREATED,
    STEP_REQUEST_RECEIVED,
    STEP_SCOPE_FROZEN,
)
from scripts.capability_build.workflow_job import (
    create_job_from_workflow_start,
)
from scripts.capability_build.workflow_scope import (
    MAX_WORKFLOW_SCOPE_SUMMARY_BYTES,
    STATUS_NOT_FROZEN,
    STATUS_SCOPE_FROZEN,
    WorkflowScopeError,
    WorkflowScopeFreeze,
    freeze_scope_from_workflow_job,
)


SPEC_SHA256 = "a" * 64
BASE_SHA = "b" * 40
RAW_GOAL_MARKER = "RAW_SCOPE_USER_GOAL_MUST_NOT_APPEAR"
RAW_BEHAVIOR_MARKER = "RAW_SCOPE_BEHAVIOR_MUST_NOT_APPEAR"
RAW_CONSTRAINT_MARKER = "RAW_SCOPE_CONSTRAINT_MUST_NOT_APPEAR"
RAW_BINDING_NOTE_MARKER = "RAW_SCOPE_BINDING_NOTE_MUST_NOT_APPEAR"
RAW_JUSTIFICATION_MARKER = "RAW_SCOPE_JUSTIFICATION_MUST_NOT_APPEAR"


def _request(**overrides):
    values = {
        "request_id": "request-006",
        "capability_name": "Project insight",
        "user_goal": RAW_GOAL_MARKER,
        "requested_behavior_summary": RAW_BEHAVIOR_MARKER,
        "constraints": (RAW_CONSTRAINT_MARKER,),
    }
    values.update(overrides)
    return CapabilityBuildRequest(**values)


def _binding(**overrides):
    values = {
        "job_id": "job-v04b-slice-6",
        "capability_id": "projects.insight",
        "spec_sha256": SPEC_SHA256,
        "base_sha": BASE_SHA,
        "actor": "human:reviewer",
        "note": RAW_BINDING_NOTE_MARKER,
    }
    values.update(overrides)
    return BuildJobBinding(**values)


def _creation(request_overrides=None, binding_overrides=None):
    request = _request(**(request_overrides or {}))
    start = start_workflow_from_request(request)
    binding = _binding(**(binding_overrides or {}))
    return create_job_from_workflow_start(start, binding)


def _scope_data(**overrides):
    values = {
        "allowed_new_files": ("frontend/widgets/panel.js",),
        "allowed_existing_files": ("frontend/app.js",),
        "protected_files": ("ops/protected/**",),
        "forbidden_paths": ("private/**",),
        "justifications": {
            "frontend/widgets/panel.js": RAW_JUSTIFICATION_MARKER,
            "frontend/app.js": "Update the approved frontend entrypoint.",
        },
    }
    values.update(overrides)
    return values


def test_created_job_and_approved_scope_freeze_scope():
    creation = _creation()

    result = freeze_scope_from_workflow_job(creation, _scope_data())

    assert isinstance(result, WorkflowScopeFreeze)
    assert result.schema_version == 1
    assert result.status == STATUS_SCOPE_FROZEN
    assert result.frozen is True
    assert result.blocking_reasons == ()
    assert isinstance(result.scope, FrozenScope)
    assert result.scope.allowed_new_files == (
        "frontend/widgets/panel.js",
    )
    assert result.scope.allowed_existing_files == ("frontend/app.js",)
    assert result.offline_only is True
    assert result.autonomous is False
    assert result.runtime_authority is False


def test_existing_frozen_scope_input_is_copied_canonically():
    approved = FrozenScope.from_dict(_scope_data())

    result = freeze_scope_from_workflow_job(_creation(), approved)

    assert result.scope == approved
    assert result.scope is not approved
    assert result.scope.to_dict() == approved.to_dict()


def test_frozen_scope_is_bound_to_created_job_identity():
    creation = _creation()

    result = freeze_scope_from_workflow_job(creation, _scope_data())

    assert result.job_id == creation.job.job_id
    assert result.capability_id == creation.job.capability_id
    assert result.spec_sha256 == creation.job.spec_sha256
    assert result.base_sha == creation.job.base_sha
    assert result.to_dict()["job"] == {
        "base_sha": creation.job.base_sha,
        "capability_id": creation.job.capability_id,
        "job_id": creation.job.job_id,
        "spec_sha256": creation.job.spec_sha256,
    }


def test_workflow_advances_exactly_one_step_to_scope_frozen():
    creation = _creation()
    original_workflow = creation.workflow

    result = freeze_scope_from_workflow_job(creation, _scope_data())

    assert creation.workflow is original_workflow
    assert creation.workflow.completed_steps == (
        STEP_REQUEST_RECEIVED,
        STEP_JOB_CREATED,
    )
    assert result.workflow.completed_steps == (
        STEP_REQUEST_RECEIVED,
        STEP_JOB_CREATED,
        STEP_SCOPE_FROZEN,
    )
    assert result.workflow.current_step == STEP_SCOPE_FROZEN
    assert result.next_allowed_steps == (STEP_BRIEF_READY,)
    assert result.workflow.next_allowed_steps == (STEP_BRIEF_READY,)


def test_not_created_job_does_not_freeze_or_validate_scope():
    creation = _creation(
        request_overrides={"requester_decision_required": True}
    )

    result = freeze_scope_from_workflow_job(creation, object())

    assert result.status == STATUS_NOT_FROZEN
    assert result.frozen is False
    assert result.scope is None
    assert result.workflow is creation.workflow
    assert result.workflow.completed_steps == ()
    assert result.blocking_reasons == creation.blocking_reasons


def test_blocked_job_binding_does_not_freeze_or_advance():
    creation = _creation(binding_overrides={"note": ""})

    result = freeze_scope_from_workflow_job(creation, _scope_data())

    assert result.status == STATUS_NOT_FROZEN
    assert result.scope is None
    assert result.workflow is creation.workflow
    assert result.workflow.completed_steps == (STEP_REQUEST_RECEIVED,)
    assert result.blocking_reasons == ("note is required.",)


@pytest.mark.parametrize(
    "scope_data",
    [
        None,
        [],
        "scope",
        {},
        _scope_data(
            allowed_new_files=("../escape.py",),
            allowed_existing_files=(),
            justifications={"../escape.py": "Unsafe path."},
        ),
        _scope_data(justifications={}),
    ],
)
def test_invalid_scope_input_blocks_without_freezing_or_advancing(scope_data):
    creation = _creation()

    first = freeze_scope_from_workflow_job(creation, scope_data)
    second = freeze_scope_from_workflow_job(creation, scope_data)

    assert first.status == STATUS_NOT_FROZEN
    assert first.frozen is False
    assert first.scope is None
    assert first.workflow is creation.workflow
    assert first.workflow.completed_steps == (
        STEP_REQUEST_RECEIVED,
        STEP_JOB_CREATED,
    )
    assert first.blocking_reasons == (
        "Approved scope input is invalid.",
    )
    assert first.to_dict() == second.to_dict()
    assert first.summary() == second.summary()


@pytest.mark.parametrize("invalid", [None, {}, "creation", object()])
def test_invalid_workflow_job_input_is_rejected_deterministically(invalid):
    with pytest.raises(WorkflowScopeError, match="WorkflowJobCreation"):
        freeze_scope_from_workflow_job(invalid, _scope_data())


def test_result_is_immutable_and_inputs_are_not_mutated():
    creation = _creation()
    creation_before = creation.to_dict()
    scope_data = _scope_data()

    result = freeze_scope_from_workflow_job(creation, scope_data)

    assert creation.to_dict() == creation_before
    assert scope_data == _scope_data()
    with pytest.raises(FrozenInstanceError):
        result.status = STATUS_NOT_FROZEN
    with pytest.raises(FrozenInstanceError):
        result.workflow.completed_steps = ()
    with pytest.raises(FrozenInstanceError):
        result.scope.allowed_new_files = ()


def test_direct_construction_cannot_forge_result_invariants():
    result = freeze_scope_from_workflow_job(_creation(), _scope_data())

    with pytest.raises(WorkflowScopeError, match="status"):
        replace(result, status=STATUS_NOT_FROZEN)
    with pytest.raises(WorkflowScopeError, match="blocking reasons"):
        replace(result, blocking_reasons=("Forged blocker.",))
    with pytest.raises(WorkflowScopeError, match="blocking reasons"):
        replace(result, scope=None, status=STATUS_NOT_FROZEN)


def test_to_dict_and_summary_are_deterministic_for_stable_fields():
    first = freeze_scope_from_workflow_job(_creation(), _scope_data())
    second = freeze_scope_from_workflow_job(_creation(), _scope_data())

    assert first.to_dict() == second.to_dict()
    assert first.summary() == second.summary()
    assert json.loads(first.summary()) == first.to_dict()
    assert "history" not in first.to_dict()["job"]
    assert "content_sha256" not in first.to_dict()["job"]


def test_summary_is_bounded_and_excludes_raw_or_operational_fields():
    result = freeze_scope_from_workflow_job(_creation(), _scope_data())
    summary = result.summary()
    payload = json.loads(summary)

    assert len(summary.encode("utf-8")) <= MAX_WORKFLOW_SCOPE_SUMMARY_BYTES
    assert payload["authority"] == {
        "autonomous": False,
        "offline_only": True,
        "runtime_authority": False,
    }
    for marker in (
        RAW_GOAL_MARKER,
        RAW_BEHAVIOR_MARKER,
        RAW_CONSTRAINT_MARKER,
        RAW_BINDING_NOTE_MARKER,
        RAW_JUSTIFICATION_MARKER,
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


def test_adapter_stops_before_brief_and_all_later_artifacts():
    result = freeze_scope_from_workflow_job(_creation(), _scope_data())

    assert result.workflow.completed_steps == (
        STEP_REQUEST_RECEIVED,
        STEP_JOB_CREATED,
        STEP_SCOPE_FROZEN,
    )
    assert STEP_BRIEF_READY not in result.workflow.completed_steps
    assert result.next_allowed_steps == (STEP_BRIEF_READY,)


def test_adapter_module_has_only_permitted_scope_authority():
    source_path = (
        Path(__file__).parents[1]
        / "scripts"
        / "capability_build"
        / "workflow_scope.py"
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
        "render_worker_brief",
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
        "render_worker_brief",
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
    assert "record_workflow_step" in calls
    assert "from_dict" in calls
    assert "backend.tool_registry" not in source
