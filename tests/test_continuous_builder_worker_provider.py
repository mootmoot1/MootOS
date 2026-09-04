from dataclasses import FrozenInstanceError, replace

import pytest

from backend.continuous_builder.worker_provider import (
    WorkerDescriptor,
    WorkerProviderError,
    WorkerRequirement,
    match_worker,
)


def _worker(provider="provider-b", worker="worker-1", **changes):
    values = {
        "provider_id": provider,
        "worker_id": worker,
        "model_id": "model-1",
        "supported_task_classes": ("bounded_code_change",),
        "supported_capabilities": ("python", "testing"),
        "max_context_bytes": 65536,
        "max_output_bytes": 32768,
        "availability_class": "available",
    }
    values.update(changes)
    return WorkerDescriptor(**values)


def _requirement(**changes):
    values = {
        "task_class": "bounded_code_change",
        "required_capabilities": ("testing", "python"),
        "required_context_bytes": 4096,
        "required_output_bytes": 2048,
    }
    values.update(changes)
    return WorkerRequirement(**values)


def test_matching_is_deterministic_and_input_order_independent():
    left = _worker("provider-b")
    right = _worker("provider-a")
    first = match_worker(_requirement(), (left, right))
    second = match_worker(_requirement(), (right, left))
    assert first == second
    assert first.status == "matched"
    assert first.worker == right
    assert first.worker.canonical_bytes() == right.canonical_bytes()


def test_unknown_capability_fails_closed():
    result = match_worker(
        _requirement(required_capabilities=("python", "unknown")),
        (_worker(),),
    )
    assert result.status == "not_matched"
    assert result.worker is None


@pytest.mark.parametrize(
    "changes",
    [
        {"supported_capabilities": ("python", "python")},
        {"supported_capabilities": "python"},
        {"provider_id": "x" * 129},
        {"availability_class": "self_declared_superuser"},
    ],
)
def test_malformed_oversize_and_duplicate_descriptor_values_rejected(changes):
    with pytest.raises(WorkerProviderError):
        _worker(**changes)


@pytest.mark.parametrize(
    "field",
    [
        "execution_authorized", "authenticated", "credentials_available",
        "scope_growth_allowed", "budget_growth_allowed",
        "queue_transition_allowed", "approval_granted",
    ],
)
def test_provider_metadata_cannot_manufacture_authority(field):
    with pytest.raises(WorkerProviderError):
        _worker(**{field: True})


def test_descriptor_is_immutable_bounded_and_unicode_safe():
    descriptor = _worker(model_id="modèle")
    assert len(descriptor.canonical_bytes()) < 32 * 1024
    with pytest.raises(FrozenInstanceError):
        descriptor.worker_id = "other"
    with pytest.raises(WorkerProviderError):
        replace(descriptor, model_id="\ud800")


def test_duplicate_worker_identity_and_string_collection_rejected():
    with pytest.raises(WorkerProviderError):
        match_worker(_requirement(), (_worker(), _worker()))
    with pytest.raises(WorkerProviderError):
        match_worker(_requirement(), "workers")
