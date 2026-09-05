"""CB-025 immutable trust-chain proof receipt.

One bounded, content-addressed object that binds a single tiny candidate to
every piece of trusted, system-side evidence produced about it:

    CB-022 contained execution receipt
      -> CB-024 supervision receipt and circuit-breaker snapshot
      -> CB-023 artifact intake receipt and quarantine package
      -> CB-025A optional stdout artifact-provenance receipt
      -> CB-025 blast-radius receipt
      -> CB-025 independent verification receipt
      -> this proof
      -> human review

Nothing here executes, publishes, merges, advances a queue, touches GitHub,
opens a network socket, or reads a database. It does not trust worker-authored
text: every worker-proposed byte must first be bound to trusted supervisor
capture evidence, then pass the existing artifact intake and verification
boundaries.

The best possible outcome is ``contained_verified_candidate``, which means
only: *this candidate survived this bounded trust chain*. Even that carries
``human_review_required=True`` and ``result_trusted=False``, and it never
authorizes merge, publication, queue transition, GitHub action, or Main
advancement.

Artifact provenance is a precondition of that outcome, not a footnote on it.
The legacy CB-023 path reports
``artifact_intake_completed_before_destructive_teardown=False`` because it can
only observe a supervisor staging root after execution. CB-025A adds a second,
explicit route: a strict bounded stdout envelope whose complete bytes are
already captured and hashed inside the trusted CB-022 execution receipt. The
artifact-output bridge proves that the exact bytes staged into CB-023 came from
that exact execution stdout. In that route, provenance is established without
pretending the worker workspace survived teardown or adding a writable host
mount.

The accepted-state provenance rule is enforced twice. The classifier fails
closed when provenance is absent, and ``TrustChainProofReceipt.__post_init__``
independently refuses to construct ``contained_verified_candidate`` unless
both provenance booleans are ``True``. A caller, forged receipt, or future
classifier therefore cannot mint an accepted state without explicit trusted
provenance evidence.
"""

import hashlib
import json
import re
from dataclasses import dataclass, field, replace

from .artifact_output import (
    ArtifactOutputError,
    ArtifactOutputProvenanceReceipt,
)
from .blast_radius import (
    STATUS_WITHIN,
    BlastRadiusError,
    BlastRadiusReceipt,
    evaluate_blast_radius,
)
from .candidate_verifier import (
    STATUS_PASSED,
    CandidateVerificationError,
    CandidateVerificationReceipt,
    verify_candidate,
)
from .proof_fixture import FixtureTaskContract, ProofFixtureError
from .supervisor import SupervisionDecision, SupervisorError
from .text_safety import utf8_length
from .worker_artifact import ArtifactIntakeResult, WorkerArtifactError
from .worker_runtime import WorkerExecutionReceipt, WorkerRuntimeError


class TrustChainProofError(ValueError):
    """Raised when a trust-chain proof cannot be safely produced."""


POLICY_VERSION = "cb-trust-chain-proof-v1"
MAX_RECEIPT_BYTES = 64 * 1024
MAX_LIMITATIONS = 16
MAX_REASON_BYTES = 256
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_IDENTITY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@-]{0,255}$")
_GIT_SHA = re.compile(r"^[0-9a-f]{40}$")
_PROOF_TOKEN = object()

CLASSIFICATION_ACCEPTED = "contained_verified_candidate"
CLASSIFICATIONS = (
    CLASSIFICATION_ACCEPTED,
    "rejected_runtime",
    "rejected_supervision",
    "rejected_artifact_security",
    "rejected_blast_radius",
    "rejected_verification",
    "rejected_uncertain_state",
)
LIMITATION_CODES = frozenset({
    "artifact_intake_ordering_unproven",
    "fixture_scoped_acceptance_rule",
})
_SUPERVISION_REJECTION = {
    "termination_uncertain": ("rejected_supervision", "termination_uncertain"),
    "cleanup_uncertain": ("rejected_supervision", "cleanup_uncertain"),
    "containment_violation": (
        "rejected_supervision", "containment_violation",
    ),
    "artifact_security_rejected": (
        "rejected_artifact_security", "artifact_security_rejected",
    ),
    "failed": ("rejected_runtime", "execution_failed"),
    "crashed": ("rejected_runtime", "execution_crashed"),
    "timed_out": ("rejected_runtime", "execution_timed_out"),
    "stalled": ("rejected_runtime", "execution_stalled"),
    "cancelled": ("rejected_runtime", "execution_cancelled"),
    "unknown_failure": ("rejected_uncertain_state", "unknown_failure"),
}


