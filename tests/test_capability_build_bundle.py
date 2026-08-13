"""Focused tests for the V0.4A Slice 5 pure build review bundle."""

import ast
import json
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from scripts.capability_build.bundle import (
    MAX_BUNDLE_SUMMARY_BYTES,
    MAX_BUNDLE_TEXT_BYTES,
    READINESS_BLOCKED,
    READINESS_INCOMPLETE,
    READINESS_READY,
    BundleError,
    build_review_bundle,
)
from scripts.capability_build.evidence import (
    MAX_OUTPUT_EXCERPT_BYTES,
    EvidenceRecord,
    VerificationCommand,
    VerificationPlan,
    build_default_verification_plan,
    evaluate_evidence,
)
from scripts.capability_build.intake import (
    ReturnedFile,
    WorkerSummary,
    validate_returned_files,
)
from scripts.capability_build.job import new_job
from scripts.capability_build.scope import FrozenScope


SPEC_SHA256 = "a" * 64
BASE_SHA = "a31da72"
JOB_ID = "slice-5-review-bundle"
RAW_CONTENT_MARKER = "RETURNED_FILE_BODY_MUST_NOT_APPEAR"
PRIVATE_OUTPUT_MARKER = "PRIVATE_EVIDENCE_OUTPUT_MUST_NOT_APPEAR"
WORKER_PROSE_MARKER = "WORKER_PROSE_MUST_NOT_APPEAR"


