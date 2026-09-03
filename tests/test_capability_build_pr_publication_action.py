"""Tests for V0.4C Slice 9 inert PR publication action envelopes."""

import ast
from dataclasses import FrozenInstanceError, replace
from pathlib import Path

import pytest

from test_capability_build_pr_publication_authorization import (
    _authorization,
    _decision,
)
from scripts.capability_build.pr_publication_action import (
    MAX_PR_PUBLICATION_ACTION_SUMMARY_BYTES,
    STATUS_ACTION_PREPARED,
    STATUS_NOT_PREPARED,
    PRPublicationActionError,
    prepare_pr_publication_action,
)
from scripts.capability_build.pr_publication_authorization import (
    STATUS_NOT_AUTHORIZED,
    authorize_pr_publication,
)


def _authorized():
    decision = _decision()
    return authorize_pr_publication(decision, _authorization(decision))


def test_valid_authorized_action_is_prepared_without_execution():
    action = prepare_pr_publication_action(_authorized())
    assert action.status == STATUS_ACTION_PREPARED
    assert action.authorized is True
    assert action.action_prepared is True
    assert dict(action.scope)["operation"] == "create_pull_request"
    assert action.executed is False
    assert action.execution_performed is False
    assert action.github_action_performed is False
    assert action.git_action_performed is False
    assert action.authorizer_identity_bound is True
    assert action.authorizer_authenticated is False


def test_title_and_body_are_reconstructed_from_authoritative_chain():
    authorization = _authorized()
    package = (
        authorization.decision_recording.review.source_rendering
        .pr_package_creation.pr_package
    )
    rendering = (
        authorization.decision_recording.review.source_rendering.rendering
    )
    action = prepare_pr_publication_action(authorization)
    scope = dict(action.scope)
    assert scope["title"] == package.proposed_pr_title
    assert scope["body"] == rendering.pr_body
    assert scope["title_sha256"] == authorization.supplied.title_sha256
    assert scope["body_sha256"] == authorization.supplied.body_sha256


@pytest.mark.parametrize(
    "field,value",
    [
        ("repository", "other/repo"), ("base_sha", "b" * 40),
        ("target_branch", "develop"), ("source_branch", "other/head"),
        ("title_sha256", "b" * 64), ("body_sha256", "c" * 64),
    ],
)
def test_unauthorized_or_mismatched_scope_is_not_prepared(field, value):
    decision = _decision()
    supplied = replace(_authorization(decision), **{field: value})
    authorization = authorize_pr_publication(decision, supplied)
    assert authorization.status == STATUS_NOT_AUTHORIZED
    action = prepare_pr_publication_action(authorization)
    assert action.status == STATUS_NOT_PREPARED
    assert action.scope is None
    assert action.idempotency_key is None


def test_wrong_operation_and_merge_cannot_be_represented():
    decision = _decision()
    with pytest.raises(Exception):
        replace(_authorization(decision), operation="merge_pull_request")


def test_stable_idempotency_identity_is_scope_identity_only():
    authorization = _authorized()
    first = prepare_pr_publication_action(authorization)
    second = prepare_pr_publication_action(authorization)
    assert first.idempotency_key == second.idempotency_key
    assert len(first.idempotency_key) == 64
    assert first.executed is False


@pytest.mark.parametrize(
    "field",
    ["title", "body", "repository", "base_sha", "authorization_id"],
)
def test_mutating_action_scope_is_rejected(field):
    action = prepare_pr_publication_action(_authorized())
    scope = dict(action.scope)
    scope[field] = str(scope[field]) + "changed"
    with pytest.raises(PRPublicationActionError, match="forged"):
        replace(action, scope=scope)


def test_action_is_immutable_deterministic_bounded_and_sanitized():
    authorization = _authorized()
    first = prepare_pr_publication_action(authorization)
    second = prepare_pr_publication_action(authorization)
    assert first.summary() == second.summary()
    assert len(first.summary().encode("utf-8")) <= (
        MAX_PR_PUBLICATION_ACTION_SUMMARY_BYTES
    )
    assert "token" not in first.summary().casefold()
    with pytest.raises(FrozenInstanceError):
        first.status = STATUS_NOT_PREPARED
    with pytest.raises(TypeError):
        first.scope[0] = ("title", "changed")


def test_multibyte_scope_identity_uses_utf8_content_deterministically():
    action = prepare_pr_publication_action(_authorized())
    scope = dict(action.scope)
    scope["title"] = "Review ☃️é"
    with pytest.raises(PRPublicationActionError, match="forged"):
        replace(action, scope=tuple(sorted(scope.items())))


def test_invalid_input_type_rejected():
    with pytest.raises(PRPublicationActionError):
        prepare_pr_publication_action(None)


def test_module_has_no_executor_or_external_authority():
    path = (
        Path(__file__).parents[1]
        / "scripts/capability_build/pr_publication_action.py"
    )
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    forbidden_imports = {
        "backend", "git", "github", "httpx", "os", "pathlib",
        "requests", "shutil", "subprocess",
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
