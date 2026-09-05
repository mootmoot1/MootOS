"""CB-025 contained single-slice end-to-end trust-chain proof tests.

Every test drives the real merged pieces -- CB-022 ``DockerWorkerRuntime``
(against the existing fake Docker CLI), CB-023 ``intake_worker_artifacts``,
CB-024 ``supervise_execution`` -- and then the new CB-025 blast-radius gate,
independent verifier, and proof receipt.  No test asserts a property the
production code does not actually establish.
"""

import ast
import dataclasses
import hashlib
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

import backend.continuous_builder.blast_radius as blast_radius
import backend.continuous_builder.candidate_verifier as candidate_verifier
import backend.continuous_builder.trust_chain_proof as trust_chain_proof
from backend.continuous_builder.blast_radius import (
    BlastRadiusError,
    BlastRadiusReceipt,
    evaluate_blast_radius,
)
from backend.continuous_builder.candidate_verifier import (
    CandidateVerificationError,
    CandidateVerificationReceipt,
    verify_candidate,
)
from backend.continuous_builder.proof_fixture import (
    ProofFixtureError,
    create_fixture_task_contract,
    create_increment_value_task,
)
from backend.continuous_builder.supervisor import (
    create_supervision_policy,
    supervise_execution,
)
from backend.continuous_builder.trust_chain_proof import (
    TrustChainProofError,
    TrustChainProofReceipt,
    build_trust_chain_proof,
)
from backend.continuous_builder.worker_artifact import intake_worker_artifacts
from tests.test_continuous_builder_supervisor import _rebuild_receipt
from tests.test_continuous_builder_worker_artifact import _stage
from tests.test_continuous_builder_worker_runtime import FakeDocker, _execute


CORRECT = {"value.txt": b"2\n"}
CHEATING = {"value.txt": b"2\n", "sneaky.txt": b"unauthorized\n"}
WRONG = {"value.txt": b"3\n"}
TESTS_PASS_CLAIM = b'{"reported":"all tests passed","result_verified":true}\n'


def _chain(tmp_path, monkeypatch, files=CORRECT, *, receipt=None, fake=None):
    """Run one whole contained chain and return every evidence object."""
    if receipt is None:
        receipt, _ = _execute(tmp_path, monkeypatch, fake=fake)
    task = create_increment_value_task()
    _, root = _stage(tmp_path, monkeypatch, files, receipt=receipt)
    intake = intake_worker_artifacts(receipt, root)
    decision = supervise_execution(
        receipt,
        create_supervision_policy(),
        artifact_intake_receipt=intake.receipt,
    )
    blast = verification = None
    if intake.quarantine_package is not None:
        blast = evaluate_blast_radius(task, receipt, intake)
        verification = verify_candidate(task, receipt, intake)
    proof = build_trust_chain_proof(
        task, receipt, decision, intake, blast, verification
    )
    return task, receipt, decision, intake, blast, verification, proof


def _forge(instance, **changes):
    forged = object.__new__(type(instance))
    for item in dataclasses.fields(instance):
        object.__setattr__(
            forged,
            item.name,
            changes.get(item.name, getattr(instance, item.name)),
        )
    return forged


# 1. The tiny chain runs every stage and then fails closed on provenance.

def test_tiny_candidate_clears_every_stage_then_stops_at_provenance(
    tmp_path, monkeypatch,
):
    task, receipt, decision, intake, blast, verification, proof = _chain(
        tmp_path, monkeypatch,
    )

    # Every stage the system can actually evaluate does pass.
    assert receipt.final_state == "succeeded"
    assert decision.receipt.final_classification == "succeeded"
    assert intake.receipt.status == "quarantined_untrusted"
    assert blast.status == "within_blast_radius_unverified"
    assert blast.violations == ()
    assert verification.status == "verification_passed"
    assert verification.failure_codes == ()
    assert proof.task_id == "cb025-increment-value"

    # And the chain still stops, specifically because CB-022 gives the system
    # no way to prove these bytes came from this execution.
    assert proof.artifact_intake_ordering_proven is False
    assert proof.artifact_content_provenance_proven is False
    assert proof.final_classification == "rejected_uncertain_state"
    assert proof.reason_code == "artifact_provenance_unproven"
    assert proof.final_classification != "contained_verified_candidate"

    # Fail-closed does not mean authority leaks out some other way.
    assert proof.human_review_required is True
    assert proof.result_trusted is False
    assert proof.merge_authorized is False


