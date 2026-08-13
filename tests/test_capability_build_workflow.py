"""Focused tests for V0.4B Slice 1 offline workflow state."""

import ast
import json
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from scripts.capability_build.workflow import (
    MAX_WORKFLOW_SUMMARY_BYTES,
    STATUS_BLOCKED,
    STATUS_COMPLETE,
    STATUS_IN_PROGRESS,
    STATUS_NOT_STARTED,
    STEP_BRIEF_READY,
    STEP_BUNDLE_CREATED,
    STEP_EVIDENCE_ATTACHED,
    STEP_HANDOFF_CREATED,
    STEP_HUMAN_DECISION_PENDING,
    STEP_INTAKE_CHECKED,
    STEP_JOB_CREATED,
    STEP_REQUEST_RECEIVED,
    STEP_SCOPE_FROZEN,
    STEP_WORKER_RETURNED,
    WORKFLOW_STATUSES,
    WORKFLOW_STEPS,
    WorkflowError,
    WorkflowPlan,
    new_workflow,
    record_workflow_step,
)


def _advance(count):
    workflow = new_workflow()
    for step in WORKFLOW_STEPS[:count]:
        workflow = record_workflow_step(workflow, step)
    return workflow


def test_initial_workflow_is_not_started_and_allows_only_request():
    workflow = new_workflow()

    assert workflow.schema_version == 1
    assert workflow.status == STATUS_NOT_STARTED
    assert workflow.current_step is None
    assert workflow.completed_steps == ()
    assert workflow.blocked_reasons == ()
    assert workflow.next_allowed_steps == (STEP_REQUEST_RECEIVED,)
    assert workflow.offline_only is True
    assert workflow.autonomous is False
    assert workflow.runtime_authority is False


def test_valid_steps_progress_one_at_a_time_in_fixed_order():
    workflow = new_workflow()

    for index, step in enumerate(WORKFLOW_STEPS[:-1], start=1):
        previous = workflow
        workflow = record_workflow_step(workflow, step)
        assert previous is not workflow
        assert workflow.status == STATUS_IN_PROGRESS
        assert workflow.current_step == step
        assert workflow.completed_steps == WORKFLOW_STEPS[:index]
        assert workflow.next_allowed_steps == (WORKFLOW_STEPS[index],)
        assert workflow.blocked_reasons == ()


@pytest.mark.parametrize(
    "completed_count,attempted",
    [
        (0, STEP_JOB_CREATED),
        (1, STEP_SCOPE_FROZEN),
        (3, STEP_WORKER_RETURNED),
        (5, STEP_BUNDLE_CREATED),
        (8, STEP_HUMAN_DECISION_PENDING),
    ],
)
def test_skipped_prerequisite_blocks_later_step(
    completed_count, attempted
):
    original = _advance(completed_count)
    blocked = record_workflow_step(original, attempted)
    required = WORKFLOW_STEPS[completed_count]

    assert blocked.status == STATUS_BLOCKED
    assert blocked.completed_steps == original.completed_steps
    assert blocked.current_step == original.current_step
    assert blocked.blocked_step == attempted
    assert blocked.next_allowed_steps == (required,)
    assert blocked.blocked_reasons == (
        f"Cannot record {attempted!r} before prerequisite {required!r}.",
    )


def test_recording_missing_prerequisite_clears_previous_block():
    blocked = record_workflow_step(new_workflow(), STEP_BRIEF_READY)

    progressed = record_workflow_step(blocked, STEP_REQUEST_RECEIVED)

    assert progressed.status == STATUS_IN_PROGRESS
    assert progressed.blocked_step is None
    assert progressed.blocked_reasons == ()
    assert progressed.next_allowed_steps == (STEP_JOB_CREATED,)


def test_workflow_order_and_summary_are_deterministic():
    first = _advance(6)
    second = new_workflow()
    for step in (
        STEP_REQUEST_RECEIVED,
        STEP_JOB_CREATED,
        STEP_SCOPE_FROZEN,
        STEP_BRIEF_READY,
        STEP_WORKER_RETURNED,
        STEP_INTAKE_CHECKED,
    ):
        second = record_workflow_step(second, step)

    assert first == second
    assert first.to_dict() == second.to_dict()
    assert first.summary() == second.summary()
    assert first.completed_steps == WORKFLOW_STEPS[:6]


