"""Tests for V0.4C Slice 2 guarded PR package creation."""

import ast
import json
from dataclasses import FrozenInstanceError, replace
from pathlib import Path

import pytest

from scripts.capability_build.evidence import (
    EvidenceRecord,
    build_default_verification_plan,
)
from scripts.capability_build.intake import ReturnedFile
from scripts.capability_build.job_binding import BuildJobBinding
from scripts.capability_build.pr_package import (
    BLOCKED,
    READY,
    PRPackageProposal,
)
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
    create_handoff_from_workflow_bundle,
)
from scripts.capability_build.workflow_intake import (
    check_returned_worker_from_workflow_brief,
)
from scripts.capability_build.workflow_job import (
    create_job_from_workflow_start,
)
from scripts.capability_build.workflow_pr_package import (
    MAX_WORKFLOW_PR_PACKAGE_SUMMARY_BYTES,
    STATUS_NOT_CREATED,
    STATUS_PR_PACKAGE_CREATED,
    WorkflowPRPackageCreation,
    WorkflowPRPackageError,
    create_pr_package_from_workflow_handoff,
)
from scripts.capability_build.workflow_scope import (
    freeze_scope_from_workflow_job,
)


SPEC_SHA256 = "e" * 64
BASE_SHA = "f" * 40
RAW_REQUEST_GOAL = "RAW_PR_PACKAGE_REQUEST_GOAL_MUST_NOT_APPEAR"
RAW_REQUEST_BEHAVIOR = "RAW_PR_PACKAGE_REQUEST_BEHAVIOR_MUST_NOT_APPEAR"
RAW_REQUEST_CONSTRAINT = "RAW_PR_PACKAGE_REQUEST_CONSTRAINT_MUST_NOT_APPEAR"
RAW_BINDING_NOTE = "RAW_PR_PACKAGE_BINDING_NOTE_MUST_NOT_APPEAR"
RAW_JUSTIFICATION = "RAW_PR_PACKAGE_JUSTIFICATION_MUST_NOT_APPEAR"
RAW_BRIEF_GOAL = "RAW_PR_PACKAGE_BRIEF_GOAL_MUST_NOT_APPEAR"
RAW_BRIEF_CONSTRAINT = "RAW_PR_PACKAGE_BRIEF_CONSTRAINT_MUST_NOT_APPEAR"
RAW_RETURNED_CONTENT = "RAW_PR_PACKAGE_RETURNED_CONTENT_MUST_NOT_APPEAR"
RAW_RECORD_SUMMARY = "RAW_PR_PACKAGE_RECORD_SUMMARY_MUST_NOT_APPEAR"
RAW_OUTPUT_EXCERPT = "RAW_PR_PACKAGE_OUTPUT_EXCERPT_MUST_NOT_APPEAR"


def _request():
    return CapabilityBuildRequest(
        request_id="request-v04c-slice-2",
        capability_name="Project insight",
        user_goal=RAW_REQUEST_GOAL,
        requested_behavior_summary=RAW_REQUEST_BEHAVIOR,
        constraints=(RAW_REQUEST_CONSTRAINT,),
    )