# 2. Exact binding across every stage of the chain.

def test_proof_binds_every_stage_by_exact_digest(tmp_path, monkeypatch):
    task, receipt, decision, intake, blast, verification, proof = _chain(
        tmp_path, monkeypatch,
    )
    materialization = receipt.materialization_receipt

    assert proof.task_sha256 == task.task_sha256
    assert proof.acceptance_rule_sha256 == task.acceptance_rule_sha256
    assert proof.pinned_base_sha == materialization.pinned_base_sha
    assert proof.attempt_id == receipt.attempt_id
    assert proof.execution_id == receipt.execution_id
    assert proof.request_digest == receipt.request_digest
    assert proof.policy_digest == receipt.policy_digest
    assert proof.materialization_receipt_digest == (
        receipt.materialization_receipt_digest
    )
    assert proof.workspace_identity == (
        materialization.workspace_instance_digest
    )
    assert proof.execution_receipt_digest == receipt.receipt_sha256
    assert proof.supervision_receipt_digest == decision.receipt.receipt_sha256
    assert proof.circuit_breaker_snapshot_digest == (
        decision.circuit_breaker.snapshot_sha256
    )
    assert proof.artifact_intake_receipt_digest == (
        intake.receipt.receipt_sha256
    )
    assert proof.quarantine_package_digest == (
        intake.quarantine_package.package_sha256
    )
    assert proof.blast_radius_receipt_digest == blast.receipt_sha256
    assert proof.verification_receipt_digest == verification.receipt_sha256
    assert blast.quarantine_package_digest == (
        intake.quarantine_package.package_sha256
    )
    assert verification.quarantine_package_digest == (
        intake.quarantine_package.package_sha256
    )


# 3 / 15. Negative control: correct result plus an unauthorized extra file.

def test_unauthorized_extra_artifact_is_rejected_despite_correct_result(
    tmp_path, monkeypatch,
):
    _, _, _, _, blast, verification, proof = _chain(
        tmp_path, monkeypatch, CHEATING,
    )

    # The desired file really is correct, and the verifier really does say so.
    assert verification.status == "verification_passed"
    # Crossing the fence is still fatal, and the verifier cannot override it.
    assert blast.status == "blast_radius_rejected"
    assert "artifact_outside_allowed_paths" in blast.violations
    assert blast.violations == (
        "artifact_count_exceeds_boundary", "artifact_outside_allowed_paths",
    )
    assert proof.final_classification == "rejected_blast_radius"
    assert proof.reason_code == "blast_radius_rejected"
    assert proof.final_classification != "contained_verified_candidate"


def test_extra_artifact_beyond_the_count_bound_is_rejected(
    tmp_path, monkeypatch,
):
    task = create_fixture_task_contract(
        task_id="cb025-two-allowed-one-permitted",
        base_fixture=(("value.txt", b"1\n"),),
        allowed_paths=("other.txt", "value.txt"),
        expected_artifacts=(("value.txt", b"2\n"),),
        max_artifact_count=1,
    )
    receipt, _ = _execute(tmp_path, monkeypatch)
    _, root = _stage(
        tmp_path,
        monkeypatch,
        {"value.txt": b"2\n", "other.txt": b"also\n"},
        receipt=receipt,
    )
    intake = intake_worker_artifacts(receipt, root)
    blast = evaluate_blast_radius(task, receipt, intake)

    assert blast.status == "blast_radius_rejected"
    assert blast.violations == ("artifact_count_exceeds_boundary",)


# 4. A worker claiming "tests passed" cannot move the verifier.

def test_worker_claim_of_passing_tests_cannot_produce_verification(
    tmp_path, monkeypatch,
):
    fake = FakeDocker(logs=TESTS_PASS_CLAIM)
    _, receipt, _, _, _, verification, proof = _chain(
        tmp_path, monkeypatch, WRONG, fake=fake,
    )

    # The claim really is present in the untrusted worker output channel.
    assert "tests passed" in receipt.stdout_sample
    assert receipt.worker_output_trusted is False
    # And it changes nothing.
    assert verification.status == "verification_failed"
    assert verification.worker_claim_considered is False
    assert verification.worker_output_trusted is False
    assert proof.final_classification == "rejected_verification"


# 5. Wrong artifact contents fail verification.

