"""Minimal independent verifier for the CB-025 contained trust-chain proof.

Deliberately narrow and fixture-specific.  It is *not* the generalized CB-026+
verifier system: it runs no commands, opens no sandbox, and reads no worker
text.  Its only inputs are the trusted fixture task contract (base bytes plus
the acceptance rule) and the exact payload bytes CB-023 admitted into
quarantine, bound by digest to one execution.

Independence properties this module maintains, and that the CB-025 tests
assert mechanically:

* it never touches the worker's mutable execution workspace (which CB-022 has
  already destroyed by this point anyway);
* it never reads ``stdout_sample``, ``stdout_sha256``, ``stderr_sample`` or
  any other worker-authored channel, so a worker asserting "tests passed"
  cannot influence the outcome;
* it re-derives every content digest from bytes rather than believing the
  digests recorded in the quarantine inventory;
* it reconstructs the candidate tree from the *trusted* base plus admitted
  payloads, then compares against the system's own expected bytes.

Extra, unexpected paths are intentionally not this module's concern: staying
inside the declared boundary is the blast-radius gate's question, and the
CB-025 proof requires both answers.  A passing verification authorizes
nothing.
"""

import hashlib
import json
import re
from dataclasses import dataclass, field, replace

from .proof_fixture import FixtureTaskContract, ProofFixtureError
from .worker_artifact import ArtifactIntakeResult, WorkerArtifactError
from .worker_runtime import WorkerExecutionReceipt, WorkerRuntimeError


class CandidateVerificationError(ValueError):
    """Raised when verification evidence cannot be safely produced."""


POLICY_VERSION = "cb-candidate-verifier-v1"
MAX_RECEIPT_BYTES = 64 * 1024
MAX_FAILURE_CODES = 16
STATUS_PASSED = "verification_passed"
STATUS_FAILED = "verification_failed"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_VERIFIER_TOKEN = object()

FAILURE_CODES = frozenset({
    "expected_artifact_content_mismatch",
    "expected_artifact_missing",
    "quarantine_payload_digest_mismatch",
})


def _canonical(value):
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")


def _digest(value):
    return hashlib.sha256(value).hexdigest()


def _sha256(value, name):
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise CandidateVerificationError(f"{name} is malformed")


def _validate_task(task):
    if not isinstance(task, FixtureTaskContract):
        raise CandidateVerificationError("fixture task contract is invalid")
    try:
        replace(task)
    except ProofFixtureError as error:
        raise CandidateVerificationError(
            "fixture task contract failed authoritative validation"
        ) from error


def _validate_execution(receipt):
    if not isinstance(receipt, WorkerExecutionReceipt):
        raise CandidateVerificationError("worker execution receipt is invalid")
    try:
        replace(receipt.materialization_receipt)
        replace(receipt.enforcement_evidence)
        replace(receipt)
    except WorkerRuntimeError as error:
        raise CandidateVerificationError(
            "worker execution receipt failed authoritative validation"
        ) from error


def _validate_intake(execution_receipt, intake_result):
    if not isinstance(intake_result, ArtifactIntakeResult):
        raise CandidateVerificationError("artifact intake result is invalid")
    receipt = intake_result.receipt
    package = intake_result.quarantine_package
    try:
        replace(receipt)
        if package is not None:
            replace(package)
    except WorkerArtifactError as error:
        raise CandidateVerificationError(
            "artifact intake evidence failed authoritative validation"
        ) from error
    if package is None or receipt.status != "quarantined_untrusted":
        raise CandidateVerificationError(
            "verification requires an admitted quarantine package"
        )
    bindings = (
        (receipt.execution_receipt_digest, execution_receipt.receipt_sha256),
        (receipt.attempt_id, execution_receipt.attempt_id),
        (receipt.execution_id, execution_receipt.execution_id),
        (receipt.request_digest, execution_receipt.request_digest),
        (receipt.policy_digest, execution_receipt.policy_digest),
        (
            receipt.materialization_receipt_digest,
            execution_receipt.materialization_receipt_digest,
        ),
        (receipt.quarantine_package_digest, package.package_sha256),
        (package.execution_receipt_digest, execution_receipt.receipt_sha256),
        (package.attempt_id, execution_receipt.attempt_id),
        (package.execution_id, execution_receipt.execution_id),
        (package.request_digest, execution_receipt.request_digest),
        (package.inventory_sha256, receipt.inventory_sha256),
    )
    if any(actual != wanted for actual, wanted in bindings):
        raise CandidateVerificationError(
            "artifact quarantine binding mismatch"
        )
    return receipt, package


