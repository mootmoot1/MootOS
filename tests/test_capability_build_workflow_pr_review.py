"""Tests for V0.4C Slice 5 human-review-pending transition."""

import ast
import json
from dataclasses import FrozenInstanceError, replace
from pathlib import Path

import pytest

from scripts.capability_build.evidence import (
    EvidenceRecord,
    build_default_verification_plan,
)
from scripts.capability_build.handoff import (
    DECISION_APPROVE_FOR_PR,
    DECISION_REJECT,
    DECISION_REQUEST_CHANGES,
)
from scripts.capability_build.intake import ReturnedFile
from scripts.capability_build.job_binding import BuildJobBinding
from scripts.capability_build.request import CapabilityBuildRequest
from scripts.capability_build.request_workflow import (
    start_workflow_from_request,
)
from scripts.capability_build.workflow import (
    STEP_HANDOFF_CREATED,
    STEP_HUMAN_DECISION_PENDING,
    STATUS_COMPLETE,
    WORKFLOW_STEPS,
)
from scripts.capability_build.workflow_brief import (
    render_brief_from_workflow_scope,
)
from scripts.capability_build.workflow_bundle import (
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
    create_pr_package_from_workflow_handoff,
)
from scripts.capability_build.workflow_pr_package_renderer import (
    DISPOSITION_BLOCKED_INSPECTION_ONLY,
    DISPOSITION_NOT_RENDERED,
    DISPOSITION_READY_FOR_HUMAN_REVIEW,
    render_pr_package_from_workflow_creation,
)
from scripts.capability_build.workflow_pr_review import (
    BLOCKED_DECISION_OPTIONS,
    MAX_WORKFLOW_PR_REVIEW_SUMMARY_BYTES,
    NO_DECISION_OPTIONS,
    READY_DECISION_OPTIONS,
    STATUS_HUMAN_REVIEW_PENDING,
    STATUS_NOT_PENDING,
    WorkflowPRReviewError,
    WorkflowPRReviewPending,
    enter_human_review_pending,
)
from scripts.capability_build.workflow_scope import (
    freeze_scope_from_workflow_job,
)


SPEC_SHA256 = "e" * 64
BASE_SHA = "f" * 40
RAW_MARKERS = (
    "RAW_REVIEW_REQUEST_GOAL",
    "RAW_REVIEW_REQUEST_BEHAVIOR",
    "RAW_REVIEW_REQUEST_CONSTRAINT",
    "RAW_REVIEW_BINDING_NOTE",
    "RAW_REVIEW_JUSTIFICATION",
    "RAW_REVIEW_BRIEF_GOAL",
    "RAW_REVIEW_BRIEF_CONSTRAINT",
    "RAW_REVIEW_RETURNED_CONTENT",
    "RAW_REVIEW_RECORD_SUMMARY",
    "RAW_REVIEW_OUTPUT_EXCERPT",
)


def _source(status="passed", *, no_evidence=False):
    request = CapabilityBuildRequest(
        request_id="request-v04c-slice-5",
        capability_name="Project insight",
        user_goal=RAW_MARKERS[0],
        requested_behavior_summary=RAW_MARKERS[1],
        constraints=(RAW_MARKERS[2],),
    )
    start = start_workflow_from_request(request)
    job = create_job_from_workflow_start(
        start,
        BuildJobBinding(
            job_id="job-v04c-slice-5",
            capability_id="projects.insight",
            spec_sha256=SPEC_SHA256,
            base_sha=BASE_SHA,
            actor="human:reviewer",
            note=RAW_MARKERS[3],
        ),
    )
    scope = freeze_scope_from_workflow_job(
        job,
        {
            "allowed_new_files": ("tests/test_widget.py",),
            "allowed_existing_files": ("backend/widgets.py",),
            "protected_files": ("ops/protected/**",),
            "forbidden_paths": ("private/**",),
            "justifications": {
                "tests/test_widget.py": RAW_MARKERS[4],
                "backend/widgets.py": "Update approved implementation.",
            },
        },
    )
    brief = render_brief_from_workflow_scope(
        scope,
        RAW_MARKERS[5],
        (RAW_MARKERS[6],),
    )
    intake = check_returned_worker_from_workflow_brief(
        brief,
        (
            ReturnedFile(
                "backend/widgets.py",
                "modify",
                f"VALUE = {RAW_MARKERS[7]!r}\n",
            ),
            ReturnedFile(
                "tests/test_widget.py",
                "create",
                "def test_widget():\n    assert True\n",
            ),
        ),
    )
    plan = build_default_verification_plan(intake.intake)
    records = None if no_evidence else tuple(
        EvidenceRecord(
            command_name=command.name,
            status=status,
            summary=f"{RAW_MARKERS[8]} {command.name}",
            exit_code=0 if status == "passed" else 1,
            output_excerpt=RAW_MARKERS[9],
        )
        for command in plan.commands
    )
    evidence = attach_evidence_from_workflow_intake(intake, records)
    bundle = create_bundle_from_workflow_evidence(evidence)
    handoff = create_handoff_from_workflow_bundle(bundle)
    creation = create_pr_package_from_workflow_handoff(handoff)
    return render_pr_package_from_workflow_creation(creation)