def test_wrong_artifact_contents_fail_verification(tmp_path, monkeypatch):
    _, _, _, _, blast, verification, proof = _chain(
        tmp_path, monkeypatch, WRONG,
    )

    assert blast.status == "within_blast_radius_unverified"
    assert verification.status == "verification_failed"
    assert verification.failure_codes == (
        "expected_artifact_content_mismatch",
    )
    assert proof.final_classification == "rejected_verification"
    assert proof.reason_code == "verification_failed"


def test_missing_expected_artifact_fails_verification(tmp_path, monkeypatch):
    task = create_fixture_task_contract(
        task_id="cb025-missing-expected",
        base_fixture=(("seed.txt", b"seed\n"),),
        allowed_paths=("value.txt",),
        expected_artifacts=(("value.txt", b"2\n"),),
    )
    receipt, _ = _execute(tmp_path, monkeypatch)
    _, root = _stage(tmp_path, monkeypatch, {}, receipt=receipt)
    intake = intake_worker_artifacts(receipt, root)
    verification = verify_candidate(task, receipt, intake)

    assert verification.status == "verification_failed"
    assert verification.failure_codes == ("expected_artifact_missing",)


# 6. termination_uncertain blocks the proof.

def test_termination_uncertain_blocks_the_proof(tmp_path, monkeypatch):
    base, _ = _execute(tmp_path, monkeypatch)
    uncertain = _rebuild_receipt(
        base,
        lifecycle_states=(
            "prepared", "launching", "running", "termination_uncertain",
        ),
        final_state="termination_uncertain",
        exit_code=None,
        termination_uncertain=True,
    )
    _, _, decision, _, _, _, proof = _chain(
        tmp_path, monkeypatch, receipt=uncertain,
    )

    assert decision.receipt.final_classification == "termination_uncertain"
    assert proof.final_classification == "rejected_supervision"
    assert proof.reason_code == "termination_uncertain"
    assert proof.human_review_required is True


# 7. cleanup_uncertain blocks the proof.

def test_cleanup_uncertain_blocks_the_proof(tmp_path, monkeypatch):
    base, _ = _execute(tmp_path, monkeypatch)
    uncertain = _rebuild_receipt(base, cleanup_confirmed=False)
    _, _, decision, intake, _, _, proof = _chain(
        tmp_path, monkeypatch, receipt=uncertain,
    )

    assert intake.receipt.teardown_uncertain is True
    assert decision.receipt.final_classification == "cleanup_uncertain"
    assert proof.final_classification == "rejected_supervision"
    assert proof.reason_code == "cleanup_uncertain"


def test_failed_execution_is_rejected_as_runtime(tmp_path, monkeypatch):
    base, _ = _execute(tmp_path, monkeypatch)
    failed = _rebuild_receipt(
        base,
        lifecycle_states=("prepared", "launching", "running", "failed"),
        final_state="failed",
        exit_code=1,
    )
    _, _, decision, _, _, _, proof = _chain(
        tmp_path, monkeypatch, receipt=failed,
    )

    assert decision.receipt.final_classification == "failed"
    assert proof.final_classification == "rejected_runtime"
    assert proof.reason_code == "execution_failed"


# 8. Artifact security rejection blocks the proof.

def test_artifact_security_rejection_blocks_the_proof(tmp_path, monkeypatch):
    secret = {"value.txt": b"2\n", "leak.txt": b"api_key = abcdef0123456789\n"}
    _, _, decision, intake, blast, verification, proof = _chain(
        tmp_path, monkeypatch, secret,
    )

    assert intake.receipt.status == "rejected_secret_material"
    assert intake.quarantine_package is None
    assert blast is None and verification is None
    assert decision.receipt.final_classification == (
        "artifact_security_rejected"
    )
    assert proof.final_classification == "rejected_artifact_security"
    assert proof.quarantine_package_digest == ""


def test_rejected_artifacts_cannot_carry_downstream_evidence(
    tmp_path, monkeypatch,
):
    clean_task, clean_receipt, _, clean_intake, blast, _, _ = _chain(
        tmp_path, monkeypatch,
    )
    other = tmp_path / "second"
    other.mkdir()
    secret_receipt, _ = _execute(other, monkeypatch)
    _, root = _stage(
        other,
        monkeypatch,
        {"leak.txt": b"api_key = abcdef0123456789\n"},
        receipt=secret_receipt,
    )
    intake = intake_worker_artifacts(secret_receipt, root)
    decision = supervise_execution(
        secret_receipt,
        create_supervision_policy(),
        artifact_intake_receipt=intake.receipt,
    )

    with pytest.raises(TrustChainProofError):
        build_trust_chain_proof(
            clean_task, secret_receipt, decision, intake, blast, None,
        )