def test_complete_workflow_has_no_next_step():
    workflow = _advance(len(WORKFLOW_STEPS))

    assert workflow.status == STATUS_COMPLETE
    assert workflow.current_step == STEP_HUMAN_DECISION_PENDING
    assert workflow.completed_steps == WORKFLOW_STEPS
    assert workflow.next_allowed_steps == ()
    assert workflow.blocked_reasons == ()
    with pytest.raises(WorkflowError, match="complete workflow"):
        record_workflow_step(workflow, STEP_HUMAN_DECISION_PENDING)


def test_blocked_workflow_reasons_are_stable():
    first = record_workflow_step(_advance(2), STEP_EVIDENCE_ATTACHED)
    second = record_workflow_step(_advance(2), STEP_EVIDENCE_ATTACHED)

    assert first == second
    assert first.status == STATUS_BLOCKED
    assert first.blocked_reasons == second.blocked_reasons == (
        "Cannot record 'evidence_attached' before prerequisite "
        "'scope_frozen'.",
    )
    assert json.loads(first.summary())["blocked_reasons"] == list(
        first.blocked_reasons
    )


@pytest.mark.parametrize(
    "unknown", ["unknown", "", None, "deploy", "job-created"]
)
def test_unknown_workflow_step_is_rejected(unknown):
    with pytest.raises(WorkflowError, match="unknown workflow step"):
        record_workflow_step(new_workflow(), unknown)


def test_repeated_step_and_impossible_direct_state_are_rejected():
    workflow = record_workflow_step(
        new_workflow(), STEP_REQUEST_RECEIVED
    )
    with pytest.raises(WorkflowError, match="already completed"):
        record_workflow_step(workflow, STEP_REQUEST_RECEIVED)
    with pytest.raises(WorkflowError, match="ordered prerequisite prefix"):
        WorkflowPlan(completed_steps=(STEP_JOB_CREATED,))
    with pytest.raises(WorkflowError, match="later than"):
        WorkflowPlan(
            completed_steps=(STEP_REQUEST_RECEIVED,),
            blocked_step=STEP_JOB_CREATED,
        )


def test_workflow_models_are_immutable():
    workflow = _advance(3)

    with pytest.raises(FrozenInstanceError):
        workflow.status = STATUS_COMPLETE
    with pytest.raises(FrozenInstanceError):
        workflow.completed_steps = WORKFLOW_STEPS


def test_summary_is_bounded_and_contains_no_untrusted_content_fields():
    summary = record_workflow_step(
        _advance(4), STEP_HANDOFF_CREATED
    ).summary()
    payload = json.loads(summary)

    assert len(summary.encode("utf-8")) <= MAX_WORKFLOW_SUMMARY_BYTES
    assert payload["authority"] == {
        "autonomous": False,
        "offline_only": True,
        "runtime_authority": False,
    }
    forbidden_keys = {
        "prompt",
        "raw_prompt",
        "secret",
        "secrets",
        "worker_prose",
        "worker_report",
        "returned_content",
        "argv",
        "output_excerpt",
    }
    assert not forbidden_keys & set(payload)
    assert all(status in WORKFLOW_STATUSES for status in (
        STATUS_NOT_STARTED,
        STATUS_IN_PROGRESS,
        STATUS_BLOCKED,
        STATUS_COMPLETE,
    ))


def test_step_sequence_is_the_fixed_v04b_slice_one_contract():
    assert WORKFLOW_STEPS == (
        STEP_REQUEST_RECEIVED,
        STEP_JOB_CREATED,
        STEP_SCOPE_FROZEN,
        STEP_BRIEF_READY,
        STEP_WORKER_RETURNED,
        STEP_INTAKE_CHECKED,
        STEP_EVIDENCE_ATTACHED,
        STEP_BUNDLE_CREATED,
        STEP_HANDOFF_CREATED,
        STEP_HUMAN_DECISION_PENDING,
    )


def test_workflow_module_has_no_execution_or_external_authority():
    source_path = (
        Path(__file__).parents[1]
        / "scripts"
        / "capability_build"
        / "workflow.py"
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
    forbidden_authority_names = {
        "deploy",
        "install",
        "register",
        "push",
        "merge",
        "create_pr",
        "open_pr",
        "apply_patch",
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
    assert not forbidden_authority_names & set(definitions)
    assert "backend.tool_registry" not in source
