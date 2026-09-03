"""Tests for V0.4C Slice 4 workflow PR package rendering."""

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
    MAX_BODY_BYTES,
    PREvidenceSummary,
    PRChecklistItem,
    PRFileSummary,
    PRPackageProposal,
    PRRiskSummary,
    PRRollbackNote,
)
from scripts.capability_build.pr_package_renderer import render_pr_package
from scripts.capability_build.request import CapabilityBuildRequest
from scripts.capability_build.request_workflow import (
    start_workflow_from_request,
)
from scripts.capability_build.workflow import STEP_HUMAN_DECISION_PENDING
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
    MAX_WORKFLOW_PR_PACKAGE_RENDERING_SUMMARY_BYTES,
    STATUS_NOT_RENDERED,
    STATUS_PR_PACKAGE_RENDERED,
    WorkflowPRPackageRenderError,
    WorkflowPRPackageRendering,
    render_pr_package_from_workflow_creation,
)
from scripts.capability_build.workflow_scope import (
    freeze_scope_from_workflow_job,
)


SPEC_SHA256 = "e" * 64
BASE_SHA = "f" * 40
RAW_MARKERS = (
    "RAW_SLICE4_REQUEST_GOAL",
    "RAW_SLICE4_REQUEST_BEHAVIOR",
    "RAW_SLICE4_REQUEST_CONSTRAINT",
    "RAW_SLICE4_BINDING_NOTE",
    "RAW_SLICE4_JUSTIFICATION",
    "RAW_SLICE4_BRIEF_GOAL",
    "RAW_SLICE4_BRIEF_CONSTRAINT",
    "RAW_SLICE4_RETURNED_CONTENT",
    "RAW_SLICE4_RECORD_SUMMARY",
    "RAW_SLICE4_OUTPUT_EXCERPT",
)


