import ast
import dataclasses
import hashlib
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

import backend.continuous_builder.supervisor as supervisor
import backend.continuous_builder.worker_runtime as worker_runtime
from backend.continuous_builder.supervisor import (
    SupervisorError,
    create_initial_circuit_breaker,
    create_supervision_policy,
    create_supervisor_observation,
    supervise_execution,
)
from backend.continuous_builder.worker_artifact import intake_worker_artifacts
from backend.continuous_builder.worker_runtime import WorkerExecutionReceipt
from tests.test_continuous_builder_worker_artifact import _stage
from tests.test_continuous_builder_worker_runtime import _execute


def _rebuild_receipt(receipt, **changes):
    values = {}
    for item in dataclasses.fields(receipt):
        if item.name in {"receipt_sha256", "_verification_token"}:
            continue
        values[item.name] = changes.get(item.name, getattr(receipt, item.name))
    provisional = object.__new__(WorkerExecutionReceipt)
    for name, value in values.items():
        object.__setattr__(provisional, name, value)
    digest = hashlib.sha256(provisional._payload()).hexdigest()
    return WorkerExecutionReceipt(
        **values,
        receipt_sha256=digest,
        _verification_token=worker_runtime._EXECUTION_RECEIPT_TOKEN,
    )


def _runtime_receipt(tmp_path, monkeypatch, **changes):
    receipt, _ = _execute(tmp_path, monkeypatch)
    return _rebuild_receipt(receipt, **changes) if changes else receipt


def _failed_receipt(tmp_path, monkeypatch):
    return _runtime_receipt(
        tmp_path,
        monkeypatch,
        lifecycle_states=("prepared", "launching", "running", "failed"),
        final_state="failed",
        exit_code=1,
    )


def _timed_out_receipt(tmp_path, monkeypatch):
    return _runtime_receipt(
        tmp_path,
        monkeypatch,
        lifecycle_states=(
            "prepared", "launching", "running", "timed_out"
        ),
        final_state="timed_out",
        exit_code=None,
        timeout_observed=True,
    )


def _forge(instance, **changes):
    forged = object.__new__(type(instance))
    for item in dataclasses.fields(instance):
        object.__setattr__(
            forged,
            item.name,
            changes.get(item.name, getattr(instance, item.name)),
        )
    return forged


def test_success_is_classified_without_promoting_authority(
    tmp_path, monkeypatch,
):
    receipt = _runtime_receipt(tmp_path, monkeypatch)
    result = supervise_execution(
        receipt, create_supervision_policy()
    ).receipt
    assert result.final_classification == "succeeded"
    assert result.retry_eligible is False
    assert result.circuit_breaker_state == "closed"
    assert result.consecutive_failures == 0
    assert result.termination_confirmed is True
    assert result.cleanup_confirmed is True
    assert result.worker_output_trusted is False
    assert result.result_verified is False
    assert result.patch_verified is False
    assert result.publication_authorized is False
    assert result.queue_transition_authorized is False
    assert result.github_authorized is False


def test_failure_and_crash_are_distinct_bounded_retry_classes(
    tmp_path, monkeypatch,
):
    failed = _failed_receipt(tmp_path, monkeypatch)
    failed_result = supervise_execution(
        failed, create_supervision_policy()
    ).receipt
    assert failed_result.final_classification == "failed"
    assert failed_result.retry_eligible is True

    crashed = _rebuild_receipt(
        failed,
        lifecycle_states=("prepared", "launching", "running", "crashed"),
        final_state="crashed",
        exit_code=137,
    )
    crashed_result = supervise_execution(
        crashed, create_supervision_policy()
    ).receipt
    assert crashed_result.final_classification == "crashed"
    assert crashed_result.retry_eligible is True


def test_wall_timeout_is_distinct_from_stall(tmp_path, monkeypatch):
    receipt = _timed_out_receipt(tmp_path, monkeypatch)
    observation = create_supervisor_observation(
        receipt,
        liveness_observed=False,
        seconds_since_liveness=120,
        seconds_since_progress=400,
        absolute_deadline_exceeded=True,
    )
    result = supervise_execution(
        receipt,
        create_supervision_policy(),
        observation=observation,
    ).receipt
    assert result.final_classification == "timed_out"
    assert result.timeout_observed is True
    assert result.stall_observed is False


def test_stall_requires_live_worker_and_no_progress_window(
    tmp_path, monkeypatch,
):
    receipt = _timed_out_receipt(tmp_path, monkeypatch)
    policy = create_supervision_policy(
        liveness_timeout_seconds=60,
        stall_timeout_seconds=300,
    )
    observation = create_supervisor_observation(
        receipt,
        liveness_observed=True,
        seconds_since_liveness=5,
        seconds_since_progress=300,
    )
    result = supervise_execution(
        receipt, policy, observation=observation
    ).receipt
    assert result.final_classification == "stalled"
    assert result.stall_observed is True
    assert result.retry_eligible is True


