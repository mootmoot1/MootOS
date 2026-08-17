"""Focused tests for V0.4C Slice 1 pure PR package proposals."""

import ast
import json
from dataclasses import FrozenInstanceError, replace
from pathlib import Path

import pytest

from scripts.capability_build.pr_package import (
    BLOCKED,
    EVIDENCE_FAILED,
    EVIDENCE_PASSED,
    MAX_BODY_BYTES,
    MAX_ITEM_TEXT_BYTES,
    MAX_PR_PACKAGE_SUMMARY_BYTES,
    MAX_TITLE_BYTES,
    READY,
    PREvidenceSummary,
    PRChecklistItem,
    PRFileSummary,
    PRPackageError,
    PRPackageProposal,
    PRRiskSummary,
    PRRollbackNote,
)


BASE_SHA = "e" * 40


def _files(*, reverse=False):
    values = (
        PRFileSummary(
            path="scripts/capability_build/example.py",
            operation="create",
            summary="Add the bounded offline model.",
        ),
        PRFileSummary(
            path="tests/test_example.py",
            operation="modify",
            summary="Cover the model invariants.",
        ),
    )
    return tuple(reversed(values)) if reverse else values


def _evidence(*, reverse=False, failed=False):
    values = (
        PREvidenceSummary(
            check_name="flake8",
            status=EVIDENCE_PASSED,
        ),
        PREvidenceSummary(
            check_name="pytest",
            status=EVIDENCE_FAILED if failed else EVIDENCE_PASSED,
        ),
    )
    return tuple(reversed(values)) if reverse else values


def _risks(*, reverse=False):
    values = (
        PRRiskSummary(
            risk_id="scope",
            level="low",
            summary="The proposal is limited to offline metadata.",
            mitigation="Require later human review before any action.",
        ),
        PRRiskSummary(
            risk_id="validation",
            level="medium",
            summary="Malformed metadata could mislead a reviewer.",
            mitigation="Reject malformed or inconsistent packages.",
        ),
    )
    return tuple(reversed(values)) if reverse else values


def _rollback_notes(*, reverse=False):
    values = (
        PRRollbackNote(
            order=1,
            instruction="Discard the offline proposal metadata.",
        ),
        PRRollbackNote(
            order=2,
            instruction="Retain the prior reviewed build artifacts.",
        ),
    )
    return tuple(reversed(values)) if reverse else values


def _checklist(*, reverse=False):
    values = (
        PRChecklistItem(
            item_id="diff",
            description="Review the complete proposed diff.",
        ),
        PRChecklistItem(
            item_id="evidence",
            description="Confirm the summarized evidence is sufficient.",
        ),
    )
    return tuple(reversed(values)) if reverse else values


def _proposal(**overrides):
    values = {
        "package_id": "pr-package-001",
        "job_id": "job-v04c-slice-1",
        "capability_id": "projects.insight",
        "base_sha": BASE_SHA,
        "target_branch": "main",
        "proposed_branch_name": "codex/v0.4c-slice-1-proposal",
        "proposed_commit_title": "feat: add offline PR package model",
        "proposed_pr_title": "Add pure PR package proposal model",
        "proposed_pr_body": (
            "## Summary\n\n"
            "Prepare bounded metadata for later human review."
        ),
        "changed_files": _files(),
        "evidence": _evidence(),
        "risks": _risks(),
        "rollback_notes": _rollback_notes(),
        "human_checklist": _checklist(),
        "readiness_status": READY,
        "blocking_reasons": (),
    }
    values.update(overrides)
    return PRPackageProposal(**values)


def test_valid_ready_pr_package_proposal_is_offline_only():
    proposal = _proposal()

    assert proposal.schema_version == 1
    assert proposal.readiness_status == READY
    assert proposal.blocking_reasons == ()
    assert proposal.offline_only is True
    assert proposal.proposal_only is True
    assert proposal.github_action_performed is False
    assert proposal.git_action_performed is False
    assert proposal.human_approval_recorded is False
    assert proposal.runtime_authority is False


