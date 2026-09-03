"""Tests for V0.4C Slice 8 explicit PR publication authorization."""

import ast
from dataclasses import FrozenInstanceError, replace
from pathlib import Path

import pytest

from test_capability_build_workflow_pr_decision import _input
from test_capability_build_workflow_pr_review import _source
from scripts.capability_build.pr_publication_authorization import (
    MAX_AUTHORIZATION_SUMMARY_BYTES,
    STATUS_AUTHORIZED,
    STATUS_NOT_AUTHORIZED,
    PRPublicationAuthorizationError,
    authorize_pr_publication,
    expected_authorization_input,
)
from scripts.capability_build.workflow_pr_decision import (
    record_pr_review_decision,
)
from scripts.capability_build.workflow_pr_review import (
    enter_human_review_pending,
)


def _decision(choice="approve_for_pr", *, blocked=False, mismatch=False):
    review = enter_human_review_pending(
        _source("failed" if blocked else "passed")
    )
    supplied = (
        _input(review, choice, job_id="wrong")
        if mismatch
        else _input(review, choice)
    )
    return record_pr_review_decision(review, supplied)


def _authorization(decision=None):
    decision = decision or _decision()
    return expected_authorization_input(
        decision, "authorization-8", "human:moot"
    )


def test_explicit_authorization_of_exact_approved_chain():
    decision = _decision()
    supplied = _authorization(decision)
    result = authorize_pr_publication(decision, supplied)
    assert result.status == STATUS_AUTHORIZED
    assert result.authorized is True
    assert result.authorizer_identity_bound is True
    assert result.authorizer_authenticated is False
    assert result.single_purpose is True
    assert result.action_prepared is False
    assert result.execution_performed is False


@pytest.mark.parametrize("choice", ["request_changes", "reject"])
def test_non_approve_decisions_cannot_authorize(choice):
    decision = _decision(choice)
    supplied = _authorization(_decision())
    result = authorize_pr_publication(decision, supplied)
    assert result.status == STATUS_NOT_AUTHORIZED
    assert result.authorized is False


def test_approve_decision_alone_is_insufficient():
    decision = _decision()
    with pytest.raises(PRPublicationAuthorizationError):
        authorize_pr_publication(decision, None)


def test_not_recorded_decision_cannot_authorize():
    decision = _decision(blocked=True)
    result = authorize_pr_publication(decision, _authorization(_decision()))
    assert result.status == STATUS_NOT_AUTHORIZED


@pytest.mark.parametrize(
    "field,value",
    [
        ("decision_id", "wrong-decision"), ("job_id", "wrong-job"),
        ("package_id", "wrong-package"), ("repository", "other/repo"),
        ("target_branch", "develop"), ("base_sha", "b" * 40),
        ("source_branch", "other/head"), ("title_sha256", "b" * 64),
        ("body_sha256", "c" * 64),
    ],
)
def test_any_scope_or_chain_mismatch_fails_closed(field, value):
    decision = _decision()
    supplied = replace(_authorization(decision), **{field: value})
    result = authorize_pr_publication(decision, supplied)
    assert result.status == STATUS_NOT_AUTHORIZED
    assert result.authorized is False
    assert field in result.blocking_reasons[0]


@pytest.mark.parametrize("field", ["authorization_id", "authorizer_id"])
def test_missing_or_invalid_authorization_identity_rejected(field):
    decision = _decision()
    with pytest.raises(PRPublicationAuthorizationError):
        replace(_authorization(decision), **{field: ""})


def test_altered_authorized_result_is_rejected_and_immutable():
    decision = _decision()
    result = authorize_pr_publication(decision, _authorization(decision))
    with pytest.raises(PRPublicationAuthorizationError):
        replace(result, status=STATUS_NOT_AUTHORIZED)
    with pytest.raises(FrozenInstanceError):
        result.status = STATUS_NOT_AUTHORIZED


def test_deterministic_bounded_sanitized_and_no_execution_authority():
    decision = _decision()
    first = authorize_pr_publication(decision, _authorization(decision))
    second = authorize_pr_publication(decision, _authorization(decision))
    assert first.summary() == second.summary()
    assert len(first.summary().encode("utf-8")) <= (
        MAX_AUTHORIZATION_SUMMARY_BYTES
    )
    payload = first.to_dict()
    assert payload["authority"]["execution_performed"] is False
    assert payload["authority"]["github_action_performed"] is False
    assert "token" not in first.summary().casefold()


def test_module_has_no_external_or_action_preparation_authority():
    path = (
        Path(__file__).parents[1]
        / "scripts/capability_build/pr_publication_authorization.py"
    )
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    forbidden_imports = {
        "backend", "git", "github", "os", "pathlib", "requests",
        "subprocess",
    }
    forbidden_calls = {
        "create_branch", "create_commit", "create_pull_request", "open",
        "push", "merge", "run", "Popen", "deploy", "execute",
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