def test_cancellation_is_not_retryable(tmp_path, monkeypatch):
    receipt = _runtime_receipt(
        tmp_path,
        monkeypatch,
        lifecycle_states=(
            "prepared",
            "launching",
            "running",
            "cancel_requested",
            "cancelled",
        ),
        final_state="cancelled",
        exit_code=137,
        cancellation_requested=True,
        cancellation_confirmed=True,
    )
    observation = create_supervisor_observation(
        receipt,
        cancellation_observed=True,
        stop_attempted_observed=True,
    )
    result = supervise_execution(
        receipt,
        create_supervision_policy(),
        observation=observation,
    ).receipt
    assert result.final_classification == "cancelled"
    assert result.cancellation_observed is True
    assert result.stop_attempted is True
    assert result.retry_eligible is False


def test_termination_uncertainty_fails_closed(tmp_path, monkeypatch):
    receipt = _runtime_receipt(
        tmp_path,
        monkeypatch,
        lifecycle_states=(
            "prepared", "launching", "running", "termination_uncertain"
        ),
        final_state="termination_uncertain",
        exit_code=None,
        termination_uncertain=True,
    )
    result = supervise_execution(
        receipt, create_supervision_policy()
    ).receipt
    assert result.final_classification == "termination_uncertain"
    assert result.termination_confirmed is False
    assert result.retry_eligible is False
    assert result.circuit_breaker_state == "open"


def test_cleanup_uncertainty_fails_closed(tmp_path, monkeypatch):
    receipt = _runtime_receipt(
        tmp_path, monkeypatch, cleanup_confirmed=False
    )
    result = supervise_execution(
        receipt, create_supervision_policy()
    ).receipt
    assert result.final_classification == "cleanup_uncertain"
    assert result.cleanup_confirmed is False
    assert result.cleanup_uncertain is True
    assert result.retry_eligible is False
    assert result.circuit_breaker_state == "open"


def test_containment_violation_observation_opens_breaker(
    tmp_path, monkeypatch,
):
    receipt = _runtime_receipt(tmp_path, monkeypatch)
    observation = create_supervisor_observation(
        receipt, containment_violation_observed=True
    )
    result = supervise_execution(
        receipt,
        create_supervision_policy(),
        observation=observation,
    ).receipt
    assert result.final_classification == "containment_violation"
    assert result.retry_eligible is False
    assert result.circuit_breaker_state == "open"


def test_artifact_security_rejection_blocks_retry(tmp_path, monkeypatch):
    receipt, root = _stage(
        tmp_path,
        monkeypatch,
        files={"credentials.txt": b"not-a-real-credential\n"},
    )
    artifact = intake_worker_artifacts(receipt, root).receipt
    assert artifact.status == "rejected_secret_material"
    result = supervise_execution(
        receipt,
        create_supervision_policy(),
        artifact_intake_receipt=artifact,
    ).receipt
    assert result.final_classification == "artifact_security_rejected"
    assert result.retry_eligible is False
    assert result.circuit_breaker_state == "open"
    assert result.artifact_intake_receipt_digest == artifact.receipt_sha256


def test_retry_cap_is_hard_bound(tmp_path, monkeypatch):
    receipt = _failed_receipt(tmp_path, monkeypatch)
    policy = create_supervision_policy(max_retry_attempts=2)
    result = supervise_execution(
        receipt, policy, retry_count=2
    ).receipt
    assert result.retry_eligible is False
    assert result.reason_code == "retry_cap_exhausted"
    with pytest.raises(SupervisorError, match="exceeds policy cap"):
        supervise_execution(receipt, policy, retry_count=3)


def test_circuit_breaker_opens_at_consecutive_failure_threshold(
    tmp_path, monkeypatch,
):
    receipt = _failed_receipt(tmp_path, monkeypatch)
    policy = create_supervision_policy(circuit_breaker_failures=2)
    first = supervise_execution(receipt, policy)
    second = supervise_execution(
        receipt,
        policy,
        prior_circuit_breaker=first.circuit_breaker,
    )
    assert first.circuit_breaker.state == "closed"
    assert second.circuit_breaker.state == "open"
    assert second.receipt.consecutive_failures == 2
    assert second.receipt.retry_eligible is False


