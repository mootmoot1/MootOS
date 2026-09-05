"""Deterministic system-side blast-radius gate for the CB-025 proof.

The gate answers exactly one question about an already-quarantined CB-023
artifact set: *did the observed, admitted artifacts stay inside the boundary
the system declared for this task?*  It reads no worker-authored text, no
stdout, and no worker claim of any kind -- only the structural inventory the
supervisor observed plus the exact payload bytes CB-023 admitted.

Passing this gate means only that.  It is not correctness, not safety, not
verification, and not merge readiness.  A correct-looking result that touched
anything outside the declared boundary is rejected here regardless of how
well it "works".
"""

import hashlib
import json
import re
from dataclasses import dataclass, field, replace

from .proof_fixture import (
    FixtureTaskContract,
    ProofFixtureError,
    safe_relative_path,
)
from .worker_artifact import (
    ArtifactIntakeResult,
    WorkerArtifactError,
)
from .worker_runtime import WorkerExecutionReceipt, WorkerRuntimeError


class BlastRadiusError(ValueError):
    """Raised when blast-radius evidence cannot be safely produced."""


POLICY_VERSION = "cb-blast-radius-v1"
MAX_RECEIPT_BYTES = 64 * 1024
MAX_VIOLATIONS = 32
STATUS_WITHIN = "within_blast_radius_unverified"
STATUS_REJECTED = "blast_radius_rejected"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_GATE_TOKEN = object()

VIOLATION_CODES = frozenset({
    "artifact_count_exceeds_boundary",
    "artifact_outside_allowed_paths",
    "artifact_path_forbidden_class",
    "artifact_path_not_canonical",
    "artifact_payload_digest_mismatch",
    "artifact_payload_set_mismatch",
    "artifact_type_not_regular_file",
})


def _canonical(value):
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")


def _digest(value):
    return hashlib.sha256(value).hexdigest()


def _sha256(value, name):
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise BlastRadiusError(f"{name} is malformed")


def _validate_task(task):
    if not isinstance(task, FixtureTaskContract):
        raise BlastRadiusError("fixture task contract is invalid")
    try:
        replace(task)
    except ProofFixtureError as error:
        raise BlastRadiusError(
            "fixture task contract failed authoritative validation"
        ) from error


def _validate_execution(receipt):
    if not isinstance(receipt, WorkerExecutionReceipt):
        raise BlastRadiusError("worker execution receipt is invalid")
    try:
        replace(receipt.materialization_receipt)
        replace(receipt.enforcement_evidence)
        replace(receipt)
    except WorkerRuntimeError as error:
        raise BlastRadiusError(
            "worker execution receipt failed authoritative validation"
        ) from error


def _validate_intake(execution_receipt, intake_result):
    if not isinstance(intake_result, ArtifactIntakeResult):
        raise BlastRadiusError("artifact intake result is invalid")
    receipt = intake_result.receipt
    package = intake_result.quarantine_package
    try:
        replace(receipt)
        if package is not None:
            replace(package)
    except WorkerArtifactError as error:
        raise BlastRadiusError(
            "artifact intake evidence failed authoritative validation"
        ) from error
    if package is None or receipt.status != "quarantined_untrusted":
        raise BlastRadiusError(
            "blast-radius evaluation requires an admitted quarantine package"
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
        (
            package.workspace_identity,
            execution_receipt.materialization_receipt
            .workspace_instance_digest,
        ),
    )
    if any(actual != wanted for actual, wanted in bindings):
        raise BlastRadiusError("artifact quarantine binding mismatch")
    return receipt, package