def _canonical(value):
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")


def _digest(value):
    return hashlib.sha256(value).hexdigest()


def _sha256(value, name):
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise TrustChainProofError(f"{name} is malformed")


def _identity(value, name):
    if not isinstance(value, str) or _IDENTITY.fullmatch(value or "") is None:
        raise TrustChainProofError(f"{name} is malformed")


def _revalidate(instance, error_types, label):
    try:
        replace(instance)
    except error_types as error:
        raise TrustChainProofError(
            f"{label} failed authoritative validation"
        ) from error


@dataclass(frozen=True)
class TrustChainProofReceipt:
    """Immutable, content-addressed CB-025 proof over one candidate."""

    task_id: str
    task_sha256: str
    acceptance_rule_sha256: str
    pinned_base_sha: str
    attempt_id: str
    execution_id: str
    request_digest: str
    policy_digest: str
    materialization_receipt_digest: str
    workspace_identity: str
    execution_receipt_digest: str
    supervision_receipt_digest: str
    circuit_breaker_snapshot_digest: str
    artifact_intake_receipt_digest: str
    quarantine_package_digest: str
    blast_radius_receipt_digest: str
    verification_receipt_digest: str
    supervision_classification: str
    artifact_intake_status: str
    blast_radius_status: str
    verification_status: str
    final_classification: str
    reason_code: str
    known_limitations: tuple
    proof_sha256: str
    artifact_provenance_receipt_digest: str = ""
    policy_version: str = POLICY_VERSION
    artifact_intake_ordering_proven: bool = False
    artifact_content_provenance_proven: bool = False
    human_review_required: bool = True
    result_trusted: bool = False
    worker_output_trusted: bool = False
    externally_verified: bool = False
    publication_authorized: bool = False
    queue_transition_authorized: bool = False
    github_authorized: bool = False
    merge_authorized: bool = False
    main_advancement_authorized: bool = False
    _proof_token: object = field(default=None, repr=False, compare=False)

    def __post_init__(self):
        if self._proof_token is not _PROOF_TOKEN:
            raise TrustChainProofError(
                "trust-chain proof requires trusted derived evidence"
            )
        if self.policy_version != POLICY_VERSION:
            raise TrustChainProofError("trust-chain policy is unsupported")
        _identity(self.attempt_id, "attempt ID")
        _identity(self.execution_id, "execution ID")
        if not isinstance(self.task_id, str) or not self.task_id or (
            utf8_length(self.task_id) > 128
        ):
            raise TrustChainProofError("task ID is malformed")
        for name in (
            "task_sha256", "acceptance_rule_sha256",
            "request_digest", "policy_digest",
            "materialization_receipt_digest", "workspace_identity",
            "execution_receipt_digest", "supervision_receipt_digest",
            "circuit_breaker_snapshot_digest",
            "artifact_intake_receipt_digest",
            "blast_radius_receipt_digest", "verification_receipt_digest",
            "proof_sha256",
        ):
            _sha256(getattr(self, name), name)
        if self.artifact_provenance_receipt_digest:
            _sha256(
                self.artifact_provenance_receipt_digest,
                "artifact provenance receipt digest",
            )
        if not isinstance(self.pinned_base_sha, str) or _GIT_SHA.fullmatch(
            self.pinned_base_sha or ""
        ) is None:
            raise TrustChainProofError("pinned base SHA is malformed")
        if self.quarantine_package_digest:
            _sha256(self.quarantine_package_digest, "quarantine digest")
        if self.final_classification not in CLASSIFICATIONS:
            raise TrustChainProofError("proof classification is malformed")
        if not isinstance(self.reason_code, str) or not self.reason_code or (
            utf8_length(self.reason_code) > MAX_REASON_BYTES
        ):
            raise TrustChainProofError("proof reason code is malformed")
        if type(self.known_limitations) is not tuple or len(
            self.known_limitations
        ) > MAX_LIMITATIONS or any(
            code not in LIMITATION_CODES for code in self.known_limitations
        ):
            raise TrustChainProofError("proof limitations are malformed")
        if self.known_limitations != tuple(
            sorted(set(self.known_limitations))
        ):
            raise TrustChainProofError("proof limitations are not canonical")
        if self.artifact_intake_ordering_proven is not (
            self.artifact_content_provenance_proven
        ):
            raise TrustChainProofError("provenance evidence is contradictory")
        if self.artifact_content_provenance_proven is False and (
            "artifact_intake_ordering_unproven" not in self.known_limitations
        ):
            raise TrustChainProofError(
                "unproven artifact provenance must be recorded as a limitation"
            )
        if self.artifact_content_provenance_proven is True and (
            "artifact_intake_ordering_unproven" in self.known_limitations
        ):
            raise TrustChainProofError(
                "proven artifact provenance contradicts ordering limitation"
            )
        if self.human_review_required is not True or any(
            value is not False
            for value in (
                self.result_trusted,
                self.worker_output_trusted,
                self.externally_verified,
                self.publication_authorized,
                self.queue_transition_authorized,
                self.github_authorized,
                self.merge_authorized,
                self.main_advancement_authorized,
            )
        ):
            raise TrustChainProofError("trust-chain proof promotes authority")
        if self.final_classification == CLASSIFICATION_ACCEPTED and (
            self.supervision_classification != "succeeded"
            or self.artifact_intake_status != "quarantined_untrusted"
            or self.blast_radius_status != STATUS_WITHIN
            or self.verification_status != STATUS_PASSED
        ):
            raise TrustChainProofError(
                "accepted proof contradicts its own stage evidence"
            )
        if self.final_classification == CLASSIFICATION_ACCEPTED and (
            self.artifact_intake_ordering_proven is not True
            or self.artifact_content_provenance_proven is not True
            or not self.artifact_provenance_receipt_digest
        ):
            raise TrustChainProofError(
                "accepted proof requires proven artifact content provenance"
            )
        if self.proof_sha256 != _digest(self._payload()):
            raise TrustChainProofError("trust-chain proof digest mismatch")
        if len(self.canonical_bytes()) > MAX_RECEIPT_BYTES:
            raise TrustChainProofError("trust-chain proof exceeds byte bound")

    def _body(self):
        return {
            "acceptance_rule_sha256": self.acceptance_rule_sha256,
            "artifact_content_provenance_proven": (
                self.artifact_content_provenance_proven
            ),
            "artifact_intake_ordering_proven": (
                self.artifact_intake_ordering_proven
            ),
            "artifact_intake_receipt_digest": (
                self.artifact_intake_receipt_digest
            ),
            "artifact_intake_status": self.artifact_intake_status,
            "artifact_provenance_receipt_digest": (
                self.artifact_provenance_receipt_digest
            ),
            "attempt_id": self.attempt_id,
            "blast_radius_receipt_digest": self.blast_radius_receipt_digest,
            "blast_radius_status": self.blast_radius_status,
            "circuit_breaker_snapshot_digest": (
                self.circuit_breaker_snapshot_digest
            ),
            "execution_id": self.execution_id,
            "execution_receipt_digest": self.execution_receipt_digest,
            "externally_verified": False,
            "final_classification": self.final_classification,
            "github_authorized": False,
            "human_review_required": True,
            "known_limitations": list(self.known_limitations),
            "main_advancement_authorized": False,
            "materialization_receipt_digest": (
                self.materialization_receipt_digest
            ),
            "merge_authorized": False,
            "pinned_base_sha": self.pinned_base_sha,
            "policy_digest": self.policy_digest,
            "policy_version": POLICY_VERSION,
            "publication_authorized": False,
            "quarantine_package_digest": self.quarantine_package_digest,
            "queue_transition_authorized": False,
            "reason_code": self.reason_code,
            "request_digest": self.request_digest,
            "result_trusted": False,
            "supervision_classification": self.supervision_classification,
            "supervision_receipt_digest": self.supervision_receipt_digest,
            "task_id": self.task_id,
            "task_sha256": self.task_sha256,
            "verification_receipt_digest": self.verification_receipt_digest,
            "verification_status": self.verification_status,
            "worker_output_trusted": False,
            "workspace_identity": self.workspace_identity,
        }

    def _payload(self):
        return _canonical(self._body())

    def canonical_bytes(self):
        value = self._body()
        value["proof_sha256"] = self.proof_sha256
        return _canonical(value)