def test_valid_blocked_pr_package_proposal_has_stable_reasons():
    proposal = _proposal(
        evidence=_evidence(failed=True),
        readiness_status=BLOCKED,
        blocking_reasons=(
            "Verification did not pass.",
            "Human review is required.",
        ),
    )

    assert proposal.readiness_status == BLOCKED
    assert proposal.blocking_reasons == (
        "Human review is required.",
        "Verification did not pass.",
    )


def test_ready_proposal_rejects_blocking_reasons():
    with pytest.raises(PRPackageError, match="ready proposals"):
        _proposal(blocking_reasons=("Unexpected blocker.",))


def test_blocked_proposal_requires_blocking_reasons():
    with pytest.raises(PRPackageError, match="require blocking reasons"):
        _proposal(readiness_status=BLOCKED)


@pytest.mark.parametrize(
    "field_name,value",
    [
        ("package_id", ""),
        ("package_id", "package/id"),
        ("job_id", " "),
        ("job_id", "job id"),
        ("capability_id", ""),
        ("capability_id", "Projects.Insight"),
        ("base_sha", ""),
        ("base_sha", "abc123"),
        ("base_sha", "g" * 40),
    ],
)
def test_malformed_or_blank_identifiers_are_rejected(field_name, value):
    with pytest.raises(PRPackageError):
        _proposal(**{field_name: value})


@pytest.mark.parametrize(
    "branch",
    [
        "/main",
        "feature/",
        "feature//topic",
        "feature..topic",
        "feature/.hidden",
        "feature/topic.lock",
        "feature topic",
        "feature\\topic",
        "feature@{topic",
        "-feature",
    ],
)
def test_unsafe_branch_names_are_rejected(branch):
    with pytest.raises(PRPackageError, match="unsafe"):
        _proposal(proposed_branch_name=branch)


def test_proposed_branch_must_differ_from_target_branch():
    with pytest.raises(PRPackageError, match="differ"):
        _proposal(proposed_branch_name="main")


@pytest.mark.parametrize(
    "field_name",
    ["proposed_commit_title", "proposed_pr_title"],
)
def test_blank_and_oversized_titles_are_rejected(field_name):
    with pytest.raises(PRPackageError, match="nonblank"):
        _proposal(**{field_name: " "})
    with pytest.raises(PRPackageError, match="exceeds"):
        _proposal(**{field_name: "x" * (MAX_TITLE_BYTES + 1)})


def test_blank_and_oversized_pr_body_are_rejected():
    with pytest.raises(PRPackageError, match="nonblank"):
        _proposal(proposed_pr_body="\n")
    with pytest.raises(PRPackageError, match="exceeds"):
        _proposal(proposed_pr_body="x" * (MAX_BODY_BYTES + 1))


def test_file_summaries_are_structured_deterministic_and_bounded():
    forward = _proposal(changed_files=_files())
    reverse_order = _proposal(changed_files=_files(reverse=True))

    assert forward.changed_files == reverse_order.changed_files
    assert tuple(item.path for item in forward.changed_files) == (
        "scripts/capability_build/example.py",
        "tests/test_example.py",
    )
    with pytest.raises(PRPackageError, match="PRFileSummary"):
        _proposal(changed_files=({"path": "tests/test_x.py"},))
    with pytest.raises(PRPackageError, match="duplicates"):
        _proposal(
            changed_files=(
                PRFileSummary("tests/test_x.py", "create", "Add it."),
                PRFileSummary("tests/test_x.py", "modify", "Change it."),
            )
        )
    with pytest.raises(PRPackageError, match="exceeds"):
        PRFileSummary(
            "tests/test_x.py",
            "create",
            "x" * (MAX_ITEM_TEXT_BYTES + 1),
        )


@pytest.mark.parametrize(
    "factory",
    [
        lambda: PREvidenceSummary("bad/name", EVIDENCE_PASSED),
        lambda: PRRiskSummary(
            "risk",
            "unknown",
            "Summary.",
            "Mitigation.",
        ),
        lambda: PRRollbackNote(0, "Rollback."),
        lambda: PRChecklistItem("check", "Checklist.", required="yes"),
    ],
)
def test_structured_support_models_reject_malformed_values(factory):
    with pytest.raises(PRPackageError):
        factory()


