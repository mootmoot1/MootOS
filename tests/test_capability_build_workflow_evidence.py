"""Tests for V0.4B Slice 9 guarded explicit-evidence attachment."""

import ast
import json
from dataclasses import FrozenInstanceError, replace
from pathlib import Path

import pytest

from scripts.capability_build.evidence import (
    EvidenceRecord,
    build_default_verification_plan,
    evaluate_evidence,
)
from scripts.capability_build.intake import ReturnedFile
from scripts.capability_build.job_binding import BuildJobBinding
from scripts.capability_build.request import CapabilityBuildRequest
from scripts.capability_build.request_workflow import (
    start_workflow_from_request,
)
from scripts.capability_build.workflow import (
    STEP_BRIEF_READY,
    STEP_BUNDLE_CREATED,
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
from scripts.capability_build.workflow_evidence import (
    MAX_WORKFLOW_EVIDENCE_SUMMARY_BYTES,
    STATUS_EVIDENCE_ATTACHED,
    STATUS_NOT_ATTACHED,
    WorkflowEvidenceAttachment,
    WorkflowEvidenceError,
    attach_evidence_from_workflow_intake,
)
from scripts.capability_build.workflow_intake import (
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
RAW_REQUEST_GOAL = "RAW_EVIDENCE_REQUEST_GOAL_MUST_NOT_APPEAR"
RAW_REQUEST_BEHAVIOR = "RAW_EVIDENCE_REQUEST_BEHAVIOR_MUST_NOT_APPEAR"
RAW_REQUEST_CONSTRAINT = "RAW_EVIDENCE_REQUEST_CONSTRAINT_MUST_NOT_APPEAR"
RAW_BINDING_NOTE = "RAW_EVIDENCE_BINDING_NOTE_MUST_NOT_APPEAR"
RAW_JUSTIFICATION = "RAW_EVIDENCE_JUSTIFICATION_MUST_NOT_APPEAR"
RAW_BRIEF_GOAL = "RAW_EVIDENCE_BRIEF_GOAL_MUST_NOT_APPEAR"
RAW_BRIEF_CONSTRAINT = "RAW_EVIDENCE_BRIEF_CONSTRAINT_MUST_NOT_APPEAR"
RAW_RETURNED_CONTENT = "RAW_EVIDENCE_RETURNED_CONTENT_MUST_NOT_APPEAR"
RAW_RECORD_SUMMARY = "RAW_EVIDENCE_RECORD_SUMMARY_MUST_NOT_APPEAR"
RAW_OUTPUT_EXCERPT = "RAW_EVIDENCE_OUTPUT_EXCERPT_MUST_NOT_APPEAR"


def _request(**overrides):
    values = {
        "request_id": "request-009",
        "capability_name": "Project insight",
        "user_goal": RAW_REQUEST_GOAL,
        "requested_behavior_summary": RAW_REQUEST_BEHAVIOR,
        "constraints": (RAW_REQUEST_CONSTRAINT,),
    }
    values.update(overrides)
    return CapabilityBuildRequest(**values)


def _binding(**overrides):
    values = {
        "job_id": "job-v04b-slice-9",
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
        "allowed_new_files": ("tests/test_widget.py",),
        "allowed_existing_files": ("backend/widgets.py",),
        "protected_files": ("ops/protected/**",),
        "forbidden_paths": ("private/**",),
        "justifications": {
            "tests/test_widget.py": RAW_JUSTIFICATION,
            "backend/widgets.py": "Update the approved implementation.",
        },
    }
    values.update(overrides)
    return values


def _brief_ready(scope_data=None):
    request = _request()
    start = start_workflow_from_request(request)
    creation = create_job_from_workflow_start(start, _binding())
    approved_scope = _scope_data() if scope_data is None else scope_data
    scope_freeze = freeze_scope_from_workflow_job(
        creation,
        approved_scope,
    )
    return render_brief_from_workflow_scope(
        scope_freeze,
        RAW_BRIEF_GOAL,
        (RAW_BRIEF_CONSTRAINT,),
    )


def _returned_files(*, blocked=False):
    implementation = (
        "import subprocess\n"
        if blocked
        else "def widget():\n    return "
        + repr(RAW_RETURNED_CONTENT)
        + "\n"
    )
    return (
        ReturnedFile("backend/widgets.py", "modify", implementation),
        ReturnedFile(
            "tests/test_widget.py",
            "create",
            "def test_widget():\n    assert True\n",
        ),
    )


def _intake_check(*, blocked=False, invalid_return=False):
    files = () if invalid_return else _returned_files(blocked=blocked)
    return check_returned_worker_from_workflow_brief(
        _brief_ready(),
        files,
    )


def _records_for(intake_check, status="passed"):
    plan = build_default_verification_plan(intake_check.intake)
    return tuple(
        EvidenceRecord(
            command_name=command.name,
            status=status,
            summary=RAW_RECORD_SUMMARY + " " + command.name,
            exit_code=0 if status == "passed" else 1,
            output_excerpt=RAW_OUTPUT_EXCERPT,
        )
        for command in plan.commands
    )


def _attach(intake_check=None, records=None):
    actual_intake = intake_check or _intake_check()
    actual_records = (
        _records_for(actual_intake) if records is None else records
    )
    return attach_evidence_from_workflow_intake(
        actual_intake,
        actual_records,
    )


def test_valid_intake_and_explicit_records_attach_existing_evidence_bundle():
    intake_check = _intake_check()
    records = _records_for(intake_check)

    result = _attach(intake_check, records)

    expected_plan = build_default_verification_plan(intake_check.intake)
    expected = evaluate_evidence(expected_plan, records)
    assert isinstance(result, WorkflowEvidenceAttachment)
    assert result.schema_version == 1
    assert result.status == STATUS_EVIDENCE_ATTACHED
    assert result.attached is True
    assert result.accepted is True
    assert result.blocking_reasons == ()
    assert result.evidence == expected
    assert result.offline_only is True
    assert result.autonomous is False
    assert result.runtime_authority is False


def test_evidence_identity_scope_and_intake_match_authoritative_state():
    intake_check = _intake_check()

    result = _attach(intake_check)

    job = intake_check.brief_ready.scope_freeze.creation.job
    assert result.job_id == job.job_id
    assert result.capability_id == job.capability_id
    assert result.spec_sha256 == job.spec_sha256
    assert result.base_sha == job.base_sha
    assert result.scope is intake_check.scope
    assert result.intake is intake_check.intake
    assert result.evidence.plan.touched_files == result.intake.touched_files


def test_workflow_advances_exactly_once_to_evidence_attached():
    intake_check = _intake_check()
    original_workflow = intake_check.workflow

    result = _attach(intake_check)

    assert intake_check.workflow is original_workflow
    assert intake_check.workflow.completed_steps == (
        STEP_REQUEST_RECEIVED,
        STEP_JOB_CREATED,
        STEP_SCOPE_FROZEN,
        STEP_BRIEF_READY,
        STEP_WORKER_RETURNED,
        STEP_INTAKE_CHECKED,
    )
    assert result.workflow.completed_steps == (
        STEP_REQUEST_RECEIVED,
        STEP_JOB_CREATED,
        STEP_SCOPE_FROZEN,
        STEP_BRIEF_READY,
        STEP_WORKER_RETURNED,
        STEP_INTAKE_CHECKED,
        STEP_EVIDENCE_ATTACHED,
    )
    assert result.workflow.current_step == STEP_EVIDENCE_ATTACHED
    assert result.next_allowed_steps == (STEP_BUNDLE_CREATED,)
    assert result.workflow.next_allowed_steps == (STEP_BUNDLE_CREATED,)


def test_not_checked_intake_does_not_attach_or_advance():
    intake_check = _intake_check(invalid_return=True)

    result = _attach(intake_check, records=object())

    assert result.status == STATUS_NOT_ATTACHED
    assert result.attached is False
    assert result.accepted is False
    assert result.evidence is None
    assert result.workflow is intake_check.workflow
    assert result.blocking_reasons == intake_check.blocking_reasons


def test_blocked_intake_cannot_attach_evidence_under_existing_model():
    intake_check = _intake_check(blocked=True)

    result = _attach(intake_check, records=())

    assert intake_check.checked is True
    assert intake_check.accepted is False
    assert result.status == STATUS_NOT_ATTACHED
    assert result.evidence is None
    assert result.workflow is intake_check.workflow
    assert result.blocking_reasons == intake_check.blocking_reasons
    assert any("subprocess" in reason for reason in result.blocking_reasons)


@pytest.mark.parametrize(
    "records",
    [None, "records", (object(),)],
)
def test_invalid_evidence_input_does_not_attach_or_advance(records):
    intake_check = _intake_check()

    result = attach_evidence_from_workflow_intake(intake_check, records)

    assert result.status == STATUS_NOT_ATTACHED
    assert result.attached is False
    assert result.evidence is None
    assert result.workflow is intake_check.workflow
    assert result.blocking_reasons == (
        "Explicit evidence input is invalid.",
    )


def test_unknown_evidence_command_is_invalid_and_does_not_advance():
    intake_check = _intake_check()
    unknown = EvidenceRecord(
        "unknown-command",
        "passed",
        "Unknown result.",
    )

    result = _attach(intake_check, records=(unknown,))

    assert result.status == STATUS_NOT_ATTACHED
    assert result.evidence is None
    assert result.workflow is intake_check.workflow


def test_failed_and_incomplete_evidence_are_valid_attachments():
    intake_check = _intake_check()
    failed = _attach(intake_check, _records_for(intake_check, "failed"))
    incomplete = _attach(intake_check, ())

    assert failed.status == STATUS_EVIDENCE_ATTACHED
    assert failed.evidence.status == "failed"
    assert failed.accepted is False
    assert failed.blocking_reasons == (
        "Verification evidence is failed.",
    )
    assert incomplete.status == STATUS_EVIDENCE_ATTACHED
    assert incomplete.evidence.status == "incomplete"
    assert incomplete.accepted is False
    assert incomplete.blocking_reasons == (
        "Verification evidence is incomplete.",
    )
    assert incomplete.next_allowed_steps == (STEP_BUNDLE_CREATED,)


@pytest.mark.parametrize("invalid", [None, {}, "intake", object()])
def test_invalid_workflow_intake_input_is_rejected_deterministically(invalid):
    with pytest.raises(WorkflowEvidenceError, match="WorkflowIntakeCheck"):
        attach_evidence_from_workflow_intake(invalid, ())


def test_result_is_immutable_and_inputs_are_not_mutated():
    intake_check = _intake_check()
    records = _records_for(intake_check)
    intake_before = intake_check.to_dict()

    result = _attach(intake_check, records)

    assert intake_check.to_dict() == intake_before
    assert records == _records_for(intake_check)
    with pytest.raises(FrozenInstanceError):
        result.status = STATUS_NOT_ATTACHED
    with pytest.raises(FrozenInstanceError):
        result.workflow.completed_steps = ()
    with pytest.raises(FrozenInstanceError):
        result.scope.allowed_new_files = ()


def test_direct_construction_cannot_forge_result_invariants():
    result = _attach()

    with pytest.raises(WorkflowEvidenceError, match="status"):
        replace(result, status=STATUS_NOT_ATTACHED)
    with pytest.raises(WorkflowEvidenceError, match="blocking reasons"):
        replace(result, blocking_reasons=("Forged blocker.",))
    with pytest.raises(WorkflowEvidenceError, match="blocking reasons"):
        replace(result, evidence=None, status=STATUS_NOT_ATTACHED)
    with pytest.raises(WorkflowEvidenceError, match="evidence_attached"):
        replace(result, workflow=result.intake_check.workflow)


def test_to_dict_and_summary_are_deterministic_without_evidence_prose():
    intake_check = _intake_check()
    records = _records_for(intake_check)
    first = _attach(intake_check, tuple(reversed(records)))
    second = _attach(intake_check, records)

    assert first.evidence == second.evidence
    assert first.to_dict() == second.to_dict()
    assert first.summary() == second.summary()
    assert json.loads(first.summary()) == first.to_dict()
    assert "argv" not in first.to_dict()["evidence"]["commands"][0]
    assert "summary" not in first.to_dict()["evidence"]["records"][0]
    assert "output_excerpt" not in first.to_dict()["evidence"]["records"][0]


def test_summary_is_bounded_and_excludes_raw_or_operational_fields():
    result = _attach()
    summary = result.summary()
    payload = json.loads(summary)

    assert len(summary.encode("utf-8")) <= (
        MAX_WORKFLOW_EVIDENCE_SUMMARY_BYTES
    )
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
        RAW_RECORD_SUMMARY,
        RAW_OUTPUT_EXCERPT,
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
        "evidence_excerpt",
        "output_excerpt",
        "logs",
        "stdout",
        "stderr",
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


def test_adapter_stops_before_bundle_and_all_later_artifacts():
    result = _attach()

    assert result.workflow.completed_steps == (
        STEP_REQUEST_RECEIVED,
        STEP_JOB_CREATED,
        STEP_SCOPE_FROZEN,
        STEP_BRIEF_READY,
        STEP_WORKER_RETURNED,
        STEP_INTAKE_CHECKED,
        STEP_EVIDENCE_ATTACHED,
    )
    assert STEP_BUNDLE_CREATED not in result.workflow.completed_steps
    assert result.next_allowed_steps == (STEP_BUNDLE_CREATED,)


def test_adapter_module_has_only_permitted_evidence_authority():
    source_path = (
        Path(__file__).parents[1]
        / "scripts"
        / "capability_build"
        / "workflow_evidence.py"
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
    assert "build_default_verification_plan" in calls
    assert "evaluate_evidence" in calls
    assert "record_workflow_step" in calls
    assert "backend.tool_registry" not in source
