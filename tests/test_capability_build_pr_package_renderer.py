"""Focused tests for V0.4C Slice 3 PR package rendering."""

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
    MAX_STRUCTURED_ITEMS,
    READY,
    PREvidenceSummary,
    PRChecklistItem,
    PRFileSummary,
    PRPackageProposal,
    PRRiskSummary,
    PRRollbackNote,
)
from scripts.capability_build import pr_package_renderer
from scripts.capability_build.pr_package_renderer import (
    MAX_RENDERED_PR_BODY_BYTES,
    MAX_REVIEW_SUMMARY_BYTES,
    PRPackageRenderError,
    render_pr_body,
    render_pr_package,
    render_review_summary,
)


BASE_SHA = "a" * 40
RAW_WORKER_TEXT = "RAW_RENDERER_WORKER_TEXT_MUST_NOT_APPEAR"
RAW_OUTPUT_TEXT = "RAW_RENDERER_OUTPUT_TEXT_MUST_NOT_APPEAR"


def _files(*, reverse=False):
    values = (
        PRFileSummary(
            path="scripts/capability_build/pr_package_renderer.py",
            operation="create",
            summary="Add inert Markdown rendering for PR packages.",
        ),
        PRFileSummary(
            path="tests/test_capability_build_pr_package_renderer.py",
            operation="create",
            summary="Cover renderer invariants and safety boundaries.",
        ),
    )
    return tuple(reversed(values)) if reverse else values


def _evidence(*, reverse=False, failed=False):
    values = (
        PREvidenceSummary(
            check_name="python-syntax",
            status=EVIDENCE_PASSED,
        ),
        PREvidenceSummary(
            check_name="targeted-tests",
            status=EVIDENCE_FAILED if failed else EVIDENCE_PASSED,
        ),
    )
    return tuple(reversed(values)) if reverse else values


def _risks(*, reverse=False):
    values = (
        PRRiskSummary(
            risk_id="authority",
            level="low",
            summary="Rendering is text-only metadata.",
            mitigation="Require a later human decision before action.",
        ),
        PRRiskSummary(
            risk_id="formatting",
            level="low",
            summary="Markdown could omit relevant review context.",
            mitigation="Render files, evidence, risks, rollback, and safety.",
        ),
    )
    return tuple(reversed(values)) if reverse else values


def _rollback_notes(*, reverse=False):
    values = (
        PRRollbackNote(1, "Discard the rendered Markdown."),
        PRRollbackNote(2, "Return to the offline PR package proposal."),
    )
    return tuple(reversed(values)) if reverse else values


def _checklist(*, reverse=False):
    values = (
        PRChecklistItem("diff", "Review the proposed diff."),
        PRChecklistItem("evidence", "Confirm evidence is sufficient."),
    )
    return tuple(reversed(values)) if reverse else values


