"""Tests for V0.4B Slice 10 guarded review-bundle creation."""

import ast
import json
from dataclasses import FrozenInstanceError, replace
from pathlib import Path

import pytest

from scripts.capability_build.bundle import (
    READINESS_BLOCKED,
    READINESS_READY,
    BuildReviewBundle,
    build_review_bundle,
)
from scripts.capability_build.evidence import (
    EvidenceRecord,
    build_default_verification_plan,
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
    STEP_HANDOFF_CREATED,
    STEP_INTAKE_CHECKED,
    STEP_JOB_CREATED,
    STEP_REQUEST_RECEIVED,
    STEP_SCOPE_FROZEN,
    STEP_WORKER_RETURNED,
)
from scripts.capability_build.workflow_brief import (
    render_brief_from_workflow_scope,
)
from scripts.capability_build.workflow_bundle import (
    MAX_WORKFLOW_BUNDLE_SUMMARY_BYTES,
    STATUS_BUNDLE_CREATED,
    STATUS_NOT_CREATED,
    WorkflowBundleCreation,
    WorkflowBundleError,
    create_bundle_from_workflow_evidence,
)
from scripts.capability_build.workflow_evidence import (
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
RAW_REQUEST_GOAL = "RAW_BUNDLE_REQUEST_GOAL_MUST_NOT_APPEAR"
RAW_REQUEST_BEHAVIOR = "RAW_BUNDLE_REQUEST_BEHAVIOR_MUST_NOT_APPEAR"
RAW_REQUEST_CONSTRAINT = "RAW_BUNDLE_REQUEST_CONSTRAINT_MUST_NOT_APPEAR"
RAW_BINDING_NOTE = "RAW_BUNDLE_BINDING_NOTE_MUST_NOT_APPEAR"
RAW_JUSTIFICATION = "RAW_BUNDLE_JUSTIFICATION_MUST_NOT_APPEAR"
RAW_BRIEF_GOAL = "RAW_BUNDLE_BRIEF_GOAL_MUST_NOT_APPEAR"
RAW_BRIEF_CONSTRAINT = "RAW_BUNDLE_BRIEF_CONSTRAINT_MUST_NOT_APPEAR"
RAW_RETURNED_CONTENT = "RAW_BUNDLE_RETURNED_CONTENT_MUST_NOT_APPEAR"
RAW_RECORD_SUMMARY = "RAW_BUNDLE_RECORD_SUMMARY_MUST_NOT_APPEAR"
RAW_OUTPUT_EXCERPT = "RAW_BUNDLE_OUTPUT_EXCERPT_MUST_NOT_APPEAR"


def _request():
    return CapabilityBuildRequest(
        request_id="request-010",
        capability_name="Project insight",
        user_goal=RAW_REQUEST_GOAL,
        requested_behavior_summary=RAW_REQUEST_BEHAVIOR,
        constraints=(RAW_REQUEST_CONSTRAINT,),
    )


def _binding():
    return BuildJobBinding(
        job_id="job-v04b-slice-10",
        capability_id="projects.insight",
        spec_sha256=SPEC_SHA256,
        base_sha=BASE_SHA,
        actor="human:reviewer",
        note=RAW_BINDING_NOTE,
    )


def _scope_data():
    return {
        "allowed_new_files": ("tests/test_widget.py",),
        "allowed_existing_files": ("backend/widgets.py",),
        "protected_files": ("ops/protected/**",),
        "forbidden_paths": ("private/**",),
        "justifications": {
            "tests/test_widget.py": RAW_JUSTIFICATION,
            "backend/widgets.py": "Update the approved implementation.",
        },
    }


def _intake_check():
    start = start_workflow_from_request(_request())
    creation = create_job_from_workflow_start(start, _binding())
    scope_freeze = freeze_scope_from_workflow_job(
        creation,
        _scope_data(),
    )
    brief_ready = render_brief_from_workflow_scope(
        scope_freeze,
        RAW_BRIEF_GOAL,
        (RAW_BRIEF_CONSTRAINT,),
    )
    returned_files = (
        ReturnedFile(
            "backend/widgets.py",
            "modify",
            "def widget():\n    return "
            + repr(RAW_RETURNED_CONTENT)
            + "\n",
        ),
        ReturnedFile(
            "tests/test_widget.py",
            "create",
            "def test_widget():\n    assert True\n",
        ),
    )
    return check_returned_worker_from_workflow_brief(
        brief_ready,
        returned_files,
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


def _evidence_attachment(status="passed", *, incomplete=False):
    intake_check = _intake_check()
    records = () if incomplete else _records_for(intake_check, status)
    return attach_evidence_from_workflow_intake(
        intake_check,
        records,
    )


def test_attached_evidence_creates_existing_review_bundle():
    evidence_attachment = _evidence_attachment()

    result = create_bundle_from_workflow_evidence(evidence_attachment)

    intake_check = evidence_attachment.intake_check
    expected = build_review_bundle(
        intake_check.brief_ready.scope_freeze.creation.job,
        evidence_attachment.scope,
        evidence_attachment.intake,
        evidence_attachment.evidence.plan,
        evidence_attachment.evidence,
    )
    assert isinstance(result, WorkflowBundleCreation)
    assert result.schema_version == 1
    assert result.status == STATUS_BUNDLE_CREATED
    assert result.created is True
    assert result.ready_for_human_review is True
    assert result.blocking_reasons == ()
    assert isinstance(result.bundle, BuildReviewBundle)
    assert result.bundle == expected
    assert result.bundle.readiness_status == READINESS_READY
    assert result.offline_only is True
    assert result.autonomous is False
    assert result.runtime_authority is False


def test_bundle_identity_and_sources_match_authoritative_workflow_state():
    evidence_attachment = _evidence_attachment()

    result = create_bundle_from_workflow_evidence(evidence_attachment)

    job = (
        evidence_attachment.intake_check
        .brief_ready.scope_freeze.creation.job
    )
    assert result.bundle.job.job_id == job.job_id
    assert result.bundle.job.capability_id == job.capability_id
    assert result.bundle.job.spec_sha256 == job.spec_sha256
    assert result.bundle.job.base_sha == job.base_sha
    assert result.bundle.intake.touched_files == (
        evidence_attachment.intake.touched_files
    )
    assert result.bundle.evidence.status == evidence_attachment.evidence.status
    assert result.bundle.verification_plan.touched_files == (
        evidence_attachment.evidence.plan.touched_files
    )


def test_workflow_advances_exactly_once_to_bundle_created():
    evidence_attachment = _evidence_attachment()
    original_workflow = evidence_attachment.workflow

    result = create_bundle_from_workflow_evidence(evidence_attachment)

    assert evidence_attachment.workflow is original_workflow
    assert evidence_attachment.workflow.completed_steps == (
        STEP_REQUEST_RECEIVED,
        STEP_JOB_CREATED,
        STEP_SCOPE_FROZEN,
        STEP_BRIEF_READY,
        STEP_WORKER_RETURNED,
        STEP_INTAKE_CHECKED,
        STEP_EVIDENCE_ATTACHED,
    )
    assert result.workflow.completed_steps == (
        STEP_REQUEST_RECEIVED,
        STEP_JOB_CREATED,
        STEP_SCOPE_FROZEN,
        STEP_BRIEF_READY,
        STEP_WORKER_RETURNED,
        STEP_INTAKE_CHECKED,
        STEP_EVIDENCE_ATTACHED,
        STEP_BUNDLE_CREATED,
    )
    assert result.workflow.current_step == STEP_BUNDLE_CREATED
    assert result.next_allowed_steps == (STEP_HANDOFF_CREATED,)
    assert result.workflow.next_allowed_steps == (STEP_HANDOFF_CREATED,)


def test_not_attached_evidence_does_not_create_or_advance():
    intake_check = _intake_check()
    evidence_attachment = attach_evidence_from_workflow_intake(
        intake_check,
        None,
    )

    result = create_bundle_from_workflow_evidence(evidence_attachment)

    assert result.status == STATUS_NOT_CREATED
    assert result.created is False
    assert result.ready_for_human_review is False
    assert result.bundle is None
    assert result.workflow is evidence_attachment.workflow
    assert result.blocking_reasons == evidence_attachment.blocking_reasons


@pytest.mark.parametrize(
    "status,incomplete,expected_status,reason",
    [
        (
            "failed",
            False,
            "failed",
            "Verification evidence is failed.",
        ),
        (
            "blocked",
            False,
            "blocked",
            "Verification evidence is blocked.",
        ),
        (
            "passed",
            True,
            "incomplete",
            "Verification evidence is incomplete.",
        ),
    ],
)
def test_nonpassing_evidence_creates_truthful_blocked_bundle(
    status,
    incomplete,
    expected_status,
    reason,
):
    evidence_attachment = _evidence_attachment(
        status,
        incomplete=incomplete,
    )

    result = create_bundle_from_workflow_evidence(evidence_attachment)

    assert result.status == STATUS_BUNDLE_CREATED
    assert result.created is True
    assert result.ready_for_human_review is False
    assert result.bundle.readiness_status == READINESS_BLOCKED
    assert result.bundle.evidence.status == expected_status
    assert result.blocking_reasons == (reason,)
    assert result.next_allowed_steps == (STEP_HANDOFF_CREATED,)


@pytest.mark.parametrize("invalid", [None, {}, "evidence", object()])
def test_invalid_workflow_evidence_input_is_rejected_deterministically(
    invalid,
):
    with pytest.raises(
        WorkflowBundleError,
        match="WorkflowEvidenceAttachment",
    ):
        create_bundle_from_workflow_evidence(invalid)


def test_result_is_immutable_and_input_is_not_mutated():
    evidence_attachment = _evidence_attachment()
    before = evidence_attachment.to_dict()

    result = create_bundle_from_workflow_evidence(evidence_attachment)

    assert evidence_attachment.to_dict() == before
    with pytest.raises(FrozenInstanceError):
        result.status = STATUS_NOT_CREATED
    with pytest.raises(FrozenInstanceError):
        result.workflow.completed_steps = ()
    with pytest.raises(FrozenInstanceError):
        result.bundle.readiness_status = READINESS_BLOCKED


def test_direct_construction_cannot_forge_result_invariants():
    result = create_bundle_from_workflow_evidence(_evidence_attachment())

    with pytest.raises(WorkflowBundleError, match="status"):
        replace(result, status=STATUS_NOT_CREATED)
    with pytest.raises(WorkflowBundleError, match="blocking reasons"):
        replace(result, blocking_reasons=("Forged blocker.",))
    with pytest.raises(WorkflowBundleError, match="blocking reasons"):
        replace(result, bundle=None, status=STATUS_NOT_CREATED)
    with pytest.raises(WorkflowBundleError, match="bundle_created"):
        replace(result, workflow=result.evidence_attachment.workflow)


def test_to_dict_and_summary_are_deterministic_and_use_existing_bundle():
    first = create_bundle_from_workflow_evidence(_evidence_attachment())
    second = create_bundle_from_workflow_evidence(_evidence_attachment())

    assert first.bundle == second.bundle
    assert first.to_dict() == second.to_dict()
    assert first.summary() == second.summary()
    assert json.loads(first.summary()) == first.to_dict()
    assert first.to_dict()["bundle"] == first.bundle.to_dict()


def test_summary_is_bounded_and_excludes_raw_or_operational_fields():
    result = create_bundle_from_workflow_evidence(_evidence_attachment())
    summary = result.summary()
    payload = json.loads(summary)

    assert len(summary.encode("utf-8")) <= (
        MAX_WORKFLOW_BUNDLE_SUMMARY_BYTES
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


def test_adapter_stops_before_handoff_and_all_later_artifacts():
    result = create_bundle_from_workflow_evidence(_evidence_attachment())

    assert result.workflow.completed_steps == (
        STEP_REQUEST_RECEIVED,
        STEP_JOB_CREATED,
        STEP_SCOPE_FROZEN,
        STEP_BRIEF_READY,
        STEP_WORKER_RETURNED,
        STEP_INTAKE_CHECKED,
        STEP_EVIDENCE_ATTACHED,
        STEP_BUNDLE_CREATED,
    )
    assert STEP_HANDOFF_CREATED not in result.workflow.completed_steps
    assert result.next_allowed_steps == (STEP_HANDOFF_CREATED,)


def test_adapter_module_has_only_permitted_bundle_authority():
    source_path = (
        Path(__file__).parents[1]
        / "scripts"
        / "capability_build"
        / "workflow_bundle.py"
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
        "build_default_verification_plan",
        "evaluate_evidence",
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
    assert "build_review_bundle" in calls
    assert "record_workflow_step" in calls
    assert "backend.tool_registry" not in source