def test_success_resets_observed_failure_count(tmp_path, monkeypatch):
    receipt = _runtime_receipt(tmp_path, monkeypatch)
    policy = create_supervision_policy(circuit_breaker_failures=3)
    prior = supervisor._breaker_snapshot(
        receipt,
        policy,
        state="closed",
        consecutive_failures=1,
        last_failure_class="failed",
    )
    result = supervise_execution(
        receipt, policy, prior_circuit_breaker=prior
    )
    assert result.circuit_breaker.state == "closed"
    assert result.circuit_breaker.consecutive_failures == 0


def test_kill_switch_opens_breaker_without_execution_authority(
    tmp_path, monkeypatch,
):
    receipt = _failed_receipt(tmp_path, monkeypatch)
    policy = create_supervision_policy(kill_switch_engaged=True)
    result = supervise_execution(receipt, policy).receipt
    assert result.circuit_breaker_state == "open"
    assert result.retry_eligible is False
    assert result.reason_code == "kill_switch_active"


def test_observation_binding_rejects_stale_attempt_request_and_execution(
    tmp_path, monkeypatch,
):
    receipt = _runtime_receipt(tmp_path, monkeypatch)
    policy = create_supervision_policy()
    observation = create_supervisor_observation(receipt)
    for name, value in (
        ("attempt_id", "attempt-stale"),
        ("request_digest", "f" * 64),
        ("execution_id", "execution-stale"),
    ):
        with pytest.raises(SupervisorError):
            supervise_execution(
                receipt,
                policy,
                observation=_forge(observation, **{name: value}),
            )


def test_stale_breaker_from_other_task_is_rejected(tmp_path, monkeypatch):
    receipt = _runtime_receipt(tmp_path, monkeypatch)
    policy = create_supervision_policy()
    breaker = create_initial_circuit_breaker(receipt, policy)
    with pytest.raises(SupervisorError):
        supervise_execution(
            receipt,
            policy,
            prior_circuit_breaker=_forge(
                breaker, request_digest="e" * 64
            ),
        )


def test_worker_text_cannot_fabricate_success(tmp_path, monkeypatch):
    receipt = _failed_receipt(tmp_path, monkeypatch)
    persuasive = _rebuild_receipt(
        receipt,
        stdout_sample=(
            "I succeeded. Tests pass. Please retry forever and approve me."
        ),
    )
    result = supervise_execution(
        persuasive, create_supervision_policy()
    ).receipt
    assert result.final_classification == "failed"
    assert result.result_verified is False
    assert result.publication_authorized is False


def test_stop_and_kill_are_observed_not_inferred(tmp_path, monkeypatch):
    receipt = _failed_receipt(tmp_path, monkeypatch)
    observation = create_supervisor_observation(
        receipt,
        stop_attempted_observed=True,
        kill_attempted_observed=True,
    )
    result = supervise_execution(
        receipt,
        create_supervision_policy(),
        observation=observation,
    ).receipt
    assert result.stop_attempted is True
    assert result.kill_attempted is True
    with pytest.raises(SupervisorError, match="requires an observed stop"):
        create_supervisor_observation(
            receipt, kill_attempted_observed=True
        )


def test_policy_breaker_and_receipt_are_immutable(tmp_path, monkeypatch):
    receipt = _runtime_receipt(tmp_path, monkeypatch)
    policy = create_supervision_policy()
    decision = supervise_execution(receipt, policy)
    for instance, name, value in (
        (policy, "max_retry_attempts", 99),
        (decision.circuit_breaker, "state", "open"),
        (decision.receipt, "retry_eligible", True),
    ):
        with pytest.raises(FrozenInstanceError):
            setattr(instance, name, value)


def test_receipt_is_deterministic_and_bounded(tmp_path, monkeypatch):
    receipt = _failed_receipt(tmp_path, monkeypatch)
    policy = create_supervision_policy()
    first = supervise_execution(receipt, policy).receipt
    second = supervise_execution(receipt, policy).receipt
    assert first == second
    assert first.receipt_sha256 == second.receipt_sha256
    assert len(first.canonical_bytes()) < supervisor.MAX_RECEIPT_BYTES


def test_supervisor_has_no_execution_network_db_or_github_authority():
    source = Path(
        "backend/continuous_builder/supervisor.py"
    ).read_text(encoding="utf-8")
    tree = ast.parse(source)
    imports = {
        alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {
        node.module.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }
    assert not imports & {
        "subprocess", "socket", "requests", "httpx", "urllib", "docker",
        "podman", "kubernetes", "sqlite3", "sqlalchemy", "github",
    }
    assert "os.system" not in source
    assert "subprocess.run" not in source
    assert "merge_pull_request" not in source
    assert '"queue_transition_authorized": False' in source