def test_evidence_risk_rollback_and_checklist_are_deterministic():
    forward = _proposal()
    reverse_order = _proposal(
        evidence=_evidence(reverse=True),
        risks=_risks(reverse=True),
        rollback_notes=_rollback_notes(reverse=True),
        human_checklist=_checklist(reverse=True),
    )

    assert forward.evidence == reverse_order.evidence
    assert forward.risks == reverse_order.risks
    assert forward.rollback_notes == reverse_order.rollback_notes
    assert forward.human_checklist == reverse_order.human_checklist


@pytest.mark.parametrize(
    "field_name,bad_value,expected_type",
    [
        ("evidence", ({"status": "passed"},), "PREvidenceSummary"),
        ("risks", ({"level": "low"},), "PRRiskSummary"),
        ("rollback_notes", ("Discard it.",), "PRRollbackNote"),
        ("human_checklist", ("Review it.",), "PRChecklistItem"),
    ],
)
def test_structured_package_fields_reject_untyped_items(
    field_name,
    bad_value,
    expected_type,
):
    with pytest.raises(PRPackageError, match=expected_type):
        _proposal(**{field_name: bad_value})


def test_secret_like_text_is_rejected_without_storing_it():
    key_like = "sk" + "-" + ("x" * 32)

    with pytest.raises(PRPackageError, match="secret-like"):
        _proposal(proposed_pr_body="Unexpected value: " + key_like)


def test_proposal_and_nested_models_are_immutable():
    proposal = _proposal()

    with pytest.raises(FrozenInstanceError):
        proposal.readiness_status = BLOCKED
    with pytest.raises(FrozenInstanceError):
        proposal.changed_files[0].path = "tests/other.py"
    with pytest.raises(FrozenInstanceError):
        proposal.human_checklist[0].required = False


def test_to_dict_and_summary_are_deterministic():
    first = _proposal()
    second = _proposal(
        changed_files=_files(reverse=True),
        evidence=_evidence(reverse=True),
        risks=_risks(reverse=True),
        rollback_notes=_rollback_notes(reverse=True),
        human_checklist=_checklist(reverse=True),
    )

    assert first == second
    assert first.to_dict() == second.to_dict()
    assert first.summary() == second.summary()
    assert json.loads(first.summary()) == first.to_dict()


def test_summary_is_bounded_and_has_no_raw_or_operational_fields():
    proposal = _proposal()
    summary = proposal.summary()
    payload = json.loads(summary)

    assert len(summary.encode("utf-8")) <= MAX_PR_PACKAGE_SUMMARY_BYTES
    assert payload["authority"] == {
        "git_action_performed": False,
        "github_action_performed": False,
        "human_approval_recorded": False,
        "offline_only": True,
        "proposal_only": True,
        "runtime_authority": False,
    }
    forbidden_keys = {
        "user_goal",
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
        "human_approval",
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


def test_invalid_readiness_and_forged_readiness_are_rejected():
    proposal = _proposal()

    with pytest.raises(PRPackageError, match="unsupported readiness"):
        _proposal(readiness_status="approved")
    with pytest.raises(PRPackageError, match="ready proposals"):
        replace(proposal, blocking_reasons=("Forged blocker.",))


def test_module_has_no_operational_or_external_authority():
    source_path = (
        Path(__file__).parents[1]
        / "scripts"
        / "capability_build"
        / "pr_package.py"
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
        "read",
        "read_text",
        "read_bytes",
        "write",
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
        "create_branch",
        "create_commit",
        "create_pr",
        "open_pr",
        "register",
        "install",
        "deploy",
        "approve",
        "merge",
        "push",
    }
    forbidden_definitions = {
        "create_branch",
        "create_commit",
        "create_pr",
        "open_pr",
        "register",
        "install",
        "deploy",
        "approve",
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
