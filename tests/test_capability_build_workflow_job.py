"""Tests for V0.4B Slice 5 guarded workflow-to-BuildJob creation."""

import ast
import json
from dataclasses import FrozenInstanceError, replace
from pathlib import Path

import pytest

from scripts.capability_build.job import STATE_DRAFTED
from scripts.capability_build.job_binding import BuildJobBinding
from scripts.capability_build.request import CapabilityBuildRequest
from scripts.capability_build.request_workflow import (
    start_workflow_from_request,
)
from scripts.capability_build.workflow import (
    STEP_JOB_CREATED,
    STEP_REQUEST_RECEIVED,
    STEP_SCOPE_FROZEN,
)
from scripts.capability_build.workflow_job import (
    MAX_WORKFLOW_JOB_SUMMARY_BYTES,
    STATUS_JOB_CREATED,
    STATUS_NOT_CREATED,
    WorkflowJobCreation,
    WorkflowJobError,
    create_job_from_workflow_start,
)


SPEC_SHA256 = "a" * 64
BASE_SHA = "b" * 40
RAW_GOAL_MARKER = "RAW_USER_GOAL_MUST_NOT_APPEAR"
RAW_BEHAVIOR_MARKER = "RAW_BEHAVIOR_MUST_NOT_APPEAR"
RAW_CONSTRAINT_MARKER = "RAW_CONSTRAINT_MUST_NOT_APPEAR"
RAW_BINDING_NOTE_MARKER = "RAW_BINDING_NOTE_MUST_NOT_APPEAR"


def _request(**overrides):
    values = {
        "request_id": "request-005",
        "capability_name": "Project insight",
        "user_goal": RAW_GOAL_MARKER,
        "requested_behavior_summary": RAW_BEHAVIOR_MARKER,
        "constraints": (RAW_CONSTRAINT_MARKER,),
    }
    values.update(overrides)
    return CapabilityBuildRequest(**values)


def _start(**request_overrides):
    return start_workflow_from_request(_request(**request_overrides))


def _binding(**overrides):
    values = {
        "job_id": "job-v04b-slice-5",
        "capability_id": "projects.insight",
        "spec_sha256": SPEC_SHA256,
        "base_sha": BASE_SHA,
        "actor": "human:reviewer",
        "note": RAW_BINDING_NOTE_MARKER,
    }
    values.update(overrides)
    return BuildJobBinding(**values)


def test_ready_start_and_binding_create_drafted_job():
    start = _start()
    binding = _binding()

    result = create_job_from_workflow_start(start, binding)

    assert isinstance(result, WorkflowJobCreation)
    assert result.schema_version == 1
    assert result.status == STATUS_JOB_CREATED
    assert result.created is True
    assert result.blocking_reasons == ()
    assert result.job is not None
    assert result.job.state == STATE_DRAFTED
    assert result.job.fix_round == 0
    assert result.offline_only is True
    assert result.autonomous is False
    assert result.runtime_authority is False


def test_created_job_fields_and_attribution_match_binding():
    binding = _binding()

    result = create_job_from_workflow_start(_start(), binding)

    assert result.job.job_id == binding.job_id
    assert result.job.capability_id == binding.capability_id
    assert result.job.spec_sha256 == binding.spec_sha256
    assert result.job.base_sha == binding.base_sha
    assert len(result.job.history) == 1
    assert result.job.history[0].actor == binding.actor
    assert result.job.history[0].note == binding.note
    assert result.job.history[0].at


def test_workflow_advances_exactly_one_step_to_job_created():
    start = _start()
    original_workflow = start.workflow

    result = create_job_from_workflow_start(start, _binding())

    assert start.workflow is original_workflow
    assert start.workflow.completed_steps == (STEP_REQUEST_RECEIVED,)
    assert result.workflow.completed_steps == (
        STEP_REQUEST_RECEIVED,
        STEP_JOB_CREATED,
    )
    assert result.workflow.current_step == STEP_JOB_CREATED
    assert result.next_allowed_steps == (STEP_SCOPE_FROZEN,)
    assert result.workflow.next_allowed_steps == (STEP_SCOPE_FROZEN,)


def test_draft_request_does_not_create_job_or_advance_workflow():
    start = _start(requester_decision_required=True)

    result = create_job_from_workflow_start(start, _binding())

    assert result.status == STATUS_NOT_CREATED
    assert result.created is False
    assert result.job is None
    assert result.workflow is start.workflow
    assert result.workflow.completed_steps == ()
    assert result.blocking_reasons == start.blocking_reasons
    assert result.blocking_reasons == (
        "Requester decision is still required.",
    )


