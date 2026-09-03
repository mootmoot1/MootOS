"""Tests for V0.4C Slice 7 authoritative decision binding."""

import ast
from dataclasses import FrozenInstanceError, replace
from pathlib import Path

import pytest

from test_capability_build_workflow_pr_review import _source
from scripts.capability_build.pr_review_decision import PRReviewDecisionInput
from scripts.capability_build.workflow_pr_decision import (
    STATUS_DECISION_RECORDED,
    STATUS_NOT_RECORDED,
    WorkflowPRDecisionError,
    record_pr_review_decision,
)
from scripts.capability_build.workflow_pr_review import (
    enter_human_review_pending,
)


def _input(review, decision="approve_for_pr", **changes):
    package = review.source_rendering.pr_package_creation.pr_package
    values = dict(
        decision_id="decision-7", reviewer_id="human:moot",
        decision=decision, rationale="Reviewed exact evidence.",
        job_id=package.job_id if package else "missing-job",
        package_id=package.package_id if package else "missing-package",
        proposal_base_sha=package.base_sha if package else "a" * 40,
    )
    values.update(changes)
    return PRReviewDecisionInput(**values)


@pytest.mark.parametrize(
    "decision,eligible",
    [("approve_for_pr", True), ("request_changes", False), ("reject", False)],
)
def test_ready_review_records_each_allowed_decision(decision, eligible):
    review = enter_human_review_pending(_source())
    result = record_pr_review_decision(review, _input(review, decision))
    assert result.status == STATUS_DECISION_RECORDED
    assert result.decision == decision
    assert result.decision_recorded is True
    assert result.eligible_for_pr_authorization is eligible
    assert result.publication_authorized is False
    assert result.workflow is review.workflow


@pytest.mark.parametrize(
    "decision,recorded",
    [("approve_for_pr", False), ("request_changes", True), ("reject", True)],
)
def test_blocked_review_enforces_available_options(decision, recorded):
    review = enter_human_review_pending(_source("failed"))
    result = record_pr_review_decision(review, _input(review, decision))
    assert result.decision_recorded is recorded
    assert result.status == (
        STATUS_DECISION_RECORDED if recorded else STATUS_NOT_RECORDED
    )
    assert result.eligible_for_pr_authorization is False


@pytest.mark.parametrize(
    "decision", ["approve_for_pr", "request_changes", "reject"]
)
def test_not_pending_rejects_every_decision(decision):
    review = enter_human_review_pending(_source(no_evidence=True))
    result = record_pr_review_decision(review, _input(review, decision))
    assert result.status == STATUS_NOT_RECORDED
    assert result.decision is None


def test_identity_mismatch_fails_closed():
    review = enter_human_review_pending(_source())
    supplied = _input(review, job_id="wrong-job")
    result = record_pr_review_decision(review, supplied)
    assert result.status == STATUS_NOT_RECORDED
    assert "identity" in result.blocking_reasons[0]


@pytest.mark.parametrize("bad", [None, {}, "bad", object()])
def test_invalid_types_rejected(bad):
    review = enter_human_review_pending(_source())
    with pytest.raises(WorkflowPRDecisionError):
        record_pr_review_decision(bad, _input(review))
    with pytest.raises(WorkflowPRDecisionError):
        record_pr_review_decision(review, bad)


def test_forged_result_fields_are_rejected_and_result_is_immutable():
    review = enter_human_review_pending(_source())
    result = record_pr_review_decision(review, _input(review))
    with pytest.raises(WorkflowPRDecisionError):
        replace(result, decision="reject")
    with pytest.raises(WorkflowPRDecisionError):
        replace(result, blocking_reasons=("forged",))
    with pytest.raises(FrozenInstanceError):
        result.status = STATUS_NOT_RECORDED


def test_deterministic_bounded_sanitized_no_operational_authority():
    review = enter_human_review_pending(_source())
    first = record_pr_review_decision(review, _input(review))
    second = record_pr_review_decision(review, _input(review))
    assert first.summary() == second.summary()
    assert len(first.summary().encode("utf-8")) <= 128 * 1024
    assert first.to_dict()["authority"] == {
        "action_prepared": False, "autonomous": False,
        "github_action_performed": False, "git_action_performed": False,
        "publication_authorized": False, "runtime_authority": False,
    }


def test_adapter_has_no_external_or_execution_authority():
    path = (
        Path(__file__).parents[1] / "scripts" / "capability_build"
        / "workflow_pr_decision.py"
    )
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    forbidden_imports = {
        "backend", "git", "github", "httpx", "os", "pathlib",
        "pygit2", "requests", "shutil", "subprocess",
    }
    forbidden_calls = {
        "approve", "create_branch", "create_commit", "create_pull_request",
        "deploy", "dispatch_worker", "execute", "install", "merge", "open",
        "push", "register", "run", "system", "write_text",
    }
    imports = []
    calls = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imports.append(node.module or "")
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                calls.append(node.func.id)
            elif isinstance(node.func, ast.Attribute):
                calls.append(node.func.attr)
    assert not any(name.split(".")[0] in forbidden_imports for name in imports)
    assert not forbidden_calls & set(calls)
    assert "backend.tool_registry" not in source