def test_ready_rendering_enters_human_review_pending():
    source = _source()
    prior = source.workflow

    result = enter_human_review_pending(source)

    assert isinstance(result, WorkflowPRReviewPending)
    assert result.status == STATUS_HUMAN_REVIEW_PENDING
    assert result.pending is True
    assert result.disposition == DISPOSITION_READY_FOR_HUMAN_REVIEW
    assert result.prior_workflow is prior
    assert result.workflow is not prior
    assert prior.current_step == STEP_HANDOFF_CREATED
    assert prior.next_allowed_steps == (STEP_HUMAN_DECISION_PENDING,)
    assert result.workflow.completed_steps == WORKFLOW_STEPS
    assert result.workflow.current_step == STEP_HUMAN_DECISION_PENDING
    assert result.workflow.status == STATUS_COMPLETE


def test_ready_result_exposes_exactly_three_fixed_choices():
    result = enter_human_review_pending(_source())

    assert result.decision_options == READY_DECISION_OPTIONS
    assert result.decision_options == (
        DECISION_APPROVE_FOR_PR,
        DECISION_REQUEST_CHANGES,
        DECISION_REJECT,
    )
    assert result.approved is False
    assert result.human_decision_recorded is False


@pytest.mark.parametrize("status", ["failed", "blocked"])
def test_blocked_rendering_enters_inspection_only_review(status):
    source = _source(status)

    result = enter_human_review_pending(source)

    assert result.status == STATUS_HUMAN_REVIEW_PENDING
    assert result.pending is True
    assert result.disposition == DISPOSITION_BLOCKED_INSPECTION_ONLY
    assert result.inspection_only is True
    assert result.decision_options == BLOCKED_DECISION_OPTIONS
    assert result.decision_options == (
        DECISION_REQUEST_CHANGES,
        DECISION_REJECT,
    )
    assert DECISION_APPROVE_FOR_PR not in result.decision_options
    assert result.approved is False
    assert result.human_decision_recorded is False


def test_not_rendered_source_fails_closed_and_does_not_advance():
    source = _source(no_evidence=True)
    assert source.disposition == DISPOSITION_NOT_RENDERED

    result = enter_human_review_pending(source)

    assert result.status == STATUS_NOT_PENDING
    assert result.pending is False
    assert result.workflow is source.workflow
    assert result.prior_workflow is source.workflow
    assert result.workflow.current_step == source.workflow.current_step
    assert STEP_HUMAN_DECISION_PENDING not in (
        result.workflow.completed_steps
    )
    assert result.decision_options == NO_DECISION_OPTIONS
    assert result.human_decision_recorded is False


@pytest.mark.parametrize("invalid", [None, {}, "rendering", object()])
def test_invalid_input_type_is_rejected(invalid):
    with pytest.raises(
        WorkflowPRReviewError,
        match="WorkflowPRPackageRendering",
    ):
        enter_human_review_pending(invalid)