def test_blocked_request_carries_stable_reasons_without_creating_job():
    start = _start(request_id="", user_goal="")

    result = create_job_from_workflow_start(start, _binding())

    assert result.status == STATUS_NOT_CREATED
    assert result.job is None
    assert result.workflow is start.workflow
    assert result.blocking_reasons == start.blocking_reasons
    assert result.blocking_reasons == (
        "request_id is required.",
        "user_goal is required.",
    )


def test_blocked_binding_carries_reasons_without_creating_or_advancing():
    start = _start()
    binding = _binding(note="")

    result = create_job_from_workflow_start(start, binding)

    assert result.status == STATUS_NOT_CREATED
    assert result.created is False
    assert result.job is None
    assert result.workflow is start.workflow
    assert result.workflow.completed_steps == (STEP_REQUEST_RECEIVED,)
    assert result.blocking_reasons == binding.blocking_reasons
    assert result.blocking_reasons == ("note is required.",)


def test_blocked_start_and_binding_reasons_are_sorted_and_deduplicated():
    result = create_job_from_workflow_start(
        _start(request_id="", user_goal=""),
        _binding(note=""),
    )

    assert result.blocking_reasons == (
        "note is required.",
        "request_id is required.",
        "user_goal is required.",
    )


@pytest.mark.parametrize("invalid", [None, {}, "start", object()])
def test_invalid_start_input_is_rejected_deterministically(invalid):
    with pytest.raises(WorkflowJobError, match="RequestWorkflowStart"):
        create_job_from_workflow_start(invalid, _binding())


@pytest.mark.parametrize("invalid", [None, {}, "binding", object()])
def test_invalid_binding_input_is_rejected_deterministically(invalid):
    with pytest.raises(WorkflowJobError, match="BuildJobBinding"):
        create_job_from_workflow_start(_start(), invalid)


def test_result_is_immutable_and_inputs_are_not_mutated():
    start = _start()
    binding = _binding()
    start_before = start.to_dict()
    binding_before = binding.to_dict()

    result = create_job_from_workflow_start(start, binding)

    assert start.to_dict() == start_before
    assert binding.to_dict() == binding_before
    with pytest.raises(FrozenInstanceError):
        result.status = STATUS_NOT_CREATED
    with pytest.raises(FrozenInstanceError):
        result.workflow.completed_steps = ()
    with pytest.raises(FrozenInstanceError):
        result.job.state = "dispatched"


def test_direct_construction_cannot_forge_result_invariants():
    result = create_job_from_workflow_start(_start(), _binding())

    with pytest.raises(WorkflowJobError, match="status"):
        replace(result, status=STATUS_NOT_CREATED)
    with pytest.raises(WorkflowJobError, match="require a created job"):
        replace(result, job=None)
    with pytest.raises(WorkflowJobError, match="blocking reasons"):
        replace(result, blocking_reasons=("Forged blocker.",))


def test_to_dict_and_summary_are_deterministic_for_stable_fields():
    first = create_job_from_workflow_start(_start(), _binding())
    second = create_job_from_workflow_start(_start(), _binding())

    assert first.job.history[0].at
    assert second.job.history[0].at
    assert first.to_dict() == second.to_dict()
    assert first.summary() == second.summary()
    assert json.loads(first.summary()) == first.to_dict()
    assert "history" not in first.to_dict()["job"]
    assert "content_sha256" not in first.to_dict()["job"]


def test_summary_is_bounded_and_excludes_raw_or_operational_fields():
    result = create_job_from_workflow_start(_start(), _binding())
    summary = result.summary()
    payload = json.loads(summary)

    assert len(summary.encode("utf-8")) <= MAX_WORKFLOW_JOB_SUMMARY_BYTES
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


def test_adapter_stops_before_scope_and_all_later_artifacts():
    result = create_job_from_workflow_start(_start(), _binding())

    assert result.job.state == STATE_DRAFTED
    assert result.workflow.completed_steps == (
        STEP_REQUEST_RECEIVED,
        STEP_JOB_CREATED,
    )
    assert STEP_SCOPE_FROZEN not in result.workflow.completed_steps
    assert result.next_allowed_steps == (STEP_SCOPE_FROZEN,)


def test_adapter_module_has_only_permitted_creation_authority():
    source_path = (
        Path(__file__).parents[1]
        / "scripts"
        / "capability_build"
        / "workflow_job.py"
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
        "transition",
        "freeze_scope",
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
        "freeze_scope",
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
    assert set(calls) & {"new_job", "record_workflow_step"} == {
        "new_job",
        "record_workflow_step",
    }
    assert "backend.tool_registry" not in source
