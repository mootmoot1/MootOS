"""Focused tests for V0.4A Slice 6 pure human handoff packages."""

import ast
import json
from dataclasses import FrozenInstanceError, replace
from pathlib import Path

import pytest

from scripts.capability_build.bundle import (
    READINESS_BLOCKED,
    READINESS_INCOMPLETE,
    READINESS_READY,
    build_review_bundle,
)
from scripts.capability_build.evidence import (
    MAX_OUTPUT_EXCERPT_BYTES,
    EvidenceRecord,
    build_default_verification_plan,
    evaluate_evidence,
)
from scripts.capability_build.handoff import (
    DECISION_APPROVE_FOR_PR,
    DECISION_REJECT,
    DECISION_REQUEST_CHANGES,
    HUMAN_DECISION_OPTIONS,
    HUMAN_REVIEW_CHECKLIST,
    MAX_HANDOFF_SUMMARY_BYTES,
    MAX_HANDOFF_TEXT_BYTES,
    HandoffDecisionOption,
    HandoffError,
    build_human_handoff,
)
from scripts.capability_build.intake import (
    ReturnedFile,
    WorkerSummary,
    validate_returned_files,
)
from scripts.capability_build.job import new_job
from scripts.capability_build.scope import FrozenScope


SPEC_SHA256 = "b" * 64
BASE_SHA = "39501dd"
JOB_ID = "slice-6-human-handoff"
RAW_CONTENT_MARKER = "RAW_RETURNED_BODY_MUST_NOT_APPEAR"
WORKER_PROSE_MARKER = "WORKER_PROSE_MUST_NOT_APPEAR"
EVIDENCE_OUTPUT_MARKER = "EVIDENCE_OUTPUT_MUST_NOT_APPEAR"


def _job():
    return new_job(
        "projects.insight",
        SPEC_SHA256,
        BASE_SHA,
        actor="human:tester",
        note="Approve fixture; " + WORKER_PROSE_MARKER,
        job_id=JOB_ID,
    )


def _scope(*, reverse=False):
    paths = (
        "backend/tools_widget.py",
        "tests/test_widget.py",
    )
    if reverse:
        paths = tuple(reversed(paths))
    return FrozenScope(
        allowed_new_files=paths,
        justifications={
            "backend/tools_widget.py": "Adapter justification prose.",
            "tests/test_widget.py": "Test justification prose.",
        },
    )


def _accepted_intake(*, reverse=False):
    returned = (
        ReturnedFile(
            "backend/tools_widget.py",
            "create",
            "def widget():\n    return " + repr(RAW_CONTENT_MARKER) + "\n",
        ),
        ReturnedFile(
            "tests/test_widget.py",
            "create",
            "def test_widget():\n    assert True\n",
        ),
    )
    if reverse:
        returned = tuple(reversed(returned))
    return validate_returned_files(
        _scope(reverse=reverse),
        returned,
        WorkerSummary(summary=WORKER_PROSE_MARKER, tests_run=("pytest",)),
    )


def _failed_intake():
    return validate_returned_files(
        _scope(),
        (ReturnedFile("backend/unapproved.py", "create", "VALUE = 1\n"),),
    )


def _evidence(plan, status="passed", *, reverse=False):
    records = tuple(
        EvidenceRecord(
            command_name=command.name,
            status=status,
            summary=EVIDENCE_OUTPUT_MARKER,
            exit_code=0 if status == "passed" else 1,
            output_excerpt=(
                EVIDENCE_OUTPUT_MARKER
                + "x"
                * (MAX_OUTPUT_EXCERPT_BYTES - len(EVIDENCE_OUTPUT_MARKER))
            ),
        )
        for command in plan.commands
    )
    if reverse:
        records = tuple(reversed(records))
    return evaluate_evidence(plan, records)


def _bundle(
    *,
    intake=None,
    include_plan=True,
    evidence_status="passed",
    reverse=False,
):
    actual_intake = intake or _accepted_intake(reverse=reverse)
    plan = (
        build_default_verification_plan(actual_intake)
        if include_plan and actual_intake.accepted
        else None
    )
    evidence = (
        _evidence(plan, evidence_status, reverse=reverse)
        if plan is not None and evidence_status is not None
        else None
    )
    return build_review_bundle(
        _job(),
        _scope(reverse=reverse),
        actual_intake,
        plan,
        evidence,
    )


def test_ready_bundle_creates_approvable_handoff_only():
    handoff = build_human_handoff(_bundle())

    assert handoff.bundle_readiness_status == READINESS_READY
    assert handoff.approvable is True
    assert handoff.blocking_reasons == ()
    assert handoff.handoff_only is True
    assert handoff.runtime_authority is False
    assert handoff.bundle_review_only is True
    assert handoff.bundle_runtime_authority is False
    assert handoff.intake_accepted is True
    assert handoff.evidence_accepted is True
    assert handoff.evidence_status == "passed"
    assert handoff.decision_options[0].name == DECISION_APPROVE_FOR_PR
    assert handoff.decision_options[0].available is True