@dataclass(frozen=True)
class CandidateVerificationReceipt:
    """Immutable, content-addressed record of one independent verification."""

    task_sha256: str
    acceptance_rule_sha256: str
    base_fixture_sha256: str
    execution_receipt_digest: str
    attempt_id: str
    execution_id: str
    request_digest: str
    materialization_receipt_digest: str
    artifact_intake_receipt_digest: str
    quarantine_package_digest: str
    inventory_sha256: str
    candidate_tree_sha256: str
    verified_path_count: int
    status: str
    failure_codes: tuple
    receipt_sha256: str
    policy_version: str = POLICY_VERSION
    verification_performed: bool = True
    reconstructed_from_trusted_base: bool = True
    worker_workspace_reused: bool = False
    worker_claim_considered: bool = False
    worker_output_trusted: bool = False
    publication_authorized: bool = False
    queue_transition_authorized: bool = False
    github_authorized: bool = False
    merge_authorized: bool = False
    _verifier_token: object = field(default=None, repr=False, compare=False)

    def __post_init__(self):
        if self._verifier_token is not _VERIFIER_TOKEN:
            raise CandidateVerificationError(
                "verification receipt requires trusted derived evidence"
            )
        if self.policy_version != POLICY_VERSION:
            raise CandidateVerificationError("verifier policy is unsupported")
        for name in (
            "task_sha256", "acceptance_rule_sha256", "base_fixture_sha256",
            "execution_receipt_digest", "request_digest",
            "materialization_receipt_digest",
            "artifact_intake_receipt_digest", "quarantine_package_digest",
            "inventory_sha256", "candidate_tree_sha256", "receipt_sha256",
        ):
            _sha256(getattr(self, name), name)
        if self.status not in (STATUS_PASSED, STATUS_FAILED):
            raise CandidateVerificationError(
                "verification status is malformed"
            )
        if type(self.failure_codes) is not tuple or len(
            self.failure_codes
        ) > MAX_FAILURE_CODES or any(
            code not in FAILURE_CODES for code in self.failure_codes
        ):
            raise CandidateVerificationError("failure codes are malformed")
        if self.failure_codes != tuple(sorted(set(self.failure_codes))):
            raise CandidateVerificationError(
                "failure codes are not canonical"
            )
        if (self.status == STATUS_PASSED) is bool(self.failure_codes):
            raise CandidateVerificationError(
                "verification status contradicts evidence"
            )
        if type(self.verified_path_count) is not int or (
            self.verified_path_count < 0
        ):
            raise CandidateVerificationError(
                "verified path count is malformed"
            )
        if (
            self.verification_performed is not True
            or self.reconstructed_from_trusted_base is not True
        ) or any(
            value is not False
            for value in (
                self.worker_workspace_reused,
                self.worker_claim_considered,
                self.worker_output_trusted,
                self.publication_authorized,
                self.queue_transition_authorized,
                self.github_authorized,
                self.merge_authorized,
            )
        ):
            raise CandidateVerificationError(
                "verification receipt promotes authority"
            )
        if self.receipt_sha256 != _digest(self._payload()):
            raise CandidateVerificationError(
                "verification receipt digest mismatch"
            )
        if len(self.canonical_bytes()) > MAX_RECEIPT_BYTES:
            raise CandidateVerificationError(
                "verification receipt exceeds byte bound"
            )

    def _body(self):
        return {
            "acceptance_rule_sha256": self.acceptance_rule_sha256,
            "artifact_intake_receipt_digest": (
                self.artifact_intake_receipt_digest
            ),
            "attempt_id": self.attempt_id,
            "base_fixture_sha256": self.base_fixture_sha256,
            "candidate_tree_sha256": self.candidate_tree_sha256,
            "execution_id": self.execution_id,
            "execution_receipt_digest": self.execution_receipt_digest,
            "failure_codes": list(self.failure_codes),
            "github_authorized": False,
            "inventory_sha256": self.inventory_sha256,
            "materialization_receipt_digest": (
                self.materialization_receipt_digest
            ),
            "merge_authorized": False,
            "policy_version": POLICY_VERSION,
            "publication_authorized": False,
            "quarantine_package_digest": self.quarantine_package_digest,
            "queue_transition_authorized": False,
            "reconstructed_from_trusted_base": True,
            "request_digest": self.request_digest,
            "status": self.status,
            "task_sha256": self.task_sha256,
            "verification_performed": True,
            "verified_path_count": self.verified_path_count,
            "worker_claim_considered": False,
            "worker_output_trusted": False,
            "worker_workspace_reused": False,
        }

    def _payload(self):
        return _canonical(self._body())

    def canonical_bytes(self):
        value = self._body()
        value["receipt_sha256"] = self.receipt_sha256
        return _canonical(value)