def _job(*, capability_id="projects.insight"):
    return new_job(
        capability_id,
        SPEC_SHA256,
        BASE_SHA,
        actor="human:tester",
        note="Approve the bounded build; " + WORKER_PROSE_MARKER,
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


def _plan(*, reverse=False):
    return build_default_verification_plan(
        _accepted_intake(reverse=reverse)
    )


def _evidence(plan, status="passed", *, reverse=False, full_excerpt=False):
    records = tuple(
        EvidenceRecord(
            command_name=command.name,
            status=status,
            summary=PRIVATE_OUTPUT_MARKER,
            exit_code=0 if status == "passed" else 1,
            output_excerpt=(
                PRIVATE_OUTPUT_MARKER
                + "x"
                * (MAX_OUTPUT_EXCERPT_BYTES - len(PRIVATE_OUTPUT_MARKER))
                if full_excerpt
                else PRIVATE_OUTPUT_MARKER
            ),
        )
        for command in plan.commands
    )
    if reverse:
        records = tuple(reversed(records))
    return evaluate_evidence(plan, records)


def _ready_bundle(*, reverse=False, full_excerpt=False):
    intake = _accepted_intake(reverse=reverse)
    plan = build_default_verification_plan(intake)
    evidence = _evidence(
        plan, reverse=reverse, full_excerpt=full_excerpt
    )
    return build_review_bundle(
        _job(),
        _scope(reverse=reverse),
        intake,
        plan,
        evidence,
    )


def test_passed_intake_and_evidence_are_ready_for_human_review_only():
    bundle = _ready_bundle()

    assert bundle.readiness_status == READINESS_READY
    assert bundle.review_only is True
    assert bundle.runtime_authority is False
    assert bundle.intake.accepted is True
    assert bundle.evidence.accepted is True
    assert bundle.evidence.status == "passed"
    assert bundle.to_dict()["authority"] == {
        "purpose": "human_review_only",
        "runtime_authority": False,
    }


def test_failed_intake_is_blocked_without_plan_or_evidence():
    bundle = build_review_bundle(_job(), _scope(), _failed_intake())

    assert bundle.readiness_status == READINESS_BLOCKED
    assert bundle.verification_plan is None
    assert bundle.evidence is None
    assert bundle.intake.blocking_findings


@pytest.mark.parametrize("include_plan", [False, True])
def test_missing_verification_or_evidence_is_incomplete(include_plan):
    intake = _accepted_intake()
    plan = build_default_verification_plan(intake) if include_plan else None

    bundle = build_review_bundle(_job(), _scope(), intake, plan)

    assert bundle.readiness_status == READINESS_INCOMPLETE


@pytest.mark.parametrize("status", ["failed", "blocked"])
def test_failed_or_blocked_evidence_blocks_bundle(status):
    intake = _accepted_intake()
    plan = build_default_verification_plan(intake)
    evidence = _evidence(plan, status=status)

    bundle = build_review_bundle(
        _job(), _scope(), intake, plan, evidence
    )

    assert bundle.readiness_status == READINESS_BLOCKED
    assert bundle.evidence.status == status
    assert bundle.evidence.accepted is False


def test_not_run_evidence_is_fail_closed():
    intake = _accepted_intake()
    plan = build_default_verification_plan(intake)
    evidence = _evidence(plan, status="not_run")

    bundle = build_review_bundle(
        _job(), _scope(), intake, plan, evidence
    )

    assert evidence.status == "incomplete"
    assert bundle.readiness_status == READINESS_BLOCKED


def test_missing_evidence_record_is_fail_closed():
    intake = _accepted_intake()
    plan = build_default_verification_plan(intake)
    evidence = evaluate_evidence(
        plan,
        tuple(
            EvidenceRecord(
                command_name=command.name,
                status="passed",
                summary="External verification passed.",
                exit_code=0,
            )
            for command in plan.commands[:-1]
        ),
    )

    bundle = build_review_bundle(
        _job(), _scope(), intake, plan, evidence
    )

    assert evidence.status == "incomplete"
    assert bundle.readiness_status == READINESS_BLOCKED


@pytest.mark.parametrize(
    "job,scope,intake,message",
    [
        (None, _scope(), _accepted_intake(), "job must"),
        (_job(), None, _accepted_intake(), "frozen_scope must"),
        (_job(), _scope(), None, "intake_result must"),
    ],
)
def test_missing_required_components_are_rejected(
    job, scope, intake, message
):
    with pytest.raises(BundleError, match=message):
        build_review_bundle(job, scope, intake)


def test_evidence_without_plan_and_mismatched_plan_are_rejected():
    intake = _accepted_intake()
    plan = build_default_verification_plan(intake)
    evidence = _evidence(plan)
    with pytest.raises(BundleError, match="requires a verification plan"):
        build_review_bundle(_job(), _scope(), intake, None, evidence)

    other_plan = VerificationPlan(
        commands=(
            VerificationCommand(
                name="human-check",
                argv=("manual-review", *plan.touched_files),
                kind="manual",
            ),
        ),
        touched_files=plan.touched_files,
    )
    with pytest.raises(BundleError, match="does not belong"):
        build_review_bundle(
            _job(), _scope(), intake, other_plan, evidence
        )


def test_bundle_ordering_and_summary_are_deterministic():
    forward = _ready_bundle()
    reverse = _ready_bundle(reverse=True)

    assert forward == reverse
    assert forward.to_dict() == reverse.to_dict()
    assert forward.summary() == reverse.summary()
    assert forward.intake.touched_files == (
        "backend/tools_widget.py",
        "tests/test_widget.py",
    )


def test_human_summary_excludes_raw_content_prose_and_output_excerpts():
    bundle = _ready_bundle(full_excerpt=True)
    summary = bundle.summary()
    payload = json.loads(summary)

    for excluded in (
        RAW_CONTENT_MARKER,
        PRIVATE_OUTPUT_MARKER,
        WORKER_PROSE_MARKER,
        "Adapter justification prose.",
        "Test justification prose.",
    ):
        assert excluded not in summary
    assert "argv" not in summary
    assert "output_excerpt" not in summary

    forbidden_keys = {
        "prompt",
        "raw_prompt",
        "secret",
        "secrets",
        "worker_report",
        "returned_content",
    }

    def keys(value):
        if isinstance(value, dict):
            for key, child in value.items():
                yield key
                yield from keys(child)
        elif isinstance(value, list):
            for child in value:
                yield from keys(child)

    assert not forbidden_keys & set(keys(payload))


def test_bundle_models_are_immutable():
    bundle = _ready_bundle()

    with pytest.raises(FrozenInstanceError):
        bundle.readiness_status = READINESS_BLOCKED
    with pytest.raises(FrozenInstanceError):
        bundle.job.state = "installed"


def test_bundle_text_and_total_summary_are_bounded():
    with pytest.raises(BundleError, match="capability_id exceeds"):
        build_review_bundle(
            _job(capability_id="x" * (MAX_BUNDLE_TEXT_BYTES + 1)),
            _scope(),
            _accepted_intake(),
        )

    bundle = _ready_bundle(full_excerpt=True)
    assert len(bundle.summary().encode("utf-8")) <= (
        MAX_BUNDLE_SUMMARY_BYTES
    )


def test_bundle_module_has_no_runtime_or_mutation_authority():
    source_path = (
        Path(__file__).parents[1]
        / "scripts"
        / "capability_build"
        / "bundle.py"
    )
    source = source_path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    forbidden_imports = {
        "backend",
        "git",
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
        "apply_patch",
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