@dataclass(frozen=True)
class BlastRadiusReceipt:
    """Immutable, content-addressed record of one boundary evaluation."""

    task_sha256: str
    allowed_paths_sha256: str
    max_artifact_count: int
    execution_receipt_digest: str
    attempt_id: str
    execution_id: str
    request_digest: str
    policy_digest: str
    materialization_receipt_digest: str
    workspace_identity: str
    artifact_intake_receipt_digest: str
    quarantine_package_digest: str
    inventory_sha256: str
    observed_artifact_count: int
    observed_total_bytes: int
    observed_paths_sha256: str
    status: str
    violations: tuple
    receipt_sha256: str
    policy_version: str = POLICY_VERSION
    boundary_evaluated: bool = True
    worker_claim_considered: bool = False
    artifact_content_trusted: bool = False
    result_verified: bool = False
    externally_verified: bool = False
    publication_authorized: bool = False
    queue_transition_authorized: bool = False
    github_authorized: bool = False
    merge_authorized: bool = False
    _gate_token: object = field(default=None, repr=False, compare=False)

    def __post_init__(self):
        if self._gate_token is not _GATE_TOKEN:
            raise BlastRadiusError(
                "blast-radius receipt requires trusted observed evidence"
            )
        if self.policy_version != POLICY_VERSION:
            raise BlastRadiusError("blast-radius policy is unsupported")
        for name in (
            "task_sha256", "allowed_paths_sha256", "execution_receipt_digest",
            "request_digest", "policy_digest",
            "materialization_receipt_digest", "workspace_identity",
            "artifact_intake_receipt_digest", "quarantine_package_digest",
            "inventory_sha256", "observed_paths_sha256", "receipt_sha256",
        ):
            _sha256(getattr(self, name), name)
        if self.status not in (STATUS_WITHIN, STATUS_REJECTED):
            raise BlastRadiusError("blast-radius status is malformed")
        if type(self.violations) is not tuple or len(
            self.violations
        ) > MAX_VIOLATIONS or any(
            code not in VIOLATION_CODES for code in self.violations
        ):
            raise BlastRadiusError("blast-radius violations are malformed")
        if self.violations != tuple(sorted(set(self.violations))):
            raise BlastRadiusError("blast-radius violations are not canonical")
        if (self.status == STATUS_WITHIN) is bool(self.violations):
            raise BlastRadiusError("blast-radius status contradicts evidence")
        for name in (
            "max_artifact_count", "observed_artifact_count",
            "observed_total_bytes",
        ):
            value = getattr(self, name)
            if type(value) is not int or value < 0:
                raise BlastRadiusError(f"{name} is malformed")
        if self.boundary_evaluated is not True or any(
            value is not False
            for value in (
                self.worker_claim_considered,
                self.artifact_content_trusted,
                self.result_verified,
                self.externally_verified,
                self.publication_authorized,
                self.queue_transition_authorized,
                self.github_authorized,
                self.merge_authorized,
            )
        ):
            raise BlastRadiusError("blast-radius receipt promotes authority")
        if self.receipt_sha256 != _digest(self._payload()):
            raise BlastRadiusError("blast-radius receipt digest mismatch")
        if len(self.canonical_bytes()) > MAX_RECEIPT_BYTES:
            raise BlastRadiusError("blast-radius receipt exceeds byte bound")

    def _body(self):
        return {
            "allowed_paths_sha256": self.allowed_paths_sha256,
            "artifact_content_trusted": False,
            "artifact_intake_receipt_digest": (
                self.artifact_intake_receipt_digest
            ),
            "attempt_id": self.attempt_id,
            "boundary_evaluated": True,
            "execution_id": self.execution_id,
            "execution_receipt_digest": self.execution_receipt_digest,
            "externally_verified": False,
            "github_authorized": False,
            "inventory_sha256": self.inventory_sha256,
            "materialization_receipt_digest": (
                self.materialization_receipt_digest
            ),
            "max_artifact_count": self.max_artifact_count,
            "merge_authorized": False,
            "observed_artifact_count": self.observed_artifact_count,
            "observed_paths_sha256": self.observed_paths_sha256,
            "observed_total_bytes": self.observed_total_bytes,
            "policy_digest": self.policy_digest,
            "policy_version": POLICY_VERSION,
            "publication_authorized": False,
            "quarantine_package_digest": self.quarantine_package_digest,
            "queue_transition_authorized": False,
            "request_digest": self.request_digest,
            "result_verified": False,
            "status": self.status,
            "task_sha256": self.task_sha256,
            "violations": list(self.violations),
            "worker_claim_considered": False,
            "workspace_identity": self.workspace_identity,
        }

    def _payload(self):
        return _canonical(self._body())

    def canonical_bytes(self):
        value = self._body()
        value["receipt_sha256"] = self.receipt_sha256
        return _canonical(value)


def evaluate_blast_radius(task, execution_receipt, intake_result):
    """Compare one admitted artifact set against the declared boundary."""
    _validate_task(task)
    _validate_execution(execution_receipt)
    receipt, package = _validate_intake(execution_receipt, intake_result)

    allowed = set(task.allowed_paths)
    violations = set()
    observed_paths = []
    for entry in package.inventory:
        observed_paths.append(entry.relative_path)
        if entry.artifact_type != "regular_file":
            violations.add("artifact_type_not_regular_file")
        try:
            safe_relative_path(entry.relative_path, "artifact path")
        except ProofFixtureError as error:
            if "forbidden path class" in str(error):
                violations.add("artifact_path_forbidden_class")
            else:
                violations.add("artifact_path_not_canonical")
        if entry.relative_path not in allowed:
            violations.add("artifact_outside_allowed_paths")
    if len(package.inventory) > task.max_artifact_count:
        violations.add("artifact_count_exceeds_boundary")

    payloads = intake_result._artifact_payloads
    inventory = {
        entry.relative_path: (entry.size_bytes, entry.content_sha256)
        for entry in package.inventory
    }
    observed_payloads = {}
    for path, content in payloads:
        observed_payloads[path] = (len(content), _digest(content))
    if set(observed_payloads) != set(inventory) or len(payloads) != len(
        inventory
    ):
        violations.add("artifact_payload_set_mismatch")
    elif observed_payloads != inventory:
        violations.add("artifact_payload_digest_mismatch")

    ordered = tuple(sorted(violations))
    values = {
        "task_sha256": task.task_sha256,
        "allowed_paths_sha256": task.allowed_paths_sha256,
        "max_artifact_count": task.max_artifact_count,
        "execution_receipt_digest": execution_receipt.receipt_sha256,
        "attempt_id": execution_receipt.attempt_id,
        "execution_id": execution_receipt.execution_id,
        "request_digest": execution_receipt.request_digest,
        "policy_digest": execution_receipt.policy_digest,
        "materialization_receipt_digest": (
            execution_receipt.materialization_receipt_digest
        ),
        "workspace_identity": package.workspace_identity,
        "artifact_intake_receipt_digest": receipt.receipt_sha256,
        "quarantine_package_digest": package.package_sha256,
        "inventory_sha256": package.inventory_sha256,
        "observed_artifact_count": package.total_artifact_count,
        "observed_total_bytes": package.total_artifact_bytes,
        "observed_paths_sha256": _digest(
            _canonical(sorted(observed_paths))
        ),
        "status": STATUS_REJECTED if ordered else STATUS_WITHIN,
        "violations": ordered,
    }
    provisional = object.__new__(BlastRadiusReceipt)
    for name, value in values.items():
        object.__setattr__(provisional, name, value)
    object.__setattr__(provisional, "policy_version", POLICY_VERSION)
    return BlastRadiusReceipt(
        **values,
        receipt_sha256=_digest(provisional._payload()),
        _gate_token=_GATE_TOKEN,
    )
