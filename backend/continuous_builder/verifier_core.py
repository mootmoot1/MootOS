"""Deterministic verifier-core contracts for bounded code candidates.

CB-026A generalizes the fixture-only CB-025 verifier into a reusable structural
verification boundary.  It deliberately performs no subprocess execution,
opens no network connection, touches no worker workspace, and grants no
publication or merge authority.

The verifier receives only trusted system inputs plus the exact payload bytes
already admitted by CB-023.  It independently re-hashes those bytes,
reconstructs a candidate tree from a trusted base snapshot, enforces the
contract's path boundary, and emits an immutable content-addressed receipt.
Worker-authored claims are never inputs to the decision.

Behavioral checks such as pytest/flake8 belong to CB-026B.  This module proves
only deterministic candidate identity and structural compliance.
"""

import hashlib
import json
import re
from dataclasses import dataclass, field, replace

from .paths import PathCanonicalizationError, canonicalize_repo_path
from .worker_artifact import ArtifactIntakeResult, WorkerArtifactError
from .worker_runtime import WorkerExecutionReceipt, WorkerRuntimeError


class VerifierCoreError(ValueError):
    """Raised when verifier evidence cannot be produced safely."""


POLICY_VERSION = "cb-verifier-core-v1"
PROPOSAL_KIND = "replacement_files_v1"
MAX_BASE_FILES = 4096
MAX_ALLOWED_PATHS = 512
MAX_REQUIRED_PATHS = 256
MAX_PROTECTED_PATHS = 512
MAX_FAILURE_CODES = 16
MAX_RECEIPT_BYTES = 128 * 1024
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_GIT_SHA = re.compile(r"^[0-9a-f]{40}$")
_CONTRACT_TOKEN = object()
_RECEIPT_TOKEN = object()

STATUS_PASSED = "structural_verification_passed"
STATUS_FAILED = "structural_verification_failed"

FAILURE_CODES = frozenset({
    "artifact_path_not_allowed",
    "protected_path_modified",
    "quarantine_payload_digest_mismatch",
    "required_change_missing",
})


def _canonical(value):
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")


def _digest(value):
    return hashlib.sha256(value).hexdigest()


def _sha256(value, label):
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise VerifierCoreError(f"{label} is malformed")


def _canonical_path(value, label):
    if not isinstance(value, str):
        raise VerifierCoreError(f"{label} is malformed")
    try:
        canonical = canonicalize_repo_path(value)
    except PathCanonicalizationError as error:
        raise VerifierCoreError(f"{label} is unsafe") from error
    if canonical != value:
        raise VerifierCoreError(f"{label} is not canonical")
    return canonical


def _canonical_paths(values, label, maximum):
    if type(values) is not tuple or len(values) > maximum:
        raise VerifierCoreError(f"{label} is malformed")
    normalized = tuple(_canonical_path(value, label) for value in values)
    if normalized != tuple(sorted(set(normalized))):
        raise VerifierCoreError(f"{label} is not canonical")
    if len({value.casefold() for value in normalized}) != len(normalized):
        raise VerifierCoreError(f"{label} collides by case")
    return normalized


def _tree_manifest(files):
    return tuple(
        {
            "content_sha256": _digest(content),
            "relative_path": path,
            "size_bytes": len(content),
        }
        for path, content in sorted(files.items())
    )


def _tree_digest(files):
    return _digest(_canonical(list(_tree_manifest(files))))


def _validate_execution(receipt):
    if not isinstance(receipt, WorkerExecutionReceipt):
        raise VerifierCoreError("worker execution receipt is invalid")
    try:
        replace(receipt.materialization_receipt)
        replace(receipt.enforcement_evidence)
        replace(receipt)
    except WorkerRuntimeError as error:
        raise VerifierCoreError(
            "worker execution receipt failed authoritative validation"
        ) from error
    if receipt.execution_performed is not True:
        raise VerifierCoreError("verification requires an executed worker")
    if receipt.termination_uncertain or receipt.cleanup_uncertain:
        raise VerifierCoreError("uncertain worker execution cannot be verified")
    if any(
        value is not False
        for value in (
            receipt.worker_output_trusted,
            receipt.result_verified,
            receipt.patch_verified,
            receipt.externally_verified,
            receipt.publication_authorized,
            receipt.queue_transition_authorized,
            receipt.github_authorized,
        )
    ):
        raise VerifierCoreError("execution receipt overstates authority")