# 9. Stale or mismatched identity is rejected.

def test_downstream_evidence_from_another_execution_is_rejected(
    tmp_path, monkeypatch,
):
    task, receipt, decision, intake, blast, verification, _ = _chain(
        tmp_path, monkeypatch,
    )
    other = tmp_path / "other"
    other.mkdir()
    other_receipt, _ = _execute(other, monkeypatch)
    _, other_root = _stage(
        other, monkeypatch, CORRECT, receipt=other_receipt,
    )
    other_intake = intake_worker_artifacts(other_receipt, other_root)
    other_blast = evaluate_blast_radius(task, other_receipt, other_intake)
    other_verification = verify_candidate(task, other_receipt, other_intake)

    assert other_receipt.receipt_sha256 != receipt.receipt_sha256
    with pytest.raises(TrustChainProofError):
        build_trust_chain_proof(
            task, receipt, decision, intake, other_blast, verification,
        )
    with pytest.raises(TrustChainProofError):
        build_trust_chain_proof(
            task, receipt, decision, intake, blast, other_verification,
        )


def test_supervision_from_another_execution_is_rejected(
    tmp_path, monkeypatch,
):
    task, receipt, _, intake, blast, verification, _ = _chain(
        tmp_path, monkeypatch,
    )
    other = tmp_path / "other"
    other.mkdir()
    other_receipt, _ = _execute(other, monkeypatch)
    _, other_root = _stage(
        other, monkeypatch, CORRECT, receipt=other_receipt,
    )
    other_intake = intake_worker_artifacts(other_receipt, other_root)
    other_decision = supervise_execution(
        other_receipt,
        create_supervision_policy(),
        artifact_intake_receipt=other_intake.receipt,
    )

    with pytest.raises(TrustChainProofError):
        build_trust_chain_proof(
            task, receipt, other_decision, intake, blast, verification,
        )


def test_supervision_without_artifact_evidence_is_rejected(
    tmp_path, monkeypatch,
):
    task = create_increment_value_task()
    receipt, _ = _execute(tmp_path, monkeypatch)
    _, root = _stage(tmp_path, monkeypatch, CORRECT, receipt=receipt)
    intake = intake_worker_artifacts(receipt, root)
    blind = supervise_execution(receipt, create_supervision_policy())
    blast = evaluate_blast_radius(task, receipt, intake)
    verification = verify_candidate(task, receipt, intake)

    assert blind.receipt.artifact_intake_receipt_digest == ""
    with pytest.raises(TrustChainProofError):
        build_trust_chain_proof(
            task, receipt, blind, intake, blast, verification,
        )


def test_blast_radius_rejects_a_quarantine_from_another_execution(
    tmp_path, monkeypatch,
):
    task = create_increment_value_task()
    receipt, _ = _execute(tmp_path, monkeypatch)
    other = tmp_path / "other"
    other.mkdir()
    other_receipt, _ = _execute(other, monkeypatch)
    _, other_root = _stage(
        other, monkeypatch, CORRECT, receipt=other_receipt,
    )
    other_intake = intake_worker_artifacts(other_receipt, other_root)

    with pytest.raises(BlastRadiusError):
        evaluate_blast_radius(task, receipt, other_intake)
    with pytest.raises(CandidateVerificationError):
        verify_candidate(task, receipt, other_intake)


# 10. Forged evidence is rejected.

def test_forged_blast_radius_receipt_is_rejected(tmp_path, monkeypatch):
    task, receipt, decision, intake, blast, verification, _ = _chain(
        tmp_path, monkeypatch, CHEATING,
    )
    forged = _forge(
        blast, status="within_blast_radius_unverified", violations=(),
    )

    assert blast.status == "blast_radius_rejected"
    with pytest.raises(TrustChainProofError):
        build_trust_chain_proof(
            task, receipt, decision, intake, forged, verification,
        )


