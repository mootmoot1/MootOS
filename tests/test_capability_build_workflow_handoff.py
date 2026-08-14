"""Tests for V0.4B Slice 11 guarded human-handoff creation."""

import ast
import json
from dataclasses import FrozenInstanceError, replace
from pathlib import Path

import pytest

from scripts.capability_build.bundle import (
    READINESS_BLOCKED,
    READINESS_READY,
)
from scripts.capability_build.evidence import (
    EvidenceRecord,
    build_default_verification_plan,
)
from scripts.capability_build.handoff import (
    HumanHandoffPackage,
    build_human_handoff,
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
    STEP_HUMAN_DECISION_PENDING,
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
    STATUS_NOT_CREATED as STATUS_BUNDLE_NOT_CREATED,
    create_bundle_from_workflow_evidence,
)
from scripts.capability_build.workflow_evidence import (
    attach_evidence_from_workflow_intake,
)
from scripts.capability_build.workflow_handoff import (
    MAX_WORKFLOW_HANDOFF_SUMMARY_BYTES,
    STATUS_HANDOFF_CREATED,
    STATUS_NOT_CREATED,
    WorkflowHandoffCreation,
    WorkflowHandoffError,
    create_handoff_from_workflow_bundle,
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


SPEC_SHA256 = "c" * 64
BASE_SHA = "d" * 40
RAW_REQUEST_GOAL = "RAW_HANDOFF_REQUEST_GOAL_MUST_NOT_APPEAR"
RAW_REQUEST_BEHAVIOR = "RAW_HANDOFF_REQUEST_BEHAVIOR_MUST_NOT_APPEAR"
RAW_REQUEST_CONSTRAINT = "RAW_HANDOFF_REQUEST_CONSTRAINT_MUST_NOT_APPEAR"
RAW_BINDING_NOTE = "RAW_HANDOFF_BINDING_NOTE_MUST_NOT_APPEAR"
RAW_JUSTIFICATION = "RAW_HANDOFF_JUSTIFICATION_MUST_NOT_APPEAR"
RAW_BRIEF_GOAL = "RAW_HANDOFF_BRIEF_GOAL_MUST_NOT_APPEAR"
RAW_BRIEF_CONSTRAINT = "RAW_HANDOFF_BRIEF_CONSTRAINT_MUST_NOT_APPEAR"
RAW_RETURNED_CONTENT = "RAW_HANDOFF_RETURNED_CONTENT_MUST_NOT_APPEAR"
RAW_RECORD_SUMMARY = "RAW_HANDOFF_RECORD_SUMMARY_MUST_NOT_APPEAR"
RAW_OUTPUT_EXCERPT = "RAW_HANDOFF_OUTPUT_EXCERPT_MUST_NOT_APPEAR"


def _request():
    return CapabilityBuildRequest(
        request_id="request-011",
        capability_name="Project insight",
        user_goal=RAW_REQUEST_GOAL,
        requested_behavior_summary=RAW_REQUEST_BEHAVIOR,
        constraints=(RAW_REQUEST_CONSTRAINT,),
    )


def _binding():
    return BuildJobBinding(
        job_id="job-v04b-slice-11",
        capability_id="projects.insight",
        spec_sha256=SPEC_SHA256,
        base_sha=BASE_SHA,
        actor="human:reviewer",
        note=RAW_BINDING_NOTE,
    )


def _scope_data(*, reverse=False):
    new_files = ("tests/test_widget.py",)
    existing_files = ("backend/widgets.py",)
    if reverse:
        new_files = tuple(reversed(new_files))
        existing_files = tuple(reversed(existing_files))
    return {
        "allowed_new_files": new_files,
        "allowed_existing_files": existing_files,
        "protected_files": ("ops/protected/**",),
        "forbidden_paths": ("private/**",),
        "justifications": {
            "tests/test_widget.py": RAW_JUSTIFICATION,
            "backend/widgets.py": "Update the approved implementation.",
        },
    }


def _intake_check(*, reverse=False):
    start = start_workflow_from_request(_request())
    creation = create_job_from_workflow_start(start, _binding())
    scope_freeze = freeze_scope_from_workflow_job(
        creation,
        _scope_data(reverse=reverse),
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
    if reverse:
        returned_files = tuple(reversed(returned_files))
    return check_returned_worker_from_workflow_brief(
        brief_ready,
        returned_files,
    )


def _records_for(intake_check, status="passed", *, reverse=False):
    plan = build_default_verification_plan(intake_check.intake)
    records = tuple(
        EvidenceRecord(
            command_name=command.name,
            status=status,
            summary=RAW_RECORD_SUMMARY + " " + command.name,
            exit_code=0 if status == "passed" else 1,
            output_excerpt=RAW_OUTPUT_EXCERPT,
        )
        for command in plan.commands
    )
    return tuple(reversed(records)) if reverse else records


def _bundle_creation(
    status="passed",
    *,
    incomplete=False,
    reverse=False,
):
    intake_check = _intake_check(reverse=reverse)
    records = (
        ()
        if incomplete
        else _records_for(intake_check, status, reverse=reverse)
    )
    attachment = attach_evidence_from_workflow_intake(
        intake_check,
        records,
    )
    return create_bundle_from_workflow_evidence(attachment)


def _not_created_bundle():
    intake_check = _intake_check()
    attachment = attach_evidence_from_workflow_intake(
        intake_check,
        None,
    )
    return create_bundle_from_workflow_evidence(attachment)


def test_bundle_created_result_creates_existing_human_handoff():
    bundle_creation = _bundle_creation()

    result = create_handoff_from_workflow_bundle(bundle_creation)

    assert isinstance(result, WorkflowHandoffCreation)
    assert result.schema_version == 1
    assert result.status == STATUS_HANDOFF_CREATED
    assert result.created is True
    assert result.approvable is True
    assert result.blocking_reasons == ()
    assert isinstance(result.handoff, HumanHandoffPackage)
    assert result.handoff == build_human_handoff(bundle_creation.bundle)
    assert result.handoff.bundle_readiness_status == READINESS_READY
    assert result.handoff_only is True
    assert result.human_decision_recorded is False
    assert result.offline_only is True
    assert result.autonomous is False
    assert result.runtime_authority is False


def test_handoff_identity_and_metadata_bind_to_authoritative_bundle():
    bundle_creation = _bundle_creation()

    result = create_handoff_from_workflow_bundle(bundle_creation)

    bundle = bundle_creation.bundle
    source = result.to_dict()["source_binding"]
    assert result.handoff.job == bundle.job
    assert result.handoff.touched_files == bundle.intake.touched_files
    assert result.handoff.intake_accepted == bundle.intake.accepted
    assert result.handoff.evidence_status == bundle.evidence.status
    assert source["job"] == bundle.job.to_dict()
    assert source["frozen_scope"] == bundle.frozen_scope.to_dict()
    assert source["intake"] == bundle.intake.to_dict()
    assert source["evidence"] == bundle.evidence.to_dict()
    assert source["bundle"]["readiness_status"] == (
        bundle.readiness_status
    )


def test_workflow_advances_exactly_once_to_handoff_created():
    bundle_creation = _bundle_creation()
    original_workflow = bundle_creation.workflow

    result = create_handoff_from_workflow_bundle(bundle_creation)

    assert bundle_creation.workflow is original_workflow
    assert bundle_creation.workflow.completed_steps == (
        STEP_REQUEST_RECEIVED,
        STEP_JOB_CREATED,
        STEP_SCOPE_FROZEN,
        STEP_BRIEF_READY,
        STEP_WORKER_RETURNED,
        STEP_INTAKE_CHECKED,
        STEP_EVIDENCE_ATTACHED,
        STEP_BUNDLE_CREATED,
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
        STEP_HANDOFF_CREATED,
    )
    assert result.workflow.current_step == STEP_HANDOFF_CREATED
    assert result.next_allowed_steps == (STEP_HUMAN_DECISION_PENDING,)
    assert result.workflow.next_allowed_steps == (
        STEP_HUMAN_DECISION_PENDING,
    )
    assert STEP_HUMAN_DECISION_PENDING not in (
        result.workflow.completed_steps
    )


def test_not_created_bundle_does_not_create_handoff_or_advance():
    bundle_creation = _not_created_bundle()
    assert bundle_creation.status == STATUS_BUNDLE_NOT_CREATED

    result = create_handoff_from_workflow_bundle(bundle_creation)

    assert result.status == STATUS_NOT_CREATED
    assert result.created is False
    assert result.approvable is False
    assert result.handoff is None
    assert result.workflow is bundle_creation.workflow
    assert result.blocking_reasons == bundle_creation.blocking_reasons
    assert result.next_allowed_steps == bundle_creation.next_allowed_steps
    assert result.to_dict()["source_binding"] is None


@pytest.mark.parametrize(
    "status,incomplete,expected_evidence",
    [
        ("failed", False, "failed"),
        ("blocked", False, "blocked"),
        ("passed", True, "incomplete"),
    ],
)
def test_blocked_bundle_creates_truthful_nonapprovable_handoff(
    status,
    incomplete,
    expected_evidence,
):
    bundle_creation = _bundle_creation(status, incomplete=incomplete)
    assert bundle_creation.bundle.readiness_status == READINESS_BLOCKED

    result = create_handoff_from_workflow_bundle(bundle_creation)

    assert result.status == STATUS_HANDOFF_CREATED
    assert result.created is True
    assert result.approvable is False
    assert result.handoff.approvable is False
    assert result.handoff.bundle_readiness_status == READINESS_BLOCKED
    assert result.handoff.evidence_status == expected_evidence
    assert result.blocking_reasons == result.handoff.blocking_reasons
    assert result.next_allowed_steps == (STEP_HUMAN_DECISION_PENDING,)


@pytest.mark.parametrize("invalid", [None, {}, "bundle", object()])
def test_invalid_workflow_bundle_input_is_rejected_deterministically(
    invalid,
):
    with pytest.raises(
        WorkflowHandoffError,
        match="WorkflowBundleCreation",
    ):
        create_handoff_from_workflow_bundle(invalid)


def test_result_is_immutable_and_input_is_not_mutated():
    bundle_creation = _bundle_creation()
    before = bundle_creation.to_dict()

    result = create_handoff_from_workflow_bundle(bundle_creation)

    assert bundle_creation.to_dict() == before
    with pytest.raises(FrozenInstanceError):
        result.status = STATUS_NOT_CREATED
    with pytest.raises(FrozenInstanceError):
        result.workflow.completed_steps = ()
    with pytest.raises(FrozenInstanceError):
        result.handoff.approvable = False


def test_direct_construction_cannot_forge_result_invariants():
    result = create_handoff_from_workflow_bundle(_bundle_creation())
    blocked = create_handoff_from_workflow_bundle(
        _bundle_creation("failed")
    )

    with pytest.raises(WorkflowHandoffError, match="status"):
        replace(result, status=STATUS_NOT_CREATED)
    with pytest.raises(WorkflowHandoffError, match="blocking reasons"):
        replace(result, blocking_reasons=("Forged blocker.",))
    with pytest.raises(WorkflowHandoffError, match="handoff_created"):
        replace(result, workflow=result.bundle_creation.workflow)
    with pytest.raises(WorkflowHandoffError, match="authoritative"):
        replace(
            result,
            handoff=blocked.handoff,
            blocking_reasons=blocked.handoff.blocking_reasons,
        )


def test_to_dict_and_summary_are_deterministic_for_stable_inputs():
    first = create_handoff_from_workflow_bundle(_bundle_creation())
    second = create_handoff_from_workflow_bundle(
        _bundle_creation(reverse=True)
    )

    assert first.handoff == second.handoff
    assert first.to_dict() == second.to_dict()
    assert first.summary() == second.summary()
    assert json.loads(first.summary()) == first.to_dict()


def test_summary_is_bounded_and_excludes_raw_or_operational_fields():
    result = create_handoff_from_workflow_bundle(_bundle_creation())
    summary = result.summary()
    payload = json.loads(summary)

    assert len(summary.encode("utf-8")) <= (
        MAX_WORKFLOW_HANDOFF_SUMMARY_BYTES
    )
    assert payload["authority"] == {
        "autonomous": False,
        "handoff_only": True,
        "human_decision_recorded": False,
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
        "human_decision",
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


def test_adapter_stops_before_decision_pr_registry_install_and_deploy():
    result = create_handoff_from_workflow_bundle(_bundle_creation())

    assert result.workflow.current_step == STEP_HANDOFF_CREATED
    assert result.workflow.next_allowed_steps == (
        STEP_HUMAN_DECISION_PENDING,
    )
    assert result.human_decision_recorded is False
    assert result.handoff.handoff_only is True
    assert result.handoff.runtime_authority is False


def test_adapter_module_has_only_permitted_handoff_authority():
    source_path = (
        Path(__file__).parents[1]
        / "scripts"
        / "capability_build"
        / "workflow_handoff.py"
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
        "build_review_bundle",
        "create_pr",
        "open_pr",
        "register",
        "install",
        "deploy",
        "dispatch_worker",
        "execute",
        "verify",
        "sandbox",
        "approve",
        "reject",
    }
    forbidden_definitions = {
        "create_workspace_dirs",
        "create_pr",
        "open_pr",
        "register",
        "install",
        "deploy",
        "dispatch_worker",
        "execute",
        "verify",
        "sandbox",
        "approve",
        "reject",
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
    assert "build_human_handoff" in calls
    assert "record_workflow_step" in calls
    assert "backend.tool_registry" not in source
