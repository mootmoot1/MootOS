"""Tests for V0.4B Slice 3 pure request-to-workflow start."""

import ast
import json
from dataclasses import FrozenInstanceError, replace
from pathlib import Path

import pytest

from scripts.capability_build.request import CapabilityBuildRequest
from scripts.capability_build.request_workflow import (
    MAX_START_SUMMARY_BYTES,
    STATUS_NOT_STARTED,
    STATUS_WORKFLOW_STARTED,
    RequestWorkflowError,
    start_workflow_from_request,
)
from scripts.capability_build.workflow import (
    STATUS_IN_PROGRESS,
    STATUS_NOT_STARTED as WORKFLOW_NOT_STARTED,
    STEP_JOB_CREATED,
    STEP_REQUEST_RECEIVED,
)


RAW_GOAL_MARKER = "RAW_USER_GOAL_MUST_NOT_APPEAR"
RAW_BEHAVIOR_MARKER = "RAW_BEHAVIOR_MUST_NOT_APPEAR"
RAW_CONSTRAINT_MARKER = "RAW_CONSTRAINT_MUST_NOT_APPEAR"


def _request(**overrides):
    values = {
        "request_id": "request-003",
        "capability_name": "Project insight",
        "user_goal": RAW_GOAL_MARKER,
        "requested_behavior_summary": RAW_BEHAVIOR_MARKER,
        "constraints": (RAW_CONSTRAINT_MARKER,),
    }
    values.update(overrides)
    return CapabilityBuildRequest(**values)


def test_ready_request_starts_workflow_with_only_request_received():
    request = _request()

    result = start_workflow_from_request(request)

    assert result.schema_version == 1
    assert result.status == STATUS_WORKFLOW_STARTED
    assert result.started is True
    assert result.blocking_reasons == ()
    assert result.workflow.status == STATUS_IN_PROGRESS
    assert result.workflow.completed_steps == (STEP_REQUEST_RECEIVED,)
    assert result.workflow.current_step == STEP_REQUEST_RECEIVED
    assert result.next_allowed_steps == (STEP_JOB_CREATED,)
    assert result.workflow.next_allowed_steps == (STEP_JOB_CREATED,)
    assert result.offline_only is True
    assert result.autonomous is False
    assert result.runtime_authority is False
    assert request.ready_to_start_workflow is True


def test_draft_request_does_not_start_and_reports_stable_reason():
    request = _request(requester_decision_required=True)

    first = start_workflow_from_request(request)
    second = start_workflow_from_request(request)

    assert first == second
    assert first.status == STATUS_NOT_STARTED
    assert first.started is False
    assert first.workflow.status == WORKFLOW_NOT_STARTED
    assert first.workflow.completed_steps == ()
    assert first.next_allowed_steps == (STEP_REQUEST_RECEIVED,)
    assert first.blocking_reasons == (
        "Requester decision is still required.",
    )


def test_blocked_request_does_not_start_and_carries_stable_reasons():
    request = _request(request_id="", user_goal="")

    result = start_workflow_from_request(request)

    assert result.status == STATUS_NOT_STARTED
    assert result.started is False
    assert result.workflow.status == WORKFLOW_NOT_STARTED
    assert result.workflow.completed_steps == ()
    assert result.blocking_reasons == request.blocking_reasons
    assert result.blocking_reasons == (
        "request_id is required.",
        "user_goal is required.",
    )


@pytest.mark.parametrize("invalid", [None, {}, "request", object()])
def test_invalid_input_is_rejected_deterministically(invalid):
    with pytest.raises(
        RequestWorkflowError, match="CapabilityBuildRequest"
    ):
        start_workflow_from_request(invalid)


def test_result_is_immutable_and_does_not_mutate_request():
    request = _request()
    original = request.to_dict()

    result = start_workflow_from_request(request)

    assert request.to_dict() == original
    with pytest.raises(FrozenInstanceError):
        result.status = STATUS_NOT_STARTED
    with pytest.raises(FrozenInstanceError):
        result.workflow.completed_steps = ()
    with pytest.raises(FrozenInstanceError):
        result.request.request_id = "changed"


def test_direct_construction_cannot_forge_ready_request_invariants():
    result = start_workflow_from_request(_request())

    with pytest.raises(RequestWorkflowError, match="cannot require"):
        replace(
            result,
            request=replace(
                result.request, requester_decision_required=True
            ),
        )
    with pytest.raises(RequestWorkflowError, match="cannot contain"):
        replace(
            result,
            request_blocking_reasons=("Hidden blocker.",),
        )


def test_to_dict_and_summary_are_deterministic():
    first = start_workflow_from_request(_request())
    second = start_workflow_from_request(_request())

    assert first == second
    assert first.to_dict() == second.to_dict()
    assert first.summary() == second.summary()
    assert json.loads(first.summary()) == first.to_dict()


def test_summary_is_bounded_and_excludes_raw_or_operational_fields():
    result = start_workflow_from_request(_request())
    summary = result.summary()
    payload = json.loads(summary)

    assert len(summary.encode("utf-8")) <= MAX_START_SUMMARY_BYTES
    assert payload["authority"] == {
        "autonomous": False,
        "offline_only": True,
        "runtime_authority": False,
    }
    for marker in (
        RAW_GOAL_MARKER,
        RAW_BEHAVIOR_MARKER,
        RAW_CONSTRAINT_MARKER,
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


def test_adapter_stops_before_job_created_and_all_later_artifacts():
    result = start_workflow_from_request(_request())

    assert result.workflow.completed_steps == (STEP_REQUEST_RECEIVED,)
    assert STEP_JOB_CREATED not in result.workflow.completed_steps
    assert result.next_allowed_steps == (STEP_JOB_CREATED,)


def test_adapter_module_has_no_creation_or_external_authority():
    source_path = (
        Path(__file__).parents[1]
        / "scripts"
        / "capability_build"
        / "request_workflow.py"
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
    }
    forbidden_creation_names = {
        "new_job",
        "freeze_scope",
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
    assert not forbidden_creation_names & set(definitions)
    assert not forbidden_creation_names & set(calls)
    assert "backend.tool_registry" not in source