def _validate_intake(execution_receipt, intake_result):
    if not isinstance(intake_result, ArtifactIntakeResult):
        raise VerifierCoreError("artifact intake result is invalid")
    receipt = intake_result.receipt
    package = intake_result.quarantine_package
    try:
        replace(receipt)
        if package is not None:
            replace(package)
    except WorkerArtifactError as error:
        raise VerifierCoreError(
            "artifact intake evidence failed authoritative validation"
        ) from error
    if package is None or receipt.status != "quarantined_untrusted":
        raise VerifierCoreError(
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
        raise VerifierCoreError("artifact quarantine binding mismatch")
    return receipt, package


@dataclass(frozen=True)
class TrustedCandidateContract:
    """Trusted structural boundary for one candidate proposal."""

    contract_id: str
    slice_digest: str
    pinned_base_sha: str
    worker_request_digest: str
    base_tree_sha256: str
    allowed_paths: tuple
    required_changed_paths: tuple
    protected_paths: tuple
    boundary_sha256: str
    contract_sha256: str
    proposal_kind: str = PROPOSAL_KIND
    policy_version: str = POLICY_VERSION
    _base_files: tuple = field(default=(), repr=False, compare=False)
    _token: object = field(default=None, repr=False, compare=False)

    def __post_init__(self):
        if self._token is not _CONTRACT_TOKEN:
            raise VerifierCoreError(
                "candidate contract requires trusted system construction"
            )
        if not isinstance(self.contract_id, str) or not self.contract_id:
            raise VerifierCoreError("contract ID is malformed")
        for value, label in (
            (self.slice_digest, "slice digest"),
            (self.worker_request_digest, "worker request digest"),
            (self.base_tree_sha256, "base tree digest"),
            (self.boundary_sha256, "boundary digest"),
            (self.contract_sha256, "contract digest"),
        ):
            _sha256(value, label)
        if not isinstance(self.pinned_base_sha, str) or _GIT_SHA.fullmatch(
            self.pinned_base_sha
        ) is None:
            raise VerifierCoreError("pinned base SHA is malformed")
        if self.proposal_kind != PROPOSAL_KIND or self.policy_version != POLICY_VERSION:
            raise VerifierCoreError("candidate contract version is unsupported")
        allowed = _canonical_paths(
            self.allowed_paths, "allowed paths", MAX_ALLOWED_PATHS
        )
        required = _canonical_paths(
            self.required_changed_paths,
            "required changed paths",
            MAX_REQUIRED_PATHS,
        )
        protected = _canonical_paths(
            self.protected_paths, "protected paths", MAX_PROTECTED_PATHS
        )
        if not set(required).issubset(set(allowed)):
            raise VerifierCoreError("required paths must be allowed")
        if set(allowed).intersection(protected):
            raise VerifierCoreError("protected paths cannot be allowed")
        if type(self._base_files) is not tuple or len(self._base_files) > MAX_BASE_FILES:
            raise VerifierCoreError("trusted base snapshot is malformed")
        base = {}
        for item in self._base_files:
            if type(item) is not tuple or len(item) != 2:
                raise VerifierCoreError("trusted base snapshot is malformed")
            path, content = item
            path = _canonical_path(path, "base path")
            if not isinstance(content, bytes) or path in base:
                raise VerifierCoreError("trusted base snapshot is malformed")
            base[path] = content
        if tuple(base) != tuple(sorted(base)):
            raise VerifierCoreError("trusted base snapshot is not canonical")
        if self.base_tree_sha256 != _tree_digest(base):
            raise VerifierCoreError("trusted base tree digest mismatch")
        boundary = {
            "allowed_paths": list(allowed),
            "protected_paths": list(protected),
            "required_changed_paths": list(required),
        }
        if self.boundary_sha256 != _digest(_canonical(boundary)):
            raise VerifierCoreError("candidate boundary digest mismatch")
        if self.contract_sha256 != _digest(self._payload()):
            raise VerifierCoreError("candidate contract digest mismatch")

    def _body(self):
        return {
            "allowed_paths": list(self.allowed_paths),
            "base_tree_sha256": self.base_tree_sha256,
            "boundary_sha256": self.boundary_sha256,
            "contract_id": self.contract_id,
            "pinned_base_sha": self.pinned_base_sha,
            "policy_version": POLICY_VERSION,
            "proposal_kind": PROPOSAL_KIND,
            "protected_paths": list(self.protected_paths),
            "required_changed_paths": list(self.required_changed_paths),
            "slice_digest": self.slice_digest,
            "worker_request_digest": self.worker_request_digest,
        }

    def _payload(self):
        return _canonical(self._body())

    def base_content(self):
        return dict(self._base_files)


def create_trusted_candidate_contract(
    *,
    contract_id,
    slice_digest,
    pinned_base_sha,
    worker_request_digest,
    base_files,
    allowed_paths,
    required_changed_paths=(),
    protected_paths=(),
):
    """Create one immutable verifier boundary from trusted system inputs."""
    if not isinstance(base_files, dict):
        raise VerifierCoreError("trusted base snapshot must be a mapping")
    canonical_base = {}
    for path, content in base_files.items():
        path = _canonical_path(path, "base path")
        if not isinstance(content, bytes):
            raise VerifierCoreError("trusted base bytes are malformed")
        if path in canonical_base:
            raise VerifierCoreError("trusted base paths collide")
        canonical_base[path] = content
    base_items = tuple(sorted(canonical_base.items()))
    allowed = tuple(sorted(allowed_paths))
    required = tuple(sorted(required_changed_paths))
    protected = tuple(sorted(protected_paths))
    boundary = {
        "allowed_paths": list(allowed),
        "protected_paths": list(protected),
        "required_changed_paths": list(required),
    }
    values = {
        "contract_id": contract_id,
        "slice_digest": slice_digest,
        "pinned_base_sha": pinned_base_sha,
        "worker_request_digest": worker_request_digest,
        "base_tree_sha256": _tree_digest(canonical_base),
        "allowed_paths": allowed,
        "required_changed_paths": required,
        "protected_paths": protected,
        "boundary_sha256": _digest(_canonical(boundary)),
        "_base_files": base_items,
    }
    provisional = object.__new__(TrustedCandidateContract)
    for name, value in values.items():
        object.__setattr__(provisional, name, value)
    object.__setattr__(provisional, "proposal_kind", PROPOSAL_KIND)
    object.__setattr__(provisional, "policy_version", POLICY_VERSION)
    return TrustedCandidateContract(
        **values,
        contract_sha256=_digest(provisional._payload()),
        _token=_CONTRACT_TOKEN,
    )


@dataclass(frozen=True)
class StructuralVerificationReceipt:
    """Immutable evidence for deterministic candidate reconstruction."""

    contract_sha256: str
    slice_digest: str
    boundary_sha256: str
    pinned_base_sha: str
    base_tree_sha256: str
    execution_receipt_digest: str
    attempt_id: str
    execution_id: str
    request_digest: str
    artifact_intake_receipt_digest: str
    quarantine_package_digest: str
    inventory_sha256: str
    candidate_tree_sha256: str
    changed_paths: tuple
    changed_paths_sha256: str
    status: str
    failure_codes: tuple
    receipt_sha256: str
    policy_version: str = POLICY_VERSION
    proposal_kind: str = PROPOSAL_KIND
    verification_performed: bool = True
    trusted_base_reconstructed: bool = True
    artifact_payloads_rehashed: bool = True
    path_boundary_enforced: bool = True
    worker_workspace_reused: bool = False
    worker_claim_considered: bool = False
    worker_output_trusted: bool = False
    result_trusted: bool = False
    behavioral_checks_executed: bool = False
    publication_authorized: bool = False
    queue_transition_authorized: bool = False
    github_authorized: bool = False
    merge_authorized: bool = False
    main_advancement_authorized: bool = False
    _token: object = field(default=None, repr=False, compare=False)

    def __post_init__(self):
        if self._token is not _RECEIPT_TOKEN:
            raise VerifierCoreError(
                "verification receipt requires trusted derived evidence"
            )
        for value, label in (
            (self.contract_sha256, "contract digest"),
            (self.slice_digest, "slice digest"),
            (self.boundary_sha256, "boundary digest"),
            (self.base_tree_sha256, "base tree digest"),
            (self.execution_receipt_digest, "execution receipt digest"),
            (self.request_digest, "request digest"),
            (self.artifact_intake_receipt_digest, "artifact intake digest"),
            (self.quarantine_package_digest, "quarantine package digest"),
            (self.inventory_sha256, "inventory digest"),
            (self.candidate_tree_sha256, "candidate tree digest"),
            (self.changed_paths_sha256, "changed paths digest"),
            (self.receipt_sha256, "receipt digest"),
        ):
            _sha256(value, label)
        if not isinstance(self.pinned_base_sha, str) or _GIT_SHA.fullmatch(
            self.pinned_base_sha
        ) is None:
            raise VerifierCoreError("pinned base SHA is malformed")
        _canonical_paths(self.changed_paths, "changed paths", MAX_ALLOWED_PATHS)
        if self.changed_paths_sha256 != _digest(
            _canonical(list(self.changed_paths))
        ):
            raise VerifierCoreError("changed paths digest mismatch")
        if self.status not in (STATUS_PASSED, STATUS_FAILED):
            raise VerifierCoreError("verification status is malformed")
        if type(self.failure_codes) is not tuple or len(
            self.failure_codes
        ) > MAX_FAILURE_CODES or any(
            code not in FAILURE_CODES for code in self.failure_codes
        ):
            raise VerifierCoreError("failure codes are malformed")
        if self.failure_codes != tuple(sorted(set(self.failure_codes))):
            raise VerifierCoreError("failure codes are not canonical")
        if (self.status == STATUS_PASSED) is bool(self.failure_codes):
            raise VerifierCoreError("verification status contradicts failures")
        if self.policy_version != POLICY_VERSION or self.proposal_kind != PROPOSAL_KIND:
            raise VerifierCoreError("verification receipt version is unsupported")
        if any(
            value is not True
            for value in (
                self.verification_performed,
                self.trusted_base_reconstructed,
                self.artifact_payloads_rehashed,
                self.path_boundary_enforced,
            )
        ) or any(
            value is not False
            for value in (
                self.worker_workspace_reused,
                self.worker_claim_considered,
                self.worker_output_trusted,
                self.result_trusted,
                self.behavioral_checks_executed,
                self.publication_authorized,
                self.queue_transition_authorized,
                self.github_authorized,
                self.merge_authorized,
                self.main_advancement_authorized,
            )
        ):
            raise VerifierCoreError("verification receipt promotes authority")
        if self.receipt_sha256 != _digest(self._payload()):
            raise VerifierCoreError("verification receipt digest mismatch")
        if len(self.canonical_bytes()) > MAX_RECEIPT_BYTES:
            raise VerifierCoreError("verification receipt exceeds byte bound")

    def _body(self):
        return {
            "artifact_intake_receipt_digest": self.artifact_intake_receipt_digest,
            "artifact_payloads_rehashed": True,
            "attempt_id": self.attempt_id,
            "base_tree_sha256": self.base_tree_sha256,
            "behavioral_checks_executed": False,
            "boundary_sha256": self.boundary_sha256,
            "candidate_tree_sha256": self.candidate_tree_sha256,
            "changed_paths": list(self.changed_paths),
            "changed_paths_sha256": self.changed_paths_sha256,
            "contract_sha256": self.contract_sha256,
            "execution_id": self.execution_id,
            "execution_receipt_digest": self.execution_receipt_digest,
            "failure_codes": list(self.failure_codes),
            "github_authorized": False,
            "inventory_sha256": self.inventory_sha256,
            "main_advancement_authorized": False,
            "merge_authorized": False,
            "path_boundary_enforced": True,
            "pinned_base_sha": self.pinned_base_sha,
            "policy_version": POLICY_VERSION,
            "proposal_kind": PROPOSAL_KIND,
            "publication_authorized": False,
            "quarantine_package_digest": self.quarantine_package_digest,
            "queue_transition_authorized": False,
            "request_digest": self.request_digest,
            "result_trusted": False,
            "slice_digest": self.slice_digest,
            "status": self.status,
            "trusted_base_reconstructed": True,
            "verification_performed": True,
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


def verify_candidate_structure(contract, execution_receipt, intake_result):
    """Reconstruct and structurally validate one quarantined candidate."""
    if not isinstance(contract, TrustedCandidateContract):
        raise VerifierCoreError("candidate contract is invalid")
    try:
        replace(contract)
    except VerifierCoreError as error:
        raise VerifierCoreError(
            "candidate contract failed authoritative validation"
        ) from error
    _validate_execution(execution_receipt)
    intake, package = _validate_intake(execution_receipt, intake_result)
    materialization = execution_receipt.materialization_receipt
    if contract.worker_request_digest != execution_receipt.request_digest:
        raise VerifierCoreError("candidate contract request binding mismatch")
    if contract.pinned_base_sha != materialization.pinned_base_sha:
        raise VerifierCoreError("candidate contract base binding mismatch")

    recorded = {
        entry.relative_path: entry.content_sha256
        for entry in package.inventory
    }
    admitted = {}
    failures = set()
    for path, content in intake_result._artifact_payloads:
        observed = _digest(content)
        if path in admitted or recorded.get(path) != observed:
            failures.add("quarantine_payload_digest_mismatch")
        admitted[path] = content
    if set(admitted) != set(recorded):
        failures.add("quarantine_payload_digest_mismatch")

    base = contract.base_content()
    changed = set()
    candidate = dict(base)
    allowed = set(contract.allowed_paths)
    protected = set(contract.protected_paths)
    for path, content in admitted.items():
        if path not in allowed:
            failures.add("artifact_path_not_allowed")
        if path in protected:
            failures.add("protected_path_modified")
        if base.get(path) != content:
            changed.add(path)
        candidate[path] = content

    missing = set(contract.required_changed_paths).difference(changed)
    if missing:
        failures.add("required_change_missing")

    changed_paths = tuple(sorted(changed))
    ordered_failures = tuple(sorted(failures))
    values = {
        "contract_sha256": contract.contract_sha256,
        "slice_digest": contract.slice_digest,
        "boundary_sha256": contract.boundary_sha256,
        "pinned_base_sha": contract.pinned_base_sha,
        "base_tree_sha256": contract.base_tree_sha256,
        "execution_receipt_digest": execution_receipt.receipt_sha256,
        "attempt_id": execution_receipt.attempt_id,
        "execution_id": execution_receipt.execution_id,
        "request_digest": execution_receipt.request_digest,
        "artifact_intake_receipt_digest": intake.receipt_sha256,
        "quarantine_package_digest": package.package_sha256,
        "inventory_sha256": package.inventory_sha256,
        "candidate_tree_sha256": _tree_digest(candidate),
        "changed_paths": changed_paths,
        "changed_paths_sha256": _digest(_canonical(list(changed_paths))),
        "status": STATUS_FAILED if ordered_failures else STATUS_PASSED,
        "failure_codes": ordered_failures,
    }
    provisional = object.__new__(StructuralVerificationReceipt)
    for name, value in values.items():
        object.__setattr__(provisional, name, value)
    object.__setattr__(provisional, "policy_version", POLICY_VERSION)
    object.__setattr__(provisional, "proposal_kind", PROPOSAL_KIND)
    return StructuralVerificationReceipt(
        **values,
        receipt_sha256=_digest(provisional._payload()),
        _token=_RECEIPT_TOKEN,
    )