def _proposal(**overrides):
    values = {
        "package_id": "job-v04c-slice-3-pr-package",
        "job_id": "job-v04c-slice-3",
        "capability_id": "projects.insight",
        "base_sha": BASE_SHA,
        "target_branch": "main",
        "proposed_branch_name": "codex/v0.4c-slice-3-pr-body-renderer",
        "proposed_commit_title": "feat(V0.4C): render PR package body",
        "proposed_pr_title": "feat(V0.4C): render PR package body",
        "proposed_pr_body": (
            "Prepare a Markdown body and compact review summary from "
            "offline PR package metadata."
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


def test_ready_pr_package_renders_body_and_review_summary():
    proposal = _proposal()

    body = render_pr_body(proposal)
    review_summary = render_review_summary(proposal)
    rendering = render_pr_package(proposal)

    assert "## Summary" in body
    assert "## Changed Files" in body
    assert "## Evidence" in body
    assert "## Risks" in body
    assert "## Rollback" in body
    assert "## Human Review Checklist" in body
    assert "## Safety" in body
    assert "`scripts/capability_build/pr_package_renderer.py`" in body
    assert "`python-syntax`: passed" in body
    assert "Blocking Reasons\n\nNone" in body
    assert "no Git or GitHub action" in review_summary
    assert rendering.pr_body == body
    assert rendering.review_summary == review_summary
    assert rendering.offline_only is True
    assert rendering.proposal_only is True
    assert rendering.github_action_performed is False
    assert rendering.git_action_performed is False
    assert rendering.human_approval_recorded is False
    assert rendering.runtime_authority is False


def test_blocked_pr_package_renders_blocking_reasons():
    proposal = _proposal(
        evidence=_evidence(failed=True),
        readiness_status=BLOCKED,
        blocking_reasons=(
            "targeted-tests failed.",
            "Human review is required.",
        ),
    )

    body = render_pr_body(proposal)
    review_summary = render_review_summary(proposal)

    assert "Readiness: `blocked`" in body
    assert "- Human review is required." in body
    assert "- targeted-tests failed." in body
    assert "Blocking reasons: 2" in review_summary
    assert "failed=1" in review_summary
    assert "passed=1" in review_summary


def test_rendering_is_deterministic_for_stable_proposals():
    first = _proposal()
    second = _proposal(
        changed_files=_files(reverse=True),
        evidence=_evidence(reverse=True),
        risks=_risks(reverse=True),
        rollback_notes=_rollback_notes(reverse=True),
        human_checklist=_checklist(reverse=True),
    )

    assert first == second
    assert render_pr_body(first) == render_pr_body(second)
    assert render_review_summary(first) == render_review_summary(second)
    assert (
        render_pr_package(first).summary()
        == render_pr_package(second).summary()
    )


def test_maximum_size_valid_proposed_body_renders_without_truncation():
    proposed_body = "x" * MAX_BODY_BYTES
    proposal = _proposal(proposed_pr_body=proposed_body)

    rendered = render_pr_body(proposal)

    assert proposed_body in rendered
    assert len(rendered.encode("utf-8")) <= MAX_RENDERED_PR_BODY_BYTES


@pytest.mark.parametrize(
    ("byte_count", "should_render"),
    [
        (MAX_RENDERED_PR_BODY_BYTES - 1, True),
        (MAX_RENDERED_PR_BODY_BYTES, True),
        (MAX_RENDERED_PR_BODY_BYTES + 1, False),
    ],
)
def test_rendered_output_byte_limit(byte_count, should_render):
    value = "x" * byte_count

    if should_render:
        assert (
            pr_package_renderer._bounded_text(
                value,
                "rendered PR body",
                MAX_RENDERED_PR_BODY_BYTES,
            )
            == value
        )
    else:
        with pytest.raises(PRPackageRenderError, match="exceeds"):
            pr_package_renderer._bounded_text(
                value,
                "rendered PR body",
                MAX_RENDERED_PR_BODY_BYTES,
            )


def test_rendered_output_limit_counts_multibyte_unicode_bytes():
    exact = "é" * (MAX_RENDERED_PR_BODY_BYTES // 2)
    above = exact + "é"

    assert len(exact.encode("utf-8")) == MAX_RENDERED_PR_BODY_BYTES
    assert (
        pr_package_renderer._bounded_text(
            exact,
            "rendered PR body",
            MAX_RENDERED_PR_BODY_BYTES,
        )
        == exact
    )
    with pytest.raises(PRPackageRenderError, match="exceeds"):
        pr_package_renderer._bounded_text(
            above,
            "rendered PR body",
            MAX_RENDERED_PR_BODY_BYTES,
        )


def test_maximum_valid_structured_collections_render_with_maximum_body():
    proposal = _proposal(
        proposed_pr_body="x" * MAX_BODY_BYTES,
        changed_files=tuple(
            PRFileSummary(
                path=f"changed/file-{index:03d}.py",
                operation="modify",
                summary=f"Changed file {index}.",
            )
            for index in range(MAX_STRUCTURED_ITEMS)
        ),
        evidence=tuple(
            PREvidenceSummary(
                check_name=f"check-{index:03d}",
                status=EVIDENCE_PASSED,
            )
            for index in range(MAX_STRUCTURED_ITEMS)
        ),
        risks=tuple(
            PRRiskSummary(
                risk_id=f"risk-{index:03d}",
                level="low",
                summary=f"Risk {index}.",
                mitigation=f"Mitigation {index}.",
            )
            for index in range(MAX_STRUCTURED_ITEMS)
        ),
        rollback_notes=tuple(
            PRRollbackNote(index + 1, f"Rollback step {index + 1}.")
            for index in range(MAX_STRUCTURED_ITEMS)
        ),
        human_checklist=tuple(
            PRChecklistItem(
                f"item-{index:03d}",
                f"Review item {index}.",
            )
            for index in range(MAX_STRUCTURED_ITEMS)
        ),
    )

    rendering = render_pr_package(proposal)

    assert len(rendering.pr_body.encode("utf-8")) <= (
        MAX_RENDERED_PR_BODY_BYTES
    )
    assert "`changed/file-127.py`" in rendering.pr_body
    assert "`check-127`: passed" in rendering.pr_body
    assert "`risk-127` (low)" in rendering.pr_body
    assert "128. Rollback step 128." in rendering.pr_body
    assert "- [ ] Review item 127." in rendering.pr_body


@pytest.mark.parametrize("invalid", [None, {}, "package", object()])
def test_invalid_renderer_input_is_rejected(invalid):
    with pytest.raises(PRPackageRenderError, match="PRPackageProposal"):
        render_pr_body(invalid)
    with pytest.raises(PRPackageRenderError, match="PRPackageProposal"):
        render_review_summary(invalid)
    with pytest.raises(PRPackageRenderError, match="PRPackageProposal"):
        render_pr_package(invalid)


def test_rendering_result_is_immutable_and_unforgeable():
    rendering = render_pr_package(_proposal())
    blocked = render_pr_package(
        _proposal(
            evidence=_evidence(failed=True),
            readiness_status=BLOCKED,
            blocking_reasons=("targeted-tests failed.",),
        )
    )

    with pytest.raises(FrozenInstanceError):
        rendering.pr_body = blocked.pr_body
    with pytest.raises(PRPackageRenderError, match="does not match"):
        replace(rendering, pr_body=blocked.pr_body)
    with pytest.raises(PRPackageRenderError, match="does not match"):
        replace(rendering, review_summary=blocked.review_summary)


def test_summary_is_bounded_and_excludes_raw_or_operational_fields():
    rendering = render_pr_package(_proposal())
    summary = rendering.summary()
    payload = json.loads(summary)

    assert len(rendering.pr_body.encode("utf-8")) <= (
        MAX_RENDERED_PR_BODY_BYTES
    )
    assert len(rendering.review_summary.encode("utf-8")) <= (
        MAX_REVIEW_SUMMARY_BYTES
    )
    assert payload["authority"] == {
        "git_action_performed": False,
        "github_action_performed": False,
        "human_approval_recorded": False,
        "offline_only": True,
        "proposal_only": True,
        "runtime_authority": False,
    }
    assert RAW_WORKER_TEXT not in summary
    assert RAW_OUTPUT_TEXT not in summary

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


def test_renderer_module_has_no_external_or_mutation_authority():
    source_path = (
        Path(__file__).parents[1]
        / "scripts"
        / "capability_build"
        / "pr_package_renderer.py"
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