def _binding():
    return BuildJobBinding(
        job_id="job-v04c-slice-2",
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


def _handoff_creation(status="passed", *, incomplete=False, reverse=False):
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
    bundle_creation = create_bundle_from_workflow_evidence(attachment)
    return create_handoff_from_workflow_bundle(bundle_creation)


def _not_created_handoff():
    intake_check = _intake_check()
    attachment = attach_evidence_from_workflow_intake(
        intake_check,
        None,
    )
    bundle_creation = create_bundle_from_workflow_evidence(attachment)
    assert bundle_creation.status == STATUS_BUNDLE_NOT_CREATED
    return create_handoff_from_workflow_bundle(bundle_creation)


def test_approvable_handoff_creates_ready_pr_package_proposal():
    handoff_creation = _handoff_creation()

    result = create_pr_package_from_workflow_handoff(handoff_creation)

    assert isinstance(result, WorkflowPRPackageCreation)
    assert result.schema_version == 1
    assert result.status == STATUS_PR_PACKAGE_CREATED
    assert result.created is True
    assert result.ready_for_pr is True
    assert result.blocking_reasons == ()
    assert isinstance(result.pr_package, PRPackageProposal)
    assert result.pr_package.readiness_status == READY
    assert result.pr_package.job_id == "job-v04c-slice-2"
    assert result.pr_package.capability_id == "projects.insight"
    assert result.pr_package.base_sha == BASE_SHA
    assert result.pr_package.target_branch == "main"
    assert result.pr_package.proposed_branch_name == (
        "codex/v0.4c/projects.insight/job-v04c-slice-2-pr-package"
    )
    assert result.offline_only is True
    assert result.proposal_only is True
    assert result.github_action_performed is False
    assert result.git_action_performed is False
    assert result.human_decision_recorded is False
    assert result.autonomous is False
    assert result.runtime_authority is False


def test_package_file_operations_come_from_frozen_scope():
    result = create_pr_package_from_workflow_handoff(_handoff_creation())

    operations = {
        item.path: item.operation for item in result.pr_package.changed_files
    }

    assert operations == {
        "backend/widgets.py": "modify",
        "tests/test_widget.py": "create",
    }


def test_package_binds_to_handoff_evidence_and_checklist():
    handoff_creation = _handoff_creation()

    result = create_pr_package_from_workflow_handoff(handoff_creation)

    package = result.pr_package
    assert tuple(item.check_name for item in package.evidence) == (
        "blocking-python-lint",
        "python-syntax",
        "targeted-tests",
    )
    assert all(item.status == "passed" for item in package.evidence)
    assert tuple(item.description for item in package.human_checklist) == (
        handoff_creation.handoff.checklist
    )
    assert result.to_dict()["source_binding"]["handoff"] == (
        handoff_creation.handoff.to_dict()
    )


@pytest.mark.parametrize(
    "status,incomplete,expected_blocker",
    [
        ("failed", False, "failed"),
        ("blocked", False, "blocked"),
        ("passed", True, "incomplete"),
    ],
)
def test_nonapprovable_handoff_creates_blocked_pr_package(
    status,
    incomplete,
    expected_blocker,
):
    handoff_creation = _handoff_creation(status, incomplete=incomplete)

    result = create_pr_package_from_workflow_handoff(handoff_creation)

    assert result.status == STATUS_PR_PACKAGE_CREATED
    assert result.created is True
    assert result.ready_for_pr is False
    assert result.pr_package.readiness_status == BLOCKED
    assert result.pr_package.blocking_reasons == (
        handoff_creation.handoff.blocking_reasons
    )
    assert result.blocking_reasons == result.pr_package.blocking_reasons
    assert any(
        expected_blocker in reason
        for reason in result.pr_package.blocking_reasons
    )


def test_not_created_handoff_does_not_create_pr_package_or_advance():
    handoff_creation = _not_created_handoff()

    result = create_pr_package_from_workflow_handoff(handoff_creation)

    assert result.status == STATUS_NOT_CREATED
    assert result.created is False
    assert result.ready_for_pr is False
    assert result.pr_package is None
    assert result.workflow is handoff_creation.workflow
    assert result.blocking_reasons == handoff_creation.blocking_reasons
    assert result.next_allowed_steps == handoff_creation.next_allowed_steps


def test_workflow_does_not_record_human_decision_or_pr_action():
    handoff_creation = _handoff_creation()

    result = create_pr_package_from_workflow_handoff(handoff_creation)

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
    assert result.workflow.next_allowed_steps == (
        STEP_HUMAN_DECISION_PENDING,
    )
    assert result.next_allowed_steps == (STEP_HUMAN_DECISION_PENDING,)
    assert STEP_HUMAN_DECISION_PENDING not in (
        result.workflow.completed_steps
    )
    assert result.human_decision_recorded is False
    assert result.github_action_performed is False
    assert result.git_action_performed is False


@pytest.mark.parametrize("invalid", [None, {}, "handoff", object()])
def test_invalid_workflow_handoff_input_is_rejected_deterministically(
    invalid,
):
    with pytest.raises(
        WorkflowPRPackageError,
        match="WorkflowHandoffCreation",
    ):
        create_pr_package_from_workflow_handoff(invalid)


def test_result_is_immutable_and_input_is_not_mutated():
    handoff_creation = _handoff_creation()
    before = handoff_creation.to_dict()

    result = create_pr_package_from_workflow_handoff(handoff_creation)

    assert handoff_creation.to_dict() == before
    with pytest.raises(FrozenInstanceError):
        result.status = STATUS_NOT_CREATED
    with pytest.raises(FrozenInstanceError):
        result.workflow.completed_steps = ()
    with pytest.raises(FrozenInstanceError):
        result.pr_package.readiness_status = BLOCKED


def test_direct_construction_cannot_forge_result_invariants():
    result = create_pr_package_from_workflow_handoff(_handoff_creation())
    blocked = create_pr_package_from_workflow_handoff(
        _handoff_creation("failed")
    )

    with pytest.raises(WorkflowPRPackageError, match="status"):
        replace(result, status=STATUS_NOT_CREATED)
    with pytest.raises(WorkflowPRPackageError, match="blocking reasons"):
        replace(result, blocking_reasons=("Forged blocker.",))
    with pytest.raises(WorkflowPRPackageError, match="advance"):
        replace(
            result,
            workflow=result.handoff_creation.bundle_creation.workflow,
        )
    with pytest.raises(WorkflowPRPackageError, match="authoritative"):
        replace(
            result,
            pr_package=blocked.pr_package,
            blocking_reasons=blocked.pr_package.blocking_reasons,
        )


def test_to_dict_and_summary_are_deterministic_for_stable_inputs():
    first = create_pr_package_from_workflow_handoff(_handoff_creation())
    second = create_pr_package_from_workflow_handoff(
        _handoff_creation(reverse=True)
    )

    assert first.pr_package == second.pr_package
    assert first.to_dict() == second.to_dict()
    assert first.summary() == second.summary()
    assert json.loads(first.summary()) == first.to_dict()


def test_summary_is_bounded_and_excludes_raw_or_operational_fields():
    result = create_pr_package_from_workflow_handoff(_handoff_creation())
    summary = result.summary()
    payload = json.loads(summary)

    assert len(summary.encode("utf-8")) <= (
        MAX_WORKFLOW_PR_PACKAGE_SUMMARY_BYTES
    )
    assert payload["authority"] == {
        "autonomous": False,
        "git_action_performed": False,
        "github_action_performed": False,
        "human_decision_recorded": False,
        "offline_only": True,
        "proposal_only": True,
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
        "pr_created",
        "commit_created",
        "branch_created",
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


def test_adapter_module_has_no_external_or_mutation_authority():
    source_path = (
        Path(__file__).parents[1]
        / "scripts"
        / "capability_build"
        / "workflow_pr_package.py"
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
        "create_branch",
        "create_commit",
        "create_pull_request",
        "register",
        "install",
        "deploy",
        "dispatch_worker",
        "execute",
        "verify",
        "sandbox",
        "approve",
        "reject",
        "merge",
        "push",
    }
    forbidden_definitions = {
        "create_workspace_dirs",
        "create_branch",
        "create_commit",
        "create_pull_request",
        "register",
        "install",
        "deploy",
        "dispatch_worker",
        "execute",
        "verify",
        "sandbox",
        "approve",
        "reject",
        "merge",
        "push",
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
    assert "backend.tool_registry" not in source
