import base64
import dataclasses
import hashlib
import json
from dataclasses import FrozenInstanceError

import pytest

import backend.continuous_builder.artifact_output as artifact_output
import backend.continuous_builder.worker_artifact as worker_artifact
from backend.continuous_builder.artifact_output import (
    ArtifactOutputError,
    bridge_execution_stdout_to_artifact_intake,
)
from tests.test_continuous_builder_worker_runtime import FakeDocker, _execute


def _digest(value):
    return hashlib.sha256(value).hexdigest()


def _envelope(receipt_values=None, artifacts=None, *, result_verified=False):
    receipt_values = receipt_values or {}
    artifacts = artifacts or {"value.txt": b"2\n"}
    body = {
        "protocol": "mootos-artifact-output-v1",
        "attempt_id": receipt_values.get("attempt_id", "attempt-1"),
        "request_digest": receipt_values.get("request_digest"),
        "result_verified": result_verified,
        "artifacts": [
            {
                "path": path,
                "content_base64": base64.b64encode(content).decode("ascii"),
                "content_sha256": _digest(content),
            }
            for path, content in sorted(artifacts.items())
        ],
    }
    return json.dumps(
        body, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8") + b"\n"


def _execution(tmp_path, monkeypatch, *, artifacts=None, mutate=None):
    from tests.test_continuous_builder_worker_runtime import _foundation

    foundation = _foundation()
    values = {
        "attempt_id": foundation.attempt_id,
        "request_digest": foundation.request_digest,
    }
    raw = _envelope(values, artifacts)
    if mutate is not None:
        raw = mutate(raw, values)
    receipt, _ = _execute(
        tmp_path,
        monkeypatch,
        foundation=foundation,
        fake=FakeDocker(logs=raw),
    )
    intake_root = tmp_path / "artifact-intake"
    monkeypatch.setattr(artifact_output, "ARTIFACT_INTAKE_ROOT", intake_root)
    monkeypatch.setattr(worker_artifact, "ARTIFACT_INTAKE_ROOT", intake_root)
    return receipt, raw, intake_root


def _forge(instance, **changes):
    forged = object.__new__(type(instance))
    for item in dataclasses.fields(instance):
        object.__setattr__(
            forged,
            item.name,
            changes.get(item.name, getattr(instance, item.name)),
        )
    return forged


def test_stdout_artifact_bytes_are_bound_to_exact_execution_and_quarantined(
    tmp_path, monkeypatch,
):
    receipt, raw, intake_root = _execution(tmp_path, monkeypatch)
    result = bridge_execution_stdout_to_artifact_intake(receipt)

    proof = result.provenance_receipt
    assert proof.execution_receipt_digest == receipt.receipt_sha256
    assert proof.execution_id == receipt.execution_id
    assert proof.container_id == receipt.container_id
    assert proof.attempt_id == receipt.attempt_id
    assert proof.request_digest == receipt.request_digest
    assert proof.stdout_sha256 == _digest(raw)
    assert proof.stdout_size == len(raw)
    assert proof.stdout_complete_in_trusted_receipt is True
    assert proof.artifact_bytes_bound_to_execution_stdout is True
    assert proof.artifact_content_provenance_proven is True
    assert result.intake_result.receipt.status == "quarantined_untrusted"
    assert result.intake_result.quarantine_package.inventory[0].relative_path == (
        "value.txt"
    )
    assert result.intake_result._artifact_payloads == (("value.txt", b"2\n"),)
    assert not (intake_root / receipt.execution_id).exists()


def test_provenance_does_not_promote_worker_output_or_merge_authority(
    tmp_path, monkeypatch,
):
    receipt, _, _ = _execution(tmp_path, monkeypatch)
    result = bridge_execution_stdout_to_artifact_intake(receipt)
    proof = result.provenance_receipt
    assert proof.worker_output_trusted is False
    assert proof.result_verified is False
    assert proof.patch_verified is False
    assert proof.publication_authorized is False
    assert proof.queue_transition_authorized is False
    assert proof.github_authorized is False
    assert proof.merge_authorized is False
    with pytest.raises(FrozenInstanceError):
        proof.result_verified = True


def test_worker_cannot_claim_result_verified(tmp_path, monkeypatch):
    from tests.test_continuous_builder_worker_runtime import _foundation

    foundation = _foundation()
    raw = _envelope(
        {
            "attempt_id": foundation.attempt_id,
            "request_digest": foundation.request_digest,
        },
        result_verified=True,
    )
    receipt, _ = _execute(
        tmp_path, monkeypatch, foundation=foundation, fake=FakeDocker(logs=raw)
    )
    intake_root = tmp_path / "artifact-intake"
    monkeypatch.setattr(artifact_output, "ARTIFACT_INTAKE_ROOT", intake_root)
    monkeypatch.setattr(worker_artifact, "ARTIFACT_INTAKE_ROOT", intake_root)
    with pytest.raises(ArtifactOutputError, match="overstates verification"):
        bridge_execution_stdout_to_artifact_intake(receipt)


def test_request_binding_mismatch_is_rejected(tmp_path, monkeypatch):
    def mutate(raw, values):
        body = json.loads(raw)
        body["request_digest"] = "0" * 64
        return json.dumps(
            body, sort_keys=True, separators=(",", ":")
        ).encode() + b"\n"

    receipt, _, _ = _execution(tmp_path, monkeypatch, mutate=mutate)
    with pytest.raises(ArtifactOutputError, match="binding mismatch"):
        bridge_execution_stdout_to_artifact_intake(receipt)


def test_attempt_binding_mismatch_is_rejected(tmp_path, monkeypatch):
    def mutate(raw, values):
        body = json.loads(raw)
        body["attempt_id"] = "attempt-other"
        return json.dumps(
            body, sort_keys=True, separators=(",", ":")
        ).encode() + b"\n"

    receipt, _, _ = _execution(tmp_path, monkeypatch, mutate=mutate)
    with pytest.raises(ArtifactOutputError, match="binding mismatch"):
        bridge_execution_stdout_to_artifact_intake(receipt)


def test_payload_digest_mismatch_is_rejected(tmp_path, monkeypatch):
    def mutate(raw, values):
        body = json.loads(raw)
        body["artifacts"][0]["content_sha256"] = "0" * 64
        return json.dumps(
            body, sort_keys=True, separators=(",", ":")
        ).encode() + b"\n"

    receipt, _, _ = _execution(tmp_path, monkeypatch, mutate=mutate)
    with pytest.raises(ArtifactOutputError, match="digest mismatch"):
        bridge_execution_stdout_to_artifact_intake(receipt)


def test_non_hex_payload_digest_is_rejected(tmp_path, monkeypatch):
    def mutate(raw, values):
        body = json.loads(raw)
        body["artifacts"][0]["content_sha256"] = "z" * 64
        return json.dumps(
            body, sort_keys=True, separators=(",", ":")
        ).encode() + b"\n"

    receipt, _, _ = _execution(tmp_path, monkeypatch, mutate=mutate)
    with pytest.raises(ArtifactOutputError, match="malformed"):
        bridge_execution_stdout_to_artifact_intake(receipt)


@pytest.mark.parametrize("path", ("../escape", "/absolute", "C:/drive"))
def test_unsafe_artifact_path_is_rejected(tmp_path, monkeypatch, path):
    receipt, _, _ = _execution(
        tmp_path, monkeypatch, artifacts={path: b"bad"}
    )
    with pytest.raises(ArtifactOutputError, match="path"):
        bridge_execution_stdout_to_artifact_intake(receipt)


def test_secret_scan_still_controls_quarantine(tmp_path, monkeypatch):
    secret = b"Authorization: Bearer abcdefghijklmnop\n"
    receipt, _, _ = _execution(
        tmp_path, monkeypatch, artifacts={"value.txt": secret}
    )
    result = bridge_execution_stdout_to_artifact_intake(receipt)
    assert result.provenance_receipt.artifact_content_provenance_proven is True
    assert result.intake_result.receipt.status == "rejected_secret_material"
    assert result.intake_result.quarantine_package is None
    assert result.provenance_receipt.quarantine_package_digest == ""


def test_truncated_stdout_sample_cannot_establish_provenance(
    tmp_path, monkeypatch,
):
    receipt, _, _ = _execution(tmp_path, monkeypatch)
    forged = _forge(receipt, stdout_size=receipt.stdout_size + 1)
    with pytest.raises(ArtifactOutputError):
        bridge_execution_stdout_to_artifact_intake(forged)


def test_forged_stdout_digest_is_rejected(tmp_path, monkeypatch):
    receipt, _, _ = _execution(tmp_path, monkeypatch)
    forged = _forge(receipt, stdout_sha256="0" * 64)
    with pytest.raises(ArtifactOutputError):
        bridge_execution_stdout_to_artifact_intake(forged)


def test_existing_staging_identity_fails_closed(tmp_path, monkeypatch):
    receipt, _, intake_root = _execution(tmp_path, monkeypatch)
    intake_root.mkdir(mode=0o700, parents=True)
    root = intake_root / receipt.execution_id
    root.mkdir(mode=0o700)
    (root / "do-not-overwrite").write_bytes(b"x")
    with pytest.raises(ArtifactOutputError, match="already exists"):
        bridge_execution_stdout_to_artifact_intake(receipt)
    assert (root / "do-not-overwrite").read_bytes() == b"x"


def test_staging_cleanup_uncertainty_fails_closed(tmp_path, monkeypatch):
    receipt, _, _ = _execution(tmp_path, monkeypatch)
    real_cleanup = artifact_output._cleanup
    calls = {"count": 0}

    def uncertain_cleanup(root):
        calls["count"] += 1
        real_cleanup(root)
        return False

    monkeypatch.setattr(artifact_output, "_cleanup", uncertain_cleanup)
    with pytest.raises(ArtifactOutputError, match="cleanup is uncertain"):
        bridge_execution_stdout_to_artifact_intake(receipt)
    assert calls["count"] == 1


def test_provenance_receipt_digest_detects_forgery(tmp_path, monkeypatch):
    receipt, _, _ = _execution(tmp_path, monkeypatch)
    proof = bridge_execution_stdout_to_artifact_intake(receipt).provenance_receipt
    with pytest.raises(ArtifactOutputError):
        dataclasses.replace(proof, stdout_sha256="0" * 64)
