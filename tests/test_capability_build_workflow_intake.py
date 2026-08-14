"""Tests for V0.4B Slice 8 guarded workflow intake checking."""

import ast
import json
from dataclasses import FrozenInstanceError, replace
from pathlib import Path

import pytest

from scripts.capability_build.intake import (
    OPERATION_CREATE,
    OPERATION_MODIFY,
    ReturnedFile,
    WorkerSummary,
    validate_returned_files,
)
from scripts.capability_build.job_binding import BuildJobBinding
from scripts.capability_build.request import CapabilityBuildRequest
from scripts.capability_build.request_workflow import (
    start_workflow_from_request,
)
from scripts.capability_build.workflow import (
    STEP_BRIEF_READY,
    STEP_EVIDENCE_ATTACHED,
    STEP_INTAKE_CHECKED,
    STEP_JOB_CREATED,
    STEP_REQUEST_RECEIVED,
    STEP_SCOPE_FROZEN,
    STEP_WORKER_RETURNED,
)
from scripts.capability_build.workflow_brief import (
    render_brief_from_workflow_scope,
)
from scripts.capability_build.workflow_intake import (
    MAX_WORKFLOW_INTAKE_SUMMARY_BYTES,
    STATUS_INTAKE_CHECKED,
    STATUS_NOT_CHECKED,
    WorkflowIntakeCheck,
    WorkflowIntakeError,
    check_returned_worker_from_workflow_brief,
)
from scripts.capability_build.workflow_job import (
    create_job_from_workflow_start,
)
from scripts.capability_build.workflow_scope import (
    freeze_scope_from_workflow_job,
)


SPEC_SHA256 = "a" * 64
BASE_SHA = "b" * 40
RAW_REQUEST_GOAL = "RAW_INTAKE_REQUEST_GOAL_MUST_NOT_APPEAR"
RAW_REQUEST_BEHAVIOR = "RAW_INTAKE_REQUEST_BEHAVIOR_MUST_NOT_APPEAR"
RAW_REQUEST_CONSTRAINT = "RAW_INTAKE_REQUEST_CONSTRAINT_MUST_NOT_APPEAR"
RAW_BINDING_NOTE = "RAW_INTAKE_BINDING_NOTE_MUST_NOT_APPEAR"
RAW_JUSTIFICATION = "RAW_INTAKE_JUSTIFICATION_MUST_NOT_APPEAR"
RAW_BRIEF_GOAL = "RAW_INTAKE_BRIEF_GOAL_MUST_NOT_APPEAR"
RAW_BRIEF_CONSTRAINT = "RAW_INTAKE_BRIEF_CONSTRAINT_MUST_NOT_APPEAR"
RAW_RETURNED_CONTENT = "RAW_RETURNED_CONTENT_MUST_NOT_APPEAR"
RAW_WORKER_SUMMARY = "RAW_WORKER_SUMMARY_MUST_NOT_APPEAR"
_DEFAULT_FILES = object()


def _request(**overrides):
    values = {
        "request_id": "request-008",
        "capability_name": "Project insight",
        "user_goal": RAW_REQUEST_GOAL,
        "requested_behavior_summary": RAW_REQUEST_BEHAVIOR,
        "constraints": (RAW_REQUEST_CONSTRAINT,),
    }
    values.update(overrides)
    return CapabilityBuildRequest(**values)