def _validate_inputs(
    task,
    execution_receipt,
    supervision_decision,
    intake_result,
    blast_radius_receipt,
    verification_receipt,
    artifact_provenance_receipt,
):
    if not isinstance(task, FixtureTaskContract):
        raise TrustChainProofError("fixture task contract is invalid")
    _revalidate(task, ProofFixtureError, "fixture task contract")

    if not isinstance(execution_receipt, WorkerExecutionReceipt):
        raise TrustChainProofError("worker execution receipt is invalid")
    _revalidate(
        execution_receipt.materialization_receipt,
        WorkerRuntimeError,
        "materialization receipt",
    )
    _revalidate(
        execution_receipt.enforcement_evidence,
        WorkerRuntimeError,
        "runtime enforcement evidence",
    )
    _revalidate(
        execution_receipt, WorkerRuntimeError, "worker execution receipt"
    )
    if execution_receipt.execution_performed is not True or any(
        value is not False
        for value in (
            execution_receipt.worker_output_trusted,
            execution_receipt.result_verified,
            execution_receipt.patch_verified,
            execution_receipt.externally_verified,
            execution_receipt.publication_authorized,
            execution_receipt.queue_transition_authorized,
            execution_receipt.github_authorized,
        )
    ):
        raise TrustChainProofError("execution receipt overstates authority")

    if not isinstance(supervision_decision, SupervisionDecision):
        raise TrustChainProofError("supervision decision is invalid")
    _revalidate(supervision_decision, SupervisorError, "supervision decision")
    supervision = supervision_decision.receipt
    breaker = supervision_decision.circuit_breaker
    _revalidate(supervision, SupervisorError, "supervision receipt")
    _revalidate(breaker, SupervisorError, "circuit breaker snapshot")

    if not isinstance(intake_result, ArtifactIntakeResult):
        raise TrustChainProofError("artifact intake result is invalid")
    intake = intake_result.receipt
    package = intake_result.quarantine_package
    _revalidate(intake, WorkerArtifactError, "artifact intake receipt")
    if package is not None:
        _revalidate(package, WorkerArtifactError, "quarantine package")

    execution_bindings = (
        (supervision.execution_receipt_digest, "supervision execution digest"),
        (intake.execution_receipt_digest, "artifact execution digest"),
    )
    for actual, label in execution_bindings:
        if actual != execution_receipt.receipt_sha256:
            raise TrustChainProofError(f"{label} does not bind this execution")
    identity = (
        (supervision.attempt_id, execution_receipt.attempt_id),
        (supervision.execution_id, execution_receipt.execution_id),
        (supervision.request_digest, execution_receipt.request_digest),
        (supervision.runtime_policy_digest, execution_receipt.policy_digest),
        (intake.attempt_id, execution_receipt.attempt_id),
        (intake.execution_id, execution_receipt.execution_id),
        (intake.request_digest, execution_receipt.request_digest),
        (intake.policy_digest, execution_receipt.policy_digest),
        (
            intake.materialization_receipt_digest,
            execution_receipt.materialization_receipt_digest,
        ),
        (
            intake.workspace_identity,
            execution_receipt.materialization_receipt.workspace_instance_digest,
        ),
    )
    if any(actual != wanted for actual, wanted in identity):
        raise TrustChainProofError("trust-chain identity binding mismatch")
    if supervision.artifact_intake_receipt_digest != intake.receipt_sha256:
        raise TrustChainProofError(
            "supervision did not observe this artifact intake receipt"
        )
    if intake.quarantine_package_digest != (
        package.package_sha256 if package is not None else ""
    ):
        raise TrustChainProofError("quarantine package binding mismatch")

    if artifact_provenance_receipt is not None:
        if not isinstance(
            artifact_provenance_receipt, ArtifactOutputProvenanceReceipt
        ):
            raise TrustChainProofError("artifact provenance receipt is invalid")
        _revalidate(
            artifact_provenance_receipt,
            ArtifactOutputError,
            "artifact provenance receipt",
        )
        provenance_bindings = (
            (
                artifact_provenance_receipt.execution_receipt_digest,
                execution_receipt.receipt_sha256,
            ),
            (
                artifact_provenance_receipt.execution_id,
                execution_receipt.execution_id,
            ),
            (
                artifact_provenance_receipt.container_id,
                execution_receipt.container_id,
            ),
            (
                artifact_provenance_receipt.attempt_id,
                execution_receipt.attempt_id,
            ),
            (
                artifact_provenance_receipt.request_digest,
                execution_receipt.request_digest,
            ),
            (
                artifact_provenance_receipt.policy_digest,
                execution_receipt.policy_digest,
            ),
            (
                artifact_provenance_receipt.stdout_sha256,
                execution_receipt.stdout_sha256,
            ),
            (
                artifact_provenance_receipt.stdout_size,
                execution_receipt.stdout_size,
            ),
            (
                artifact_provenance_receipt.intake_receipt_digest,
                intake.receipt_sha256,
            ),
            (
                artifact_provenance_receipt.quarantine_package_digest,
                package.package_sha256 if package is not None else "",
            ),
        )
        if any(actual != wanted for actual, wanted in provenance_bindings):
            raise TrustChainProofError("artifact provenance binding mismatch")
        if (
            artifact_provenance_receipt.artifact_content_provenance_proven
            is not True
            or artifact_provenance_receipt.worker_output_trusted is not False
            or artifact_provenance_receipt.result_verified is not False
            or artifact_provenance_receipt.merge_authorized is not False
        ):
            raise TrustChainProofError("artifact provenance overstates authority")

    if package is None:
        if blast_radius_receipt is not None or verification_receipt is not None:
            raise TrustChainProofError(
                "rejected artifacts must not carry downstream evidence"
            )
        return supervision, breaker, intake, package

    if not isinstance(blast_radius_receipt, BlastRadiusReceipt):
        raise TrustChainProofError("blast-radius receipt is invalid")
    _revalidate(blast_radius_receipt, BlastRadiusError, "blast-radius receipt")
    if not isinstance(verification_receipt, CandidateVerificationReceipt):
        raise TrustChainProofError("verification receipt is invalid")
    _revalidate(
        verification_receipt,
        CandidateVerificationError,
        "verification receipt",
    )
    downstream = (
        (blast_radius_receipt.task_sha256, task.task_sha256),
        (blast_radius_receipt.allowed_paths_sha256, task.allowed_paths_sha256),
        (
            blast_radius_receipt.execution_receipt_digest,
            execution_receipt.receipt_sha256,
        ),
        (blast_radius_receipt.attempt_id, execution_receipt.attempt_id),
        (blast_radius_receipt.execution_id, execution_receipt.execution_id),
        (
            blast_radius_receipt.artifact_intake_receipt_digest,
            intake.receipt_sha256,
        ),
        (
            blast_radius_receipt.quarantine_package_digest,
            package.package_sha256,
        ),
        (blast_radius_receipt.inventory_sha256, package.inventory_sha256),
        (verification_receipt.task_sha256, task.task_sha256),
        (
            verification_receipt.acceptance_rule_sha256,
            task.acceptance_rule_sha256,
        ),
        (
            verification_receipt.base_fixture_sha256,
            task.base_fixture_sha256,
        ),
        (
            verification_receipt.execution_receipt_digest,
            execution_receipt.receipt_sha256,
        ),
        (verification_receipt.attempt_id, execution_receipt.attempt_id),
        (verification_receipt.execution_id, execution_receipt.execution_id),
        (
            verification_receipt.artifact_intake_receipt_digest,
            intake.receipt_sha256,
        ),
        (
            verification_receipt.quarantine_package_digest,
            package.package_sha256,
        ),
        (verification_receipt.inventory_sha256, package.inventory_sha256),
    )
    if any(actual != wanted for actual, wanted in downstream):
        raise TrustChainProofError("downstream evidence binding mismatch")

    try:
        recomputed_blast = evaluate_blast_radius(
            task, execution_receipt, intake_result
        )
    except BlastRadiusError as error:
        raise TrustChainProofError(
            "blast-radius evidence could not be independently re-derived"
        ) from error
    try:
        recomputed_verification = verify_candidate(
            task, execution_receipt, intake_result
        )
    except CandidateVerificationError as error:
        raise TrustChainProofError(
            "verification evidence could not be independently re-derived"
        ) from error
    if blast_radius_receipt.receipt_sha256 != recomputed_blast.receipt_sha256:
        raise TrustChainProofError(
            "blast-radius receipt does not match independent re-derivation"
        )
    if verification_receipt.receipt_sha256 != (
        recomputed_verification.receipt_sha256
    ):
        raise TrustChainProofError(
            "verification receipt does not match independent re-derivation"
        )
    return supervision, breaker, intake, package