def test_prior_workflow_and_source_are_not_mutated():
    source = _source()
    prior_summary = source.workflow.summary()
    source_summary = source.summary()

    result = enter_human_review_pending(source)

    assert source.workflow.summary() == prior_summary
    assert source.summary() == source_summary
    assert STEP_HUMAN_DECISION_PENDING not in (
        result.prior_workflow.completed_steps
    )
    assert result.workflow.completed_steps[-1] == (
        STEP_HUMAN_DECISION_PENDING
    )


def test_source_rendering_package_and_job_identity_are_bound():
    source = _source()
    package = source.pr_package_creation.pr_package

    result = enter_human_review_pending(source)
    binding = result.to_dict()["source_binding"]

    assert result.source_rendering is source
    assert binding == {
        "job_id": package.job_id,
        "package_id": package.package_id,
        "package_rendering": {
            "disposition": source.disposition,
            "rendered": source.rendered,
            "schema_version": source.schema_version,
            "status": source.status,
        },
        "proposal_base_sha": package.base_sha,
    }


def test_forged_disposition_options_workflow_or_source_are_rejected():
    ready = enter_human_review_pending(_source())
    blocked = enter_human_review_pending(_source("failed"))

    with pytest.raises(WorkflowPRReviewError, match="disposition"):
        replace(ready, disposition=DISPOSITION_BLOCKED_INSPECTION_ONLY)
    with pytest.raises(WorkflowPRReviewError, match="decision options"):
        replace(ready, decision_options=BLOCKED_DECISION_OPTIONS)
    with pytest.raises(WorkflowPRReviewError, match="exact pending"):
        replace(ready, workflow=ready.prior_workflow)
    with pytest.raises(WorkflowPRReviewError, match="prior workflow"):
        replace(ready, source_rendering=blocked.source_rendering)


def test_repeated_transition_is_deterministic_and_result_is_immutable():
    source = _source()

    first = enter_human_review_pending(source)
    second = enter_human_review_pending(source)

    assert first == second
    assert first.summary() == second.summary()
    with pytest.raises(FrozenInstanceError):
        first.status = STATUS_NOT_PENDING
    with pytest.raises(FrozenInstanceError):
        first.workflow.completed_steps = ()


def test_summary_is_bounded_sanitized_and_has_no_decision_record():
    result = enter_human_review_pending(_source())
    summary = result.summary()
    payload = json.loads(summary)

    assert len(summary.encode("utf-8")) <= (
        MAX_WORKFLOW_PR_REVIEW_SUMMARY_BYTES
    )
    assert payload["authority"] == {
        "approved": False,
        "autonomous": False,
        "git_action_performed": False,
        "github_action_performed": False,
        "human_decision_recorded": False,
        "offline_only": True,
        "proposal_only": True,
        "runtime_authority": False,
    }
    assert all(marker not in summary for marker in RAW_MARKERS)
    forbidden = {
        "argv", "branch_created", "commit_created", "content",
        "environment", "human_decision", "logs", "output_excerpt",
        "pr_created", "prompt", "raw_prompt", "returned_content",
        "secret", "secrets", "stderr", "stdout", "worker_report",
    }

    def all_keys(value):
        if isinstance(value, dict):
            for key, child in value.items():
                yield key
                yield from all_keys(child)
        elif isinstance(value, list):
            for child in value:
                yield from all_keys(child)

    assert not forbidden & set(all_keys(payload))


def test_adapter_has_no_external_or_approval_execution_authority():
    source_path = (
        Path(__file__).parents[1]
        / "scripts"
        / "capability_build"
        / "workflow_pr_review.py"
    )
    source = source_path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    forbidden_imports = {
        "backend", "git", "github", "httpx", "os", "pathlib",
        "pygit2", "requests", "shutil", "subprocess",
    }
    forbidden_calls = {
        "Popen", "__import__", "approve", "compile", "create_branch",
        "create_commit", "create_pull_request", "deploy",
        "dispatch_worker", "eval", "exec", "execute", "install",
        "merge", "mkdir", "open", "push", "read_bytes", "read_text",
        "register", "reject", "remove", "rename", "run", "sandbox",
        "system", "unlink", "verify", "write_bytes", "write_text",
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
    assert not forbidden_calls & set(definitions)
    assert "backend.tool_registry" not in source
