"""Tests for V0.4C Slice 10 offline PR publication result intake."""

import ast
from dataclasses import FrozenInstanceError, replace
from pathlib import Path

import pytest

from test_capability_build_pr_publication_action import _authorized
from test_capability_build_pr_publication_authorization import (
    _authorization,
    _decision,
)
from scripts.capability_build.pr_publication_action import (
    prepare_pr_publication_action,
)
from scripts.capability_build.pr_publication_authorization import (
    authorize_pr_publication,
)
from scripts.capability_build.pr_publication_result import (
    MAX_EXPLANATION_BYTES,
    MAX_PR_PUBLICATION_RESULT_INPUT_BYTES,
    MAX_PR_PUBLICATION_RESULT_SUMMARY_BYTES,
    OUTCOME_CREATED,
    OUTCOME_FAILED,
    OUTCOME_NOT_ATTEMPTED,
    STATUS_CREATION_FAILED,
    STATUS_NOT_ATTEMPTED,
    STATUS_PR_CREATED,
    STATUS_RESULT_REJECTED,
    PRPublicationResultError,
    expected_result_input,
    record_pr_publication_result,
)


def _action():
    return prepare_pr_publication_action(_authorized())


def _receipt(action=None, outcome=OUTCOME_CREATED, **changes):
    action = action or _action()
    metadata = {}
    if outcome == OUTCOME_CREATED:
        metadata.update(
            pr_number=71,
            pr_url="https://github.com/mootmoot1/MootOS/pull/71",
        )
    elif outcome == OUTCOME_FAILED:
        metadata.update(
            failure_classification="external_api_failure",
            explanation="External publisher reported a safe failure.",
        )
    else:
        metadata["explanation"] = "Publication was not attempted."
    metadata.update(changes)
    return expected_result_input(action, "result-10", outcome, **metadata)


@pytest.mark.parametrize(
    "outcome,status",
    [
        (OUTCOME_CREATED, STATUS_PR_CREATED),
        (OUTCOME_FAILED, STATUS_CREATION_FAILED),
        (OUTCOME_NOT_ATTEMPTED, STATUS_NOT_ATTEMPTED),
    ],
)
def test_valid_external_receipts_are_recorded(outcome, status):
    action = _action()
    result = record_pr_publication_result(action, _receipt(action, outcome))
    assert result.status == status
    assert result.result_recorded is True
    assert result.externally_reported is True
    assert result.external_attempt_reported is (
        outcome != OUTCOME_NOT_ATTEMPTED
    )
    assert result.external_success_reported is (outcome == OUTCOME_CREATED)
    assert result.externally_verified is False
    assert result.reporter_authenticated is False
    assert result.execution_performed_by_this_module is False
    assert result.github_action_performed is False
    assert result.git_action_performed is False


@pytest.mark.parametrize(
    "field,value",
    [
        ("idempotency_key", "b" * 64),
        ("authorization_id", "other-auth"),
        ("decision_id", "other-decision"),
        ("job_id", "other-job"),
        ("package_id", "other-package"),
        ("operation", "merge_pull_request"),
        ("repository", "other/repo"),
        ("base_sha", "b" * 40),
        ("target_branch", "develop"),
        ("source_branch", "other/head"),
    ],
)
def test_any_action_or_source_binding_mismatch_is_rejected(field, value):
    action = _action()
    supplied = replace(_receipt(action), **{field: value})
    result = record_pr_publication_result(action, supplied)
    assert result.status == STATUS_RESULT_REJECTED
    assert result.result_recorded is False
    assert result.externally_reported is False


def test_created_receipt_requires_exact_safe_canonical_url():
    action = _action()
    for url in (
        "http://github.com/mootmoot1/MootOS/pull/71",
        "https://evil.example/pull/71",
        "https://github.com/mootmoot1/MootOS/pull/72",
    ):
        result = record_pr_publication_result(
            action, _receipt(action, pr_url=url)
        )
        assert result.status == STATUS_RESULT_REJECTED


@pytest.mark.parametrize("number", [None, 0, -1, "71", True])
def test_created_receipt_requires_valid_pr_number(number):
    with pytest.raises(PRPublicationResultError):
        _receipt(pr_number=number)