def test_forged_verification_receipt_is_rejected(tmp_path, monkeypatch):
    task, receipt, decision, intake, blast, verification, _ = _chain(
        tmp_path, monkeypatch, WRONG,
    )
    forged = _forge(
        verification, status="verification_passed", failure_codes=(),
    )

    with pytest.raises(TrustChainProofError):
        build_trust_chain_proof(
            task, receipt, decision, intake, blast, forged,
        )


def test_evidence_cannot_be_constructed_without_the_trusted_factory():
    with pytest.raises(BlastRadiusError):
        BlastRadiusReceipt(
            task_sha256="0" * 64,
            allowed_paths_sha256="0" * 64,
            max_artifact_count=1,
            execution_receipt_digest="0" * 64,
            attempt_id="attempt-1",
            execution_id="execution-1",
            request_digest="0" * 64,
            policy_digest="0" * 64,
            materialization_receipt_digest="0" * 64,
            workspace_identity="0" * 64,
            artifact_intake_receipt_digest="0" * 64,
            quarantine_package_digest="0" * 64,
            inventory_sha256="0" * 64,
            observed_artifact_count=1,
            observed_total_bytes=2,
            observed_paths_sha256="0" * 64,
            status="within_blast_radius_unverified",
            violations=(),
            receipt_sha256="0" * 64,
        )
    with pytest.raises(CandidateVerificationError):
        CandidateVerificationReceipt(
            task_sha256="0" * 64,
            acceptance_rule_sha256="0" * 64,
            base_fixture_sha256="0" * 64,
            execution_receipt_digest="0" * 64,
            attempt_id="attempt-1",
            execution_id="execution-1",
            request_digest="0" * 64,
            materialization_receipt_digest="0" * 64,
            artifact_intake_receipt_digest="0" * 64,
            quarantine_package_digest="0" * 64,
            inventory_sha256="0" * 64,
            candidate_tree_sha256="0" * 64,
            verified_path_count=1,
            status="verification_passed",
            failure_codes=(),
            receipt_sha256="0" * 64,
        )
    with pytest.raises(TrustChainProofError):
        TrustChainProofReceipt(
            task_id="cb025",
            task_sha256="0" * 64,
            acceptance_rule_sha256="0" * 64,
            pinned_base_sha="0" * 64,
            attempt_id="attempt-1",
            execution_id="execution-1",
            request_digest="0" * 64,
            policy_digest="0" * 64,
            materialization_receipt_digest="0" * 64,
            workspace_identity="0" * 64,
            execution_receipt_digest="0" * 64,
            supervision_receipt_digest="0" * 64,
            circuit_breaker_snapshot_digest="0" * 64,
            artifact_intake_receipt_digest="0" * 64,
            quarantine_package_digest="0" * 64,
            blast_radius_receipt_digest="0" * 64,
            verification_receipt_digest="0" * 64,
            supervision_classification="succeeded",
            artifact_intake_status="quarantined_untrusted",
            blast_radius_status="within_blast_radius_unverified",
            verification_status="verification_passed",
            final_classification="contained_verified_candidate",
            reason_code="contained_trust_chain_survived",
            known_limitations=("artifact_intake_ordering_unproven",),
            proof_sha256="0" * 64,
        )


def test_forged_task_contract_is_rejected(tmp_path, monkeypatch):
    receipt, _ = _execute(tmp_path, monkeypatch)
    _, root = _stage(tmp_path, monkeypatch, CORRECT, receipt=receipt)
    intake = intake_worker_artifacts(receipt, root)
    forged = _forge(
        create_increment_value_task(), allowed_paths=("value.txt", "any.txt"),
    )

    with pytest.raises(BlastRadiusError):
        evaluate_blast_radius(forged, receipt, intake)
    with pytest.raises(CandidateVerificationError):
        verify_candidate(forged, receipt, intake)


# 11. Every evidence object is immutable.

def test_every_evidence_object_is_immutable_and_bounded(
    tmp_path, monkeypatch,
):
    task, _, _, _, blast, verification, proof = _chain(tmp_path, monkeypatch)

    for instance, attribute, value in (
        (task, "task_id", "other"),
        (blast, "status", "within_blast_radius_unverified"),
        (verification, "status", "verification_passed"),
        (proof, "final_classification", "contained_verified_candidate"),
        (proof, "merge_authorized", True),
    ):
        with pytest.raises(FrozenInstanceError):
            setattr(instance, attribute, value)

    assert len(task.canonical_bytes()) <= 16384
    assert len(blast.canonical_bytes()) <= blast_radius.MAX_RECEIPT_BYTES
    assert len(verification.canonical_bytes()) <= (
        candidate_verifier.MAX_RECEIPT_BYTES
    )
    assert len(proof.canonical_bytes()) <= (
        trust_chain_proof.MAX_RECEIPT_BYTES
    )


