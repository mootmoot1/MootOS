from dataclasses import FrozenInstanceError, replace

import pytest

from backend.continuous_builder.worker_action import (
    WorkerActionError, WorkerCancellationIntent, WorkerResultInput,
    prepare_worker_launch_action, record_worker_result,
)
from tests.test_continuous_builder_worker_authorization import _authorization


def _action():
    return prepare_worker_launch_action(_authorization())


def _result(action, **changes):
    values = {
        "receipt_id": "receipt-1", "action_digest": action.action_digest,
        "attempt_id": action.attempt_id,
        "worker_descriptor_digest": action.worker_descriptor_digest,
        "reported_status": "reported_success",
        "bounded_output": "Provider reports tests passed.",
    }
    values.update(changes)
    return WorkerResultInput(**values)


def test_launch_action_is_exact_single_purpose_and_inert():
    action = _action()
    assert action.operation == "launch_bounded_worker"
    assert action.action_prepared is True
    assert action.executed is False
    assert action.execution_performed is False
    assert len(action.canonical_bytes()) < 32 * 1024


def test_unauthorized_or_forged_executed_action_rejected():
    denied = _authorization(authorization_input=replace(
        _authorization().authorization_input,
        authenticated=False, authentication_evidence_digest=None,
    ))
    with pytest.raises(WorkerActionError):
        prepare_worker_launch_action(denied)
    action = _action()
    for field in ("executed", "execution_performed"):
        with pytest.raises(WorkerActionError):
            replace(action, **{field: True})


def test_wrong_request_attempt_provider_or_digest_rejected():
    action = _action()
    for name, value in (
        ("request_digest", "0" * 64), ("attempt_id", "other"),
        ("worker_descriptor_digest", "0" * 64),
        ("authorization_digest", "0" * 64),
        ("action_digest", "0" * 64),
    ):
        with pytest.raises(WorkerActionError):
            replace(action, **{name: value})


def test_provider_success_is_recorded_as_untrusted_unverified_report():
    action = _action()
    receipt = record_worker_result(action, _result(action))
    assert receipt.status == "reported_success"
    assert receipt.result_recorded is True
    assert receipt.provider_output_trusted is False
    assert receipt.externally_verified is False
    assert receipt.execution_performed_by_this_module is False
    assert len(receipt.canonical_bytes()) < 64 * 1024


def test_result_binding_malformed_status_and_oversize_fail_closed():
    action = _action()
    with pytest.raises(WorkerActionError):
        record_worker_result(action, _result(action, attempt_id="other"))
    with pytest.raises(WorkerActionError):
        _result(action, reported_status="verified_success")
    with pytest.raises(WorkerActionError):
        _result(action, bounded_output="x" * (32 * 1024 + 1))
    with pytest.raises(WorkerActionError):
        _result(action, bounded_output="api_key=do-not-store")


def test_cancellation_intent_does_not_claim_cancellation_result():
    action = _action()
    intent = WorkerCancellationIntent(
        "cancel-1", action.action_digest, action.attempt_id,
        "human:operator", "Stop requested for inspection.",
    )
    assert intent.cancellation_requested is True
    assert intent.cancellation_performed is False
    assert intent.cancellation_verified is False
    with pytest.raises(WorkerActionError):
        replace(intent, cancellation_performed=True)


def test_action_and_receipt_are_immutable_and_unicode_safe():
    action = _action()
    receipt = record_worker_result(action, _result(
        action, bounded_output="Rapport non vérifié.",
    ))
    with pytest.raises(FrozenInstanceError):
        action.executed = True
    with pytest.raises(FrozenInstanceError):
        receipt.externally_verified = True