def _binding(**overrides):
    values = {
        "job_id": "job-v04b-slice-8",
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


def _brief_ready(
    request_overrides=None,
    binding_overrides=None,
    scope_data=None,
    goal=RAW_BRIEF_GOAL,
    constraints=(RAW_BRIEF_CONSTRAINT,),
):
    request = _request(**(request_overrides or {}))
    start = start_workflow_from_request(request)
    binding = _binding(**(binding_overrides or {}))
    creation = create_job_from_workflow_start(start, binding)
    approved_scope = _scope_data() if scope_data is None else scope_data
    scope_freeze = freeze_scope_from_workflow_job(
        creation,
        approved_scope,
    )
    return render_brief_from_workflow_scope(
        scope_freeze,
        goal,
        constraints,
    )


def _safe_files():
    return (
        ReturnedFile(
            "frontend/widgets/panel.js",
            OPERATION_CREATE,
            "PANEL = " + repr(RAW_RETURNED_CONTENT) + "\n",
        ),
        ReturnedFile(
            "frontend/app.js",
            OPERATION_MODIFY,
            "export const panelEnabled = true;\n",
        ),
    )


def _check(brief_ready=None, files=_DEFAULT_FILES, worker_summary=None):
    actual_brief = brief_ready or _brief_ready()
    actual_files = _safe_files() if files is _DEFAULT_FILES else files
    return check_returned_worker_from_workflow_brief(
        actual_brief,
        actual_files,
        worker_summary=worker_summary,
    )


def test_valid_brief_and_returned_files_run_existing_intake_validation():
    brief_ready = _brief_ready()
    files = _safe_files()
    summary = WorkerSummary(
        RAW_WORKER_SUMMARY,
        tests_run=("python3 -m pytest focused",),
    )

    result = _check(brief_ready, files, summary)

    assert isinstance(result, WorkflowIntakeCheck)
    assert result.schema_version == 1
    assert result.status == STATUS_INTAKE_CHECKED
    assert result.worker_returned is True
    assert result.checked is True
    assert result.accepted is True
    assert result.blocking_reasons == ()
    assert result.intake == validate_returned_files(
        brief_ready.scope_freeze.scope,
        files,
        worker_summary=summary,
    )
    assert result.offline_only is True
    assert result.autonomous is False
    assert result.runtime_authority is False


def test_intake_identity_and_scope_match_authoritative_brief_state():
    brief_ready = _brief_ready()

    result = _check(brief_ready)

    job = brief_ready.scope_freeze.creation.job
    scope = brief_ready.scope_freeze.scope
    assert result.job_id == job.job_id
    assert result.capability_id == job.capability_id
    assert result.spec_sha256 == job.spec_sha256
    assert result.base_sha == job.base_sha
    assert result.scope is scope
    assert result.intake.touched_files == (
        "frontend/app.js",
        "frontend/widgets/panel.js",
    )


def test_workflow_advances_worker_returned_then_intake_checked():
    brief_ready = _brief_ready()
    original_workflow = brief_ready.workflow

    result = _check(brief_ready)

    assert brief_ready.workflow is original_workflow
    assert brief_ready.workflow.completed_steps == (
        STEP_REQUEST_RECEIVED,
        STEP_JOB_CREATED,
        STEP_SCOPE_FROZEN,
        STEP_BRIEF_READY,
    )
    assert result.workflow.completed_steps == (
        STEP_REQUEST_RECEIVED,
        STEP_JOB_CREATED,
        STEP_SCOPE_FROZEN,
        STEP_BRIEF_READY,
        STEP_WORKER_RETURNED,
        STEP_INTAKE_CHECKED,
    )
    assert result.workflow.current_step == STEP_INTAKE_CHECKED
    assert result.next_allowed_steps == (STEP_EVIDENCE_ATTACHED,)
    assert result.workflow.next_allowed_steps == (STEP_EVIDENCE_ATTACHED,)


def test_decisive_blocked_intake_is_checked_but_not_accepted():
    unsafe = (
        ReturnedFile(
            "frontend/widgets/panel.js",
            OPERATION_CREATE,
            "import subprocess\n",
        ),
    )

    result = _check(files=unsafe)

    assert result.status == STATUS_INTAKE_CHECKED
    assert result.worker_returned is True
    assert result.checked is True
    assert result.accepted is False
    assert result.intake.accepted is False
    assert any("subprocess" in item for item in result.blocking_reasons)
    assert result.next_allowed_steps == (STEP_EVIDENCE_ATTACHED,)


def test_not_ready_brief_does_not_validate_or_advance():
    brief_ready = _brief_ready(scope_data={})

    result = _check(brief_ready, files=object())

    assert result.status == STATUS_NOT_CHECKED
    assert result.worker_returned is False
    assert result.checked is False
    assert result.accepted is False
    assert result.intake is None
    assert result.workflow is brief_ready.workflow
    assert result.blocking_reasons == brief_ready.blocking_reasons


@pytest.mark.parametrize(
    "returned_files",
    [None, "files", (), ({"path": "frontend/app.js"},), (object(),)],
)
def test_invalid_returned_input_does_not_validate_or_advance(returned_files):
    brief_ready = _brief_ready()

    first = _check(brief_ready, files=returned_files)
    second = _check(brief_ready, files=returned_files)

    assert first.status == STATUS_NOT_CHECKED
    assert first.worker_returned is False
    assert first.checked is False
    assert first.intake is None
    assert first.workflow is brief_ready.workflow
    assert first.workflow.current_step == STEP_BRIEF_READY
    assert first.blocking_reasons == (
        "Returned worker input is missing or invalid.",
    )
    assert first.to_dict() == second.to_dict()
    assert first.summary() == second.summary()


def test_invalid_worker_summary_does_not_validate_or_advance():
    brief_ready = _brief_ready()

    result = _check(
        brief_ready,
        worker_summary={"summary": "untrusted"},
    )

    assert result.status == STATUS_NOT_CHECKED
    assert result.intake is None
    assert result.workflow is brief_ready.workflow
    assert result.blocking_reasons == (
        "Returned worker input is missing or invalid.",
    )


@pytest.mark.parametrize("invalid", [None, {}, "brief", object()])
def test_invalid_workflow_brief_input_is_rejected_deterministically(invalid):
    with pytest.raises(WorkflowIntakeError, match="WorkflowBriefReady"):
        check_returned_worker_from_workflow_brief(
            invalid,
            _safe_files(),
        )


def test_result_is_immutable_and_inputs_are_not_mutated():
    brief_ready = _brief_ready()
    files = _safe_files()
    brief_before = brief_ready.to_dict()

    result = _check(brief_ready, files)

    assert brief_ready.to_dict() == brief_before
    assert files == _safe_files()
    with pytest.raises(FrozenInstanceError):
        result.status = STATUS_NOT_CHECKED
    with pytest.raises(FrozenInstanceError):
        result.workflow.completed_steps = ()
    with pytest.raises(FrozenInstanceError):
        result.scope.allowed_new_files = ()


def test_direct_construction_cannot_forge_result_invariants():
    result = _check()

    with pytest.raises(WorkflowIntakeError, match="status"):
        replace(result, status=STATUS_NOT_CHECKED)
    with pytest.raises(WorkflowIntakeError, match="blocking reasons"):
        replace(result, blocking_reasons=("Forged blocker.",))
    with pytest.raises(WorkflowIntakeError, match="blocking reasons"):
        replace(result, intake=None, status=STATUS_NOT_CHECKED)
    with pytest.raises(WorkflowIntakeError, match="worker_returned"):
        replace(result, workflow=result.brief_ready.workflow)


def test_to_dict_and_summary_are_deterministic_without_returned_content():
    first = _check(files=tuple(reversed(_safe_files())))
    second = _check(files=_safe_files())

    assert first.intake == second.intake
    assert first.to_dict() == second.to_dict()
    assert first.summary() == second.summary()
    assert json.loads(first.summary()) == first.to_dict()
    assert "content" not in first.to_dict()["intake"]["file_decisions"][0]


def test_summary_is_bounded_and_excludes_raw_or_operational_fields():
    summary_record = WorkerSummary(
        RAW_WORKER_SUMMARY,
        tests_run=("declared only",),
    )
    result = _check(worker_summary=summary_record)
    summary = result.summary()
    payload = json.loads(summary)

    assert len(summary.encode("utf-8")) <= MAX_WORKFLOW_INTAKE_SUMMARY_BYTES
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
        RAW_BRIEF_GOAL,
        RAW_BRIEF_CONSTRAINT,
        RAW_RETURNED_CONTENT,
        RAW_WORKER_SUMMARY,
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
        "content",
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


def test_adapter_stops_before_evidence_and_all_later_artifacts():
    result = _check()

    assert result.workflow.completed_steps == (
        STEP_REQUEST_RECEIVED,
        STEP_JOB_CREATED,
        STEP_SCOPE_FROZEN,
        STEP_BRIEF_READY,
        STEP_WORKER_RETURNED,
        STEP_INTAKE_CHECKED,
    )
    assert STEP_EVIDENCE_ATTACHED not in result.workflow.completed_steps
    assert result.next_allowed_steps == (STEP_EVIDENCE_ATTACHED,)


def test_adapter_module_has_only_permitted_intake_authority():
    source_path = (
        Path(__file__).parents[1]
        / "scripts"
        / "capability_build"
        / "workflow_intake.py"
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
    assert "validate_returned_files" in calls
    assert calls.count("record_workflow_step") >= 2
    assert "backend.tool_registry" not in source