# 12. No proof of any classification holds authority whatsoever.

def test_no_proof_holds_merge_or_publication_authority(
    tmp_path, monkeypatch,
):
    _, _, _, _, blast, verification, proof = _chain(tmp_path, monkeypatch)

    assert proof.human_review_required is True
    assert proof.result_trusted is False
    assert proof.worker_output_trusted is False
    assert proof.externally_verified is False
    assert proof.publication_authorized is False
    assert proof.queue_transition_authorized is False
    assert proof.github_authorized is False
    assert proof.merge_authorized is False
    assert proof.main_advancement_authorized is False
    for receipt in (blast, verification):
        assert receipt.publication_authorized is False
        assert receipt.queue_transition_authorized is False
        assert receipt.github_authorized is False
        assert receipt.merge_authorized is False


def test_proof_records_the_unproven_artifact_ordering_honestly(
    tmp_path, monkeypatch,
):
    _, _, _, intake, _, _, proof = _chain(tmp_path, monkeypatch)

    # CB-023 cannot yet prove intake precedes destructive teardown, and the
    # proof must carry that limitation rather than paper over it.
    assert intake.receipt.\
        artifact_intake_completed_before_destructive_teardown is False
    assert proof.artifact_intake_ordering_proven is False
    assert proof.artifact_content_provenance_proven is False
    assert "artifact_intake_ordering_unproven" in proof.known_limitations
    assert "fixture_scoped_acceptance_rule" in proof.known_limitations


# 13. Proofs are deterministic and content-addressed.

def test_proof_is_deterministic_and_content_addressed(tmp_path, monkeypatch):
    task, receipt, decision, intake, blast, verification, proof = _chain(
        tmp_path, monkeypatch,
    )

    # The same evidence always yields byte-identical, self-describing proof.
    replayed = build_trust_chain_proof(
        task, receipt, decision, intake, blast, verification
    )
    assert replayed.proof_sha256 == proof.proof_sha256
    assert replayed.canonical_bytes() == proof.canonical_bytes()
    assert proof.proof_sha256 == hashlib.sha256(
        proof._payload()
    ).hexdigest()
    for evidence in (blast, verification):
        assert evidence.receipt_sha256 == hashlib.sha256(
            evidence._payload()
        ).hexdigest()

    # Different admitted bytes yield a different proof identity.
    diverged_root = tmp_path / "diverged"
    diverged_root.mkdir()
    diverged = _chain(diverged_root, monkeypatch, WRONG)[-1]
    assert diverged.proof_sha256 != proof.proof_sha256
    assert diverged.final_classification != proof.final_classification


def test_task_contract_rejects_unsafe_or_forbidden_boundaries():
    for allowed in (("../escape.txt",), ("/abs.txt",), (".git/config",)):
        with pytest.raises(ProofFixtureError):
            create_fixture_task_contract(
                task_id="cb025-unsafe",
                base_fixture=(("value.txt", b"1\n"),),
                allowed_paths=allowed,
                expected_artifacts=(("value.txt", b"2\n"),),
            )
    with pytest.raises(ProofFixtureError):
        create_fixture_task_contract(
            task_id="cb025-outside",
            base_fixture=(("value.txt", b"1\n"),),
            allowed_paths=("value.txt",),
            expected_artifacts=(("elsewhere.txt", b"2\n"),),
        )


# 14. The new modules hold no execution, network, GitHub, or DB authority.

@pytest.mark.parametrize("module", [
    "backend/continuous_builder/blast_radius.py",
    "backend/continuous_builder/candidate_verifier.py",
    "backend/continuous_builder/proof_fixture.py",
    "backend/continuous_builder/trust_chain_proof.py",
])
def test_cb025_modules_have_no_execution_network_db_or_github_authority(
    module,
):
    source = Path(module).read_text(encoding="utf-8")
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
        "podman", "kubernetes", "paramiko", "fabric", "pexpect", "sqlite3",
        "sqlalchemy", "github", "shutil", "tempfile",
    }
    for forbidden in (
        "os.system", "shell=True", "subprocess.run", "merge_pull_request",
        "open(",
    ):
        assert forbidden not in source