def verify_candidate(task, execution_receipt, intake_result):
    """Independently reconstruct and check one candidate, offline."""
    _validate_task(task)
    _validate_execution(execution_receipt)
    receipt, package = _validate_intake(execution_receipt, intake_result)

    failures = set()
    recorded = {
        entry.relative_path: entry.content_sha256
        for entry in package.inventory
    }
    admitted = {}
    for path, content in intake_result._artifact_payloads:
        observed = _digest(content)
        if recorded.get(path) != observed:
            failures.add("quarantine_payload_digest_mismatch")
        admitted[path] = content
    if set(admitted) != set(recorded):
        failures.add("quarantine_payload_digest_mismatch")

    candidate = dict(task.base_content())
    candidate.update(admitted)

    expected = task.expected_content()
    for path in sorted(expected):
        actual = candidate.get(path)
        if actual is None:
            failures.add("expected_artifact_missing")
        elif actual != expected[path]:
            failures.add("expected_artifact_content_mismatch")

    tree = _digest(_canonical([
        {
            "content_sha256": _digest(candidate[path]),
            "relative_path": path,
            "size_bytes": len(candidate[path]),
        }
        for path in sorted(candidate)
    ]))
    ordered = tuple(sorted(failures))
    values = {
        "task_sha256": task.task_sha256,
        "acceptance_rule_sha256": task.acceptance_rule_sha256,
        "base_fixture_sha256": task.base_fixture_sha256,
        "execution_receipt_digest": execution_receipt.receipt_sha256,
        "attempt_id": execution_receipt.attempt_id,
        "execution_id": execution_receipt.execution_id,
        "request_digest": execution_receipt.request_digest,
        "materialization_receipt_digest": (
            execution_receipt.materialization_receipt_digest
        ),
        "artifact_intake_receipt_digest": receipt.receipt_sha256,
        "quarantine_package_digest": package.package_sha256,
        "inventory_sha256": package.inventory_sha256,
        "candidate_tree_sha256": tree,
        "verified_path_count": len(expected),
        "status": STATUS_FAILED if ordered else STATUS_PASSED,
        "failure_codes": ordered,
    }
    provisional = object.__new__(CandidateVerificationReceipt)
    for name, value in values.items():
        object.__setattr__(provisional, name, value)
    object.__setattr__(provisional, "policy_version", POLICY_VERSION)
    return CandidateVerificationReceipt(
        **values,
        receipt_sha256=_digest(provisional._payload()),
        _verifier_token=_VERIFIER_TOKEN,
    )
