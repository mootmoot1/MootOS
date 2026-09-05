import base64
import dataclasses
import hashlib
import json

import pytest

import backend.continuous_builder.artifact_output as artifact_output
import backend.continuous_builder.worker_artifact as worker_artifact
from backend.continuous_builder.artifact_output import (
    ArtifactOutputError,
    bridge_execution_stdout_to_artifact_intake,
)
from backend.continuous_builder.blast_radius import evaluate_blast_radius
from backend.continuous_builder.candidate_verifier import verify_candidate
from backend.continuous_builder.proof_fixture import create_increment_value_task
from backend.continuous_builder.supervisor import (
    create_supervision_policy,
    supervise_execution,
)
from backend.continuous_builder.trust_chain_proof import (
    TrustChainProofError,
    build_trust_chain_proof,
)
from tests.test_continuous_builder_worker_runtime import (
    FakeDocker,
    _execute,
    _foundation,
)


def _digest(value):
    return hashlib.sha256(value).hexdigest()


def _stdout(foundation, content=b"2\n"):
    body = {
        "artifacts": [{
            "content_base64": base64.b64encode(content).decode("ascii"),
            "content_sha256": _digest(content),
            "path": "value.txt",
        }],
        "attempt_id": foundation.attempt_id,
        "protocol": "mootos-artifact-output-v1",
        "request_digest": foundation.request_digest,
        "result_verified": False,
    }
    return json.dumps(
        body, sort_keys=True, separators=(",", ":")
    ).encode("utf-8") + b"\n"


def _proven_chain(tmp_path, monkeypatch, content=b"2\n"):
    foundation = _foundation()
    receipt, _ = _execute(
        tmp_path,
        monkeypatch,
        foundation=foundation,
        fake=FakeDocker(logs=_stdout(foundation, content)),
    )
    intake_root = tmp_path / "artifact-intake"
    monkeypatch.setattr(artifact_output, "ARTIFACT_INTAKE_ROOT", intake_root)
    monkeypatch.setattr(worker_artifact, "ARTIFACT_INTAKE_ROOT", intake_root)
    bridge = bridge_execution_stdout_to_artifact_intake(receipt)
    task = create_increment_value_task()
    decision = supervise_execution(
        receipt,
        create_supervision_policy(),
        artifact_intake_receipt=bridge.intake_result.receipt,
    )
    blast = None
    verification = None
    if bridge.intake_result.quarantine_package is not None:
        blast = evaluate_blast_radius(task, receipt, bridge.intake_result)
        verification = verify_candidate(task, receipt, bridge.intake_result)
    proof = build_trust_chain_proof(
        task,
        receipt,
        decision,
        bridge.intake_result,
        blast,
        verification,
        artifact_provenance_receipt=bridge.provenance_receipt,
    )
    return receipt, bridge, blast, verification, proof


def test_exact_stdout_provenance_unlocks_contained_verified_candidate(
    tmp_path, monkeypatch,
):
    receipt, bridge, blast, verification, proof = _proven_chain(
        tmp_path, monkeypatch
    )

    assert receipt.final_state == "succeeded"
    assert bridge.intake_result.receipt.status == "quarantined_untrusted"
    assert bridge.provenance_receipt.artifact_content_provenance_proven is True
    assert blast.status == "within_blast_radius_unverified"
    assert verification.status == "verification_passed"
    assert proof.final_classification == "contained_verified_candidate"
    assert proof.reason_code == "contained_trust_chain_survived"
    assert proof.artifact_intake_ordering_proven is True
    assert proof.artifact_content_provenance_proven is True
    assert proof.artifact_provenance_receipt_digest == (
        bridge.provenance_receipt.receipt_sha256
    )
    assert "artifact_intake_ordering_unproven" not in proof.known_limitations
    assert proof.human_review_required is True
    assert proof.result_trusted is False
    assert proof.worker_output_trusted is False
    assert proof.publication_authorized is False
    assert proof.queue_transition_authorized is False
    assert proof.github_authorized is False
    assert proof.merge_authorized is False
    assert proof.main_advancement_authorized is False


def test_wrong_stdout_artifact_still_fails_independent_verification(
    tmp_path, monkeypatch,
):
    _, bridge, blast, verification, proof = _proven_chain(
        tmp_path, monkeypatch, content=b"3\n"
    )
    assert bridge.provenance_receipt.artifact_content_provenance_proven is True
    assert blast.status == "within_blast_radius_unverified"
    assert verification.status == "verification_failed"
    assert proof.final_classification == "rejected_verification"
    assert proof.reason_code == "verification_failed"


def test_provenance_receipt_for_other_intake_cannot_unlock_candidate(
    tmp_path, monkeypatch,
):
    receipt, bridge, blast, verification, _ = _proven_chain(
        tmp_path, monkeypatch
    )
    task = create_increment_value_task()
    decision = supervise_execution(
        receipt,
        create_supervision_policy(),
        artifact_intake_receipt=bridge.intake_result.receipt,
    )

    # The receipt's own invariant catches a self-inconsistent mutation.
    with pytest.raises(ArtifactOutputError):
        dataclasses.replace(
            bridge.provenance_receipt,
            intake_receipt_digest="0" * 64,
            receipt_sha256="0" * 64,
        )

    # A raw object that bypasses construction still fails exact trust-chain binding.
    forged = object.__new__(type(bridge.provenance_receipt))
    for item in dataclasses.fields(bridge.provenance_receipt):
        object.__setattr__(
            forged,
            item.name,
            "0" * 64 if item.name == "intake_receipt_digest"
            else getattr(bridge.provenance_receipt, item.name),
        )
    with pytest.raises(TrustChainProofError):
        build_trust_chain_proof(
            task,
            receipt,
            decision,
            bridge.intake_result,
            blast,
            verification,
            artifact_provenance_receipt=forged,
        )