def test_verifier_never_reads_a_worker_authored_output_channel():
    source = Path(
        "backend/continuous_builder/candidate_verifier.py"
    ).read_text(encoding="utf-8")
    tree = ast.parse(source)
    attributes = {
        node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)
    }
    assert not attributes & {
        "stdout_sample", "stdout_sha256", "stdout_size",
        "stderr_sample", "stderr_sha256", "stderr_size",
        "container_id", "lifecycle_states",
    }
    assert "worker_workspace_reused" in source


def test_proof_independently_rederives_downstream_evidence(
    tmp_path, monkeypatch,
):
    task, receipt, decision, intake, blast, verification, _ = _chain(
        tmp_path, monkeypatch, WRONG,
    )
    # A forged receipt whose own internal digest is recomputed and therefore
    # self-consistent still cannot pass: the proof re-derives both gates from
    # the quarantine package and compares digests.
    passing = _forge(
        verification, status="verification_passed", failure_codes=(),
    )
    object.__setattr__(
        passing,
        "receipt_sha256",
        hashlib.sha256(passing._payload()).hexdigest(),
    )
    assert dataclasses.replace(passing).status == "verification_passed"

    with pytest.raises(TrustChainProofError):
        build_trust_chain_proof(
            task, receipt, decision, intake, blast, passing,
        )


def _reseal(proof, **changes):
    """Rebuild a proof receipt bypassing the factory, with a valid digest."""
    forged = _forge(proof, **changes)
    object.__setattr__(
        forged, "proof_sha256", hashlib.sha256(forged._payload()).hexdigest()
    )
    return forged


def test_accepted_classification_is_invalid_without_proven_provenance(
    tmp_path, monkeypatch,
):
    _, _, _, _, blast, verification, proof = _chain(tmp_path, monkeypatch)

    # Every stage status on this receipt already says "pass", so the only
    # thing standing between it and the accepted classification is provenance.
    assert proof.supervision_classification == "succeeded"
    assert proof.artifact_intake_status == "quarantined_untrusted"
    assert proof.blast_radius_status == blast.status == (
        "within_blast_radius_unverified"
    )
    assert proof.verification_status == verification.status == (
        "verification_passed"
    )
    assert proof.artifact_content_provenance_proven is False

    # Relabelling it accepted -- with a recomputed, self-consistent digest, so
    # no digest check can catch it -- is rejected by the receipt invariant
    # itself, not merely by the classifier that would never have emitted it.
    accepted = _reseal(
        proof, final_classification="contained_verified_candidate",
    )
    with pytest.raises(TrustChainProofError):
        dataclasses.replace(accepted)

    # Positive control: the same relabelling validates once provenance is
    # proven, which shows the invariant above turns on provenance and not on
    # some unrelated field. Nothing in the shipped pipeline can reach here --
    # CB-023 hard-codes the ordering flag false -- so this state is
    # constructed only to pin down what the invariant is testing.
    provable = _reseal(
        proof,
        final_classification="contained_verified_candidate",
        artifact_intake_ordering_proven=True,
        artifact_content_provenance_proven=True,
        known_limitations=("fixture_scoped_acceptance_rule",),
    )
    assert dataclasses.replace(provable).final_classification == (
        "contained_verified_candidate"
    )

    # And one flag alone is never enough.
    for changes in (
        {"artifact_intake_ordering_proven": True},
        {"artifact_content_provenance_proven": True},
    ):
        half = _reseal(
            proof,
            final_classification="contained_verified_candidate",
            **changes,
        )
        with pytest.raises(TrustChainProofError):
            dataclasses.replace(half)


def test_build_refuses_to_emit_accepted_while_provenance_is_unproven(
    tmp_path, monkeypatch,
):
    # The classifier and the invariant agree: across the whole fixture chain
    # the accepted state is simply not reachable on this architecture.
    for index, files in enumerate((CORRECT, WRONG, CHEATING)):
        root = tmp_path / f"case-{index}"
        root.mkdir(parents=True)
        proof = _chain(root, monkeypatch, files)[-1]
        assert proof.final_classification != "contained_verified_candidate"
        assert proof.artifact_content_provenance_proven is False