def _classify(
    supervision, breaker, intake, blast, verification, provenance_proven,
):
    classification = supervision.final_classification
    if classification != "succeeded":
        return _SUPERVISION_REJECTION.get(
            classification, ("rejected_uncertain_state", "unclassified_state")
        )
    if (
        supervision.termination_uncertain
        or supervision.cleanup_uncertain
        or not supervision.termination_confirmed
        or not supervision.cleanup_confirmed
    ):
        return "rejected_supervision", "supervision_uncertainty"
    if supervision.circuit_breaker_state != "closed" or breaker.state != "closed":
        return "rejected_supervision", "circuit_breaker_open"
    if intake.status != "quarantined_untrusted" or not intake.scan_passed:
        return "rejected_artifact_security", "artifact_security_rejected"
    if blast is None or verification is None:
        return "rejected_uncertain_state", "downstream_evidence_missing"
    if blast.status != STATUS_WITHIN:
        return "rejected_blast_radius", "blast_radius_rejected"
    if verification.status != STATUS_PASSED:
        return "rejected_verification", "verification_failed"
    if not provenance_proven:
        return "rejected_uncertain_state", "artifact_provenance_unproven"
    return CLASSIFICATION_ACCEPTED, "contained_trust_chain_survived"


def build_trust_chain_proof(
    task,
    execution_receipt,
    supervision_decision,
    intake_result,
    blast_radius_receipt=None,
    verification_receipt=None,
    artifact_provenance_receipt=None,
):
    """Bind one candidate's whole evidence chain into an immutable proof."""
    supervision, breaker, intake, package = _validate_inputs(
        task,
        execution_receipt,
        supervision_decision,
        intake_result,
        blast_radius_receipt,
        verification_receipt,
        artifact_provenance_receipt,
    )
    legacy_ordering_proven = bool(
        intake.artifact_intake_completed_before_destructive_teardown
    )
    stdout_provenance = bool(
        artifact_provenance_receipt is not None
        and artifact_provenance_receipt.artifact_content_provenance_proven
    )
    provenance_proven = legacy_ordering_proven or stdout_provenance
    classification, reason = _classify(
        supervision,
        breaker,
        intake,
        blast_radius_receipt,
        verification_receipt,
        provenance_proven,
    )
    limitations = {"fixture_scoped_acceptance_rule"}
    if not provenance_proven:
        limitations.add("artifact_intake_ordering_unproven")
    values = {
        "task_id": task.task_id,
        "task_sha256": task.task_sha256,
        "acceptance_rule_sha256": task.acceptance_rule_sha256,
        "pinned_base_sha": execution_receipt.materialization_receipt.pinned_base_sha,
        "attempt_id": execution_receipt.attempt_id,
        "execution_id": execution_receipt.execution_id,
        "request_digest": execution_receipt.request_digest,
        "policy_digest": execution_receipt.policy_digest,
        "materialization_receipt_digest": (
            execution_receipt.materialization_receipt_digest
        ),
        "workspace_identity": (
            execution_receipt.materialization_receipt.workspace_instance_digest
        ),
        "execution_receipt_digest": execution_receipt.receipt_sha256,
        "supervision_receipt_digest": supervision.receipt_sha256,
        "circuit_breaker_snapshot_digest": breaker.snapshot_sha256,
        "artifact_intake_receipt_digest": intake.receipt_sha256,
        "quarantine_package_digest": (
            package.package_sha256 if package is not None else ""
        ),
        "artifact_provenance_receipt_digest": (
            artifact_provenance_receipt.receipt_sha256
            if artifact_provenance_receipt is not None
            else _digest(b"cb025a-artifact-provenance-not-provided")
        ),
        "blast_radius_receipt_digest": (
            blast_radius_receipt.receipt_sha256
            if blast_radius_receipt is not None
            else _digest(b"cb025-blast-radius-not-evaluated")
        ),
        "verification_receipt_digest": (
            verification_receipt.receipt_sha256
            if verification_receipt is not None
            else _digest(b"cb025-verification-not-evaluated")
        ),
        "supervision_classification": supervision.final_classification,
        "artifact_intake_status": intake.status,
        "blast_radius_status": (
            blast_radius_receipt.status
            if blast_radius_receipt is not None
            else "not_evaluated"
        ),
        "verification_status": (
            verification_receipt.status
            if verification_receipt is not None
            else "not_evaluated"
        ),
        "final_classification": classification,
        "reason_code": reason,
        "known_limitations": tuple(sorted(limitations)),
        "artifact_intake_ordering_proven": provenance_proven,
        "artifact_content_provenance_proven": provenance_proven,
    }
    provisional = object.__new__(TrustChainProofReceipt)
    for name, value in values.items():
        object.__setattr__(provisional, name, value)
    object.__setattr__(provisional, "policy_version", POLICY_VERSION)
    return TrustChainProofReceipt(
        **values,
        proof_sha256=_digest(provisional._payload()),
        _proof_token=_PROOF_TOKEN,
    )