@pytest.mark.parametrize("outcome", [OUTCOME_FAILED, OUTCOME_NOT_ATTEMPTED])
def test_non_created_receipt_cannot_claim_pr_identity(outcome):
    with pytest.raises(PRPublicationResultError):
        _receipt(outcome=outcome, pr_number=71)


def test_failed_receipt_requires_bounded_classification():
    with pytest.raises(PRPublicationResultError):
        _receipt(outcome=OUTCOME_FAILED, failure_classification=None)
    with pytest.raises(PRPublicationResultError):
        _receipt(outcome=OUTCOME_FAILED, failure_classification="x" * 257)


def test_multibyte_explanation_boundary_is_counted_in_utf8_bytes():
    valid = "é" * (MAX_EXPLANATION_BYTES // 2)
    receipt = _receipt(outcome=OUTCOME_FAILED, explanation=valid)
    assert receipt.explanation == valid
    with pytest.raises(PRPublicationResultError, match="exceeds"):
        _receipt(outcome=OUTCOME_FAILED, explanation=valid + "é")


@pytest.mark.parametrize(
    "changes",
    [
        {"pr_number": None},
        {"pr_url": None},
        {"failure_classification": "token=raw-value"},
        {"explanation": "password: raw-value"},
        {"explanation": "raw output\nsecond line"},
    ],
)
def test_malformed_or_unsafe_metadata_is_rejected(changes):
    outcome = OUTCOME_CREATED
    if "failure_classification" in changes or "explanation" in changes:
        outcome = OUTCOME_FAILED
    with pytest.raises(PRPublicationResultError):
        _receipt(outcome=outcome, **changes)


def test_unknown_outcome_and_invalid_action_types_are_rejected():
    with pytest.raises(PRPublicationResultError):
        expected_result_input(_action(), "result-10", "unknown")
    with pytest.raises(PRPublicationResultError):
        record_pr_publication_result(None, _receipt())


def test_action_must_be_authoritative_and_prepared():
    decision = _decision()
    mismatched = replace(_authorization(decision), repository="other/repo")
    authorization = authorize_pr_publication(decision, mismatched)
    not_prepared = prepare_pr_publication_action(authorization)
    result = record_pr_publication_result(not_prepared, _receipt())
    assert result.status == STATUS_RESULT_REJECTED
    assert result.result_recorded is False


def test_result_is_deterministic_immutable_bounded_and_sanitized():
    action = _action()
    supplied = _receipt(action)
    first = record_pr_publication_result(action, supplied)
    second = record_pr_publication_result(action, supplied)
    assert first == second
    assert supplied.summary() == _receipt(action).summary()
    assert len(supplied.summary().encode("utf-8")) <= (
        MAX_PR_PUBLICATION_RESULT_INPUT_BYTES
    )
    assert first.summary() == second.summary()
    assert len(first.summary().encode("utf-8")) <= (
        MAX_PR_PUBLICATION_RESULT_SUMMARY_BYTES
    )
    assert "token=" not in first.summary().casefold()
    with pytest.raises(FrozenInstanceError):
        first.status = STATUS_RESULT_REJECTED
    with pytest.raises(PRPublicationResultError, match="forged"):
        replace(first, status=STATUS_RESULT_REJECTED)


def test_module_has_no_executor_or_external_authority():
    path = (
        Path(__file__).parents[1]
        / "scripts/capability_build/pr_publication_result.py"
    )
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    forbidden_imports = {
        "backend", "git", "github", "httpx", "os", "pathlib",
        "requests", "shutil", "socket", "subprocess", "urllib",
    }
    forbidden_calls = {
        "create_branch", "create_commit", "create_pull_request", "open",
        "push", "merge", "run", "Popen", "deploy", "execute", "retry",
    }
    imports, calls = [], []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imports.append(node.module or "")
        elif isinstance(node, ast.Call):
            calls.append(
                getattr(node.func, "id", getattr(node.func, "attr", ""))
            )
    assert not any(
        name.split(".")[0] in forbidden_imports for name in imports
    )
    assert not forbidden_calls & set(calls)