def test_blocked_failed_intake_is_not_approvable_with_reasons():
    handoff = build_human_handoff(_bundle(intake=_failed_intake()))

    assert handoff.bundle_readiness_status == READINESS_BLOCKED
    assert handoff.approvable is False
    assert handoff.intake_accepted is False
    assert any(
        "intake" in reason.lower() for reason in handoff.blocking_reasons
    )
    assert handoff.decision_options[0].available is False


@pytest.mark.parametrize("include_plan", [False, True])
def test_incomplete_or_missing_evidence_is_not_approvable(include_plan):
    handoff = build_human_handoff(
        _bundle(include_plan=include_plan, evidence_status=None)
    )

    assert handoff.bundle_readiness_status == READINESS_INCOMPLETE
    assert handoff.approvable is False
    assert handoff.evidence_present is False
    assert handoff.evidence_accepted is None
    assert handoff.evidence_status is None
    assert any(
        "evidence is missing" in reason.lower()
        for reason in handoff.blocking_reasons
    )


@pytest.mark.parametrize(
    "evidence_status,expected_status",
    [
        ("failed", "failed"),
        ("blocked", "blocked"),
        ("not_run", "incomplete"),
    ],
)
def test_failed_blocked_and_not_run_evidence_block_approval(
    evidence_status, expected_status
):
    handoff = build_human_handoff(
        _bundle(evidence_status=evidence_status)
    )

    assert handoff.bundle_readiness_status == READINESS_BLOCKED
    assert handoff.approvable is False
    assert handoff.evidence_accepted is False
    assert handoff.evidence_status == expected_status
    assert any(
        expected_status in reason for reason in handoff.blocking_reasons
    )


def test_handoff_is_deterministic_regardless_of_artifact_order():
    forward = build_human_handoff(_bundle())
    reverse = build_human_handoff(_bundle(reverse=True))

    assert forward == reverse
    assert forward.to_dict() == reverse.to_dict()
    assert forward.summary() == reverse.summary()
    assert forward.touched_files == (
        "backend/tools_widget.py",
        "tests/test_widget.py",
    )


def test_handoff_summary_excludes_raw_and_sensitive_artifacts():
    summary = build_human_handoff(_bundle()).summary()
    payload = json.loads(summary)

    for excluded in (
        RAW_CONTENT_MARKER,
        WORKER_PROSE_MARKER,
        EVIDENCE_OUTPUT_MARKER,
        "Adapter justification prose.",
        "Test justification prose.",
    ):
        assert excluded not in summary
    for excluded_key in (
        "argv",
        "output_excerpt",
        "prompt",
        "raw_prompt",
        "secret",
        "secrets",
        "worker_report",
        "returned_content",
    ):
        assert excluded_key not in summary
    assert payload["authority"] == {
        "handoff_only": True,
        "runtime_authority": False,
    }


def test_handoff_models_are_immutable():
    handoff = build_human_handoff(_bundle())

    with pytest.raises(FrozenInstanceError):
        handoff.approvable = False
    with pytest.raises(FrozenInstanceError):
        handoff.job.state = "installed"
    with pytest.raises(FrozenInstanceError):
        handoff.decision_options[0].available = False


def test_text_and_total_handoff_summary_are_bounded():
    with pytest.raises(HandoffError, match="exceeds"):
        HandoffDecisionOption(
            DECISION_REJECT,
            True,
            "x" * (MAX_HANDOFF_TEXT_BYTES + 1),
        )
    with pytest.raises(HandoffError, match="fixed option text"):
        HandoffDecisionOption(
            DECISION_REJECT,
            True,
            "Arbitrary worker-controlled prose.",
        )

    handoff = build_human_handoff(_bundle())
    assert len(handoff.summary().encode("utf-8")) <= (
        MAX_HANDOFF_SUMMARY_BYTES
    )
    oversized_paths = tuple(
        f"file-{index}-" + "x" * 3_000 for index in range(12)
    )
    with pytest.raises(HandoffError, match="summary exceeds"):
        replace(handoff, touched_files=oversized_paths)


def test_human_decision_options_and_checklist_are_stable():
    handoff = build_human_handoff(_bundle())

    assert tuple(option.name for option in handoff.decision_options) == (
        DECISION_APPROVE_FOR_PR,
        DECISION_REQUEST_CHANGES,
        DECISION_REJECT,
    )
    assert HUMAN_DECISION_OPTIONS == tuple(
        option.name for option in handoff.decision_options
    )
    assert handoff.checklist == HUMAN_REVIEW_CHECKLIST
    assert all(option.available for option in handoff.decision_options)


def test_missing_or_wrong_bundle_is_rejected():
    for invalid in (None, {}, "bundle"):
        with pytest.raises(HandoffError, match="BuildReviewBundle"):
            build_human_handoff(invalid)


def test_handoff_module_has_no_external_or_mutation_authority():
    source_path = (
        Path(__file__).parents[1]
        / "scripts"
        / "capability_build"
        / "handoff.py"
    )
    source = source_path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    forbidden_imports = {
        "backend",
        "git",
        "github",
        "os",
        "pathlib",
        "pygit2",
        "dulwich",
        "shutil",
        "subprocess",
    }
    forbidden_calls = {
        "eval",
        "exec",
        "open",
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
        "github_request",
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