def _package_creation(status="passed", *, no_evidence=False):
    request = CapabilityBuildRequest(
        request_id="request-v04c-slice-4",
        capability_name="Project insight",
        user_goal=RAW_MARKERS[0],
        requested_behavior_summary=RAW_MARKERS[1],
        constraints=(RAW_MARKERS[2],),
    )
    start = start_workflow_from_request(request)
    job = create_job_from_workflow_start(
        start,
        BuildJobBinding(
            job_id="job-v04c-slice-4",
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
    return create_pr_package_from_workflow_handoff(handoff)


def _maximum_body_proposal():
    return PRPackageProposal(
        package_id="max-package",
        job_id="max-job",
        capability_id="projects.insight",
        base_sha=BASE_SHA,
        target_branch="main",
        proposed_branch_name="codex/v0.4c/max-package",
        proposed_commit_title="Render maximum package",
        proposed_pr_title="Render maximum package",
        proposed_pr_body="x" * MAX_BODY_BYTES,
        changed_files=(PRFileSummary("a.py", "modify", "Modify a."),),
        evidence=(PREvidenceSummary("tests", "passed"),),
        risks=(
            PRRiskSummary("risk", "low", "Bounded.", "Review it."),
        ),
        rollback_notes=(PRRollbackNote(1, "Discard it."),),
        human_checklist=(PRChecklistItem("review", "Review it."),),
        readiness_status="ready",
    )


def test_ready_proposal_renders_for_human_review():
    creation = _package_creation()

    result = render_pr_package_from_workflow_creation(creation)

    assert isinstance(result, WorkflowPRPackageRendering)
    assert result.status == STATUS_PR_PACKAGE_RENDERED
    assert result.disposition == DISPOSITION_READY_FOR_HUMAN_REVIEW
    assert result.rendered is True
    assert result.ready_for_human_review is True
    assert result.inspection_only is False
    assert result.blocking_reasons == ()
    assert result.rendering.proposal is creation.pr_package


@pytest.mark.parametrize("status", ["failed", "blocked"])
def test_blocked_proposal_renders_for_inspection_only(status):
    creation = _package_creation(status)

    result = render_pr_package_from_workflow_creation(creation)

    assert result.status == STATUS_PR_PACKAGE_RENDERED
    assert result.disposition == DISPOSITION_BLOCKED_INSPECTION_ONLY
    assert result.rendered is True
    assert result.ready_for_human_review is False
    assert result.inspection_only is True
    assert result.blocking_reasons == creation.pr_package.blocking_reasons
    assert "Readiness: `blocked`" in result.rendering.pr_body


def test_package_not_created_fails_closed_without_rendering():
    creation = _package_creation(no_evidence=True)

    result = render_pr_package_from_workflow_creation(creation)

    assert creation.pr_package is None
    assert result.status == STATUS_NOT_RENDERED
    assert result.disposition == DISPOSITION_NOT_RENDERED
    assert result.rendered is False
    assert result.rendering is None
    assert result.ready_for_human_review is False
    assert result.inspection_only is False


@pytest.mark.parametrize("invalid", [None, {}, "creation", object()])
def test_invalid_input_type_is_rejected(invalid):
    with pytest.raises(
        WorkflowPRPackageRenderError,
        match="WorkflowPRPackageCreation",
    ):
        render_pr_package_from_workflow_creation(invalid)


def test_source_identity_and_exact_workflow_are_preserved():
    creation = _package_creation()

    result = render_pr_package_from_workflow_creation(creation)
    binding = result.to_dict()["source_binding"]

    assert result.pr_package_creation is creation
    assert result.workflow is creation.workflow
    assert result.next_allowed_steps == (STEP_HUMAN_DECISION_PENDING,)
    assert binding["package_identity"] == {
        "base_sha": creation.pr_package.base_sha,
        "job_id": creation.pr_package.job_id,
        "package_id": creation.pr_package.package_id,
        "readiness_status": creation.pr_package.readiness_status,
    }


def test_forged_or_mismatched_rendering_is_rejected():
    ready = render_pr_package_from_workflow_creation(_package_creation())
    blocked = render_pr_package_from_workflow_creation(
        _package_creation("failed")
    )

    with pytest.raises(WorkflowPRPackageRenderError, match="authoritative"):
        replace(ready, rendering=blocked.rendering)
    with pytest.raises(WorkflowPRPackageRenderError, match="disposition"):
        replace(ready, disposition=DISPOSITION_BLOCKED_INSPECTION_ONLY)
    with pytest.raises(WorkflowPRPackageRenderError, match="exact workflow"):
        replace(ready, workflow=blocked.workflow)


def test_repeated_rendering_is_deterministic_and_result_is_immutable():
    creation = _package_creation()

    first = render_pr_package_from_workflow_creation(creation)
    second = render_pr_package_from_workflow_creation(creation)

    assert first == second
    assert first.summary() == second.summary()
    with pytest.raises(FrozenInstanceError):
        first.status = STATUS_NOT_RENDERED
    with pytest.raises(FrozenInstanceError):
        first.workflow.completed_steps = ()


def test_summary_is_bounded_sanitized_and_has_no_approval_state():
    result = render_pr_package_from_workflow_creation(_package_creation())
    summary = result.summary()
    payload = json.loads(summary)

    assert len(summary.encode("utf-8")) <= (
        MAX_WORKFLOW_PR_PACKAGE_RENDERING_SUMMARY_BYTES
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


def test_slice_3_maximum_size_proposal_regression():
    proposal = _maximum_body_proposal()

    rendering = render_pr_package(proposal)

    assert proposal.proposed_pr_body in rendering.pr_body


def test_adapter_has_no_external_or_mutation_authority():
    source_path = (
        Path(__file__).parents[1]
        / "scripts"
        / "capability_build"
        / "workflow_pr_package_renderer.py"
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
        "system", "transition", "unlink", "verify", "write_bytes",
        "write_text",
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
