from dataclasses import FrozenInstanceError, replace

import pytest

from backend.continuous_builder.worker_authorization import (
    DispatchAuthorizationInput, WorkerAuthorizationError,
    authorize_worker_dispatch,
)
from tests.test_continuous_builder_worker_provider import _worker
from tests.test_continuous_builder_worker_request import _request


EVIDENCE = "e" * 64


def _input(**changes):
    values = {
        "authorization_id": "authorization-1",
        "supplied_authorizer_identity": "human:reviewer",
        "authenticated": True,
        "authentication_evidence_digest": EVIDENCE,
        "authorization_granted": True,
    }
    values.update(changes)
    return DispatchAuthorizationInput(**values)


def _authorization(**changes):
    values = {
        "request": _request(), "worker": _worker(),
        "authorization_input": _input(),
    }
    values.update(changes)
    return authorize_worker_dispatch(**values)


def test_authorization_binds_exact_request_attempt_and_worker():
    result = _authorization()
    assert result.status == "authorized"
    assert result.authorized is True
    assert result.request_digest == result.request.request_digest
    assert result.attempt_id == result.request.attempt_id
    assert result.worker_descriptor_digest == result.worker.descriptor_sha256
    assert result.action_prepared is False
    assert result.authentication_independently_verified is False


def test_unauthenticated_or_ungranted_authorizer_fails_closed():
    unauthenticated = _input(
        authenticated=False, authentication_evidence_digest=None,
    )
    result = _authorization(authorization_input=unauthenticated)
    assert result.status == "not_authorized"
    assert result.blocking_reasons == ("authorizer_not_authenticated",)
    assert _authorization(authorization_input=_input(
        authorization_granted=False,
    )).status == "not_authorized"


def test_identity_text_alone_is_not_authentication_and_evidence_is_validated():
    with pytest.raises(WorkerAuthorizationError):
        _input(authenticated=True, authentication_evidence_digest=None)
    with pytest.raises(WorkerAuthorizationError):
        _input(authenticated=False, authentication_evidence_digest=EVIDENCE)


def test_provider_or_worker_cannot_self_authorize():
    result = _authorization(authorization_input=_input(
        supplied_authorizer_identity="provider-b",
    ))
    assert result.status == "not_authorized"
    assert "self_authorize" in result.blocking_reasons[0]


def test_wrong_request_attempt_worker_and_mutation_rejected():
    result = _authorization()
    for name, value in (
        ("request_digest", "0" * 64), ("attempt_id", "attempt-2"),
        ("worker_descriptor_digest", "0" * 64),
        ("authorization_digest", "0" * 64),
    ):
        with pytest.raises(WorkerAuthorizationError):
            replace(result, **{name: value})
    mismatch = authorize_worker_dispatch(
        _request(), _worker(supported_capabilities=("other",)), _input(),
    )
    assert mismatch.status == "not_authorized"


def test_authorization_is_immutable_bounded_and_never_launches():
    result = _authorization()
    assert len(result.canonical_bytes()) < 32 * 1024
    with pytest.raises(FrozenInstanceError):
        result.status = "not_authorized"
    for field in (
        "action_prepared", "launched", "execution_performed",
        "credentials_granted", "network_granted", "github_granted",
        "authentication_independently_verified",
    ):
        with pytest.raises(WorkerAuthorizationError):
            replace(result, **{field: True})
