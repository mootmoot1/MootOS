"""Inert repository-materialization plans and pre-execution receipts.

The contracts specify evidence a future trusted materializer must produce.
They contain no filesystem, archive, Git, or process operation.
"""

import hashlib
import json
import re
from dataclasses import dataclass

from .sandbox_repository import DisposableRepositoryPlan
from .text_safety import utf8_length


class RepositoryMaterializationError(ValueError):
    """Raised when materialization evidence is malformed or forged."""


POLICY_VERSION = "cb-repository-materialization-v1"
MAX_CONTRACT_BYTES = 64 * 1024
VERIFICATION_REQUIREMENTS = (
    "content_digests_match",
    "exact_file_count",
    "exact_manifest_match",
    "no_extra_files",
    "no_git_control_directory",
    "no_git_hooks",
    "no_inherited_git_config",
    "no_path_collisions",
    "no_path_escape",
    "no_symlinks",
    "pinned_base_matches_source",
    "source_remains_read_only",
    "workspace_is_disposable",
    "writable_workspace_isolated",
)
_IDENTITY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _identity(value, name):
    if (
        not isinstance(value, str)
        or _IDENTITY.fullmatch(value or "") is None
        or utf8_length(value) > 256
    ):
        raise RepositoryMaterializationError(f"{name} is malformed")
    return value


def _sha256(value, name):
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise RepositoryMaterializationError(f"{name} is malformed")
    return value


def _canonical(value):
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")


@dataclass(frozen=True)
class RepositoryMaterializationContract:
    reconstruction_plan: DisposableRepositoryPlan
    materialization_id: str
    repository_id: str
    worker_request_digest: str
    blueprint_id: str
    blueprint_digest: str
    slice_id: str
    slice_digest: str
    attempt_id: str
    pinned_base_sha: str
    source_manifest_digest: str
    disposable_workspace_id: str
    reconstruction_plan_digest: str
    materialization_mode: str
    expected_file_count: int
    expected_total_bytes: int
    content_manifest_digest: str
    contract_sha256: str
    verification_requirements: tuple = VERIFICATION_REQUIREMENTS
    policy_version: str = POLICY_VERSION
    materialization_planned: bool = True
    materialization_verified: bool = False
    materialization_performed: bool = False
    symlinks_allowed: bool = False
    git_directory_allowed: bool = False
    git_hooks_allowed: bool = False
    inherited_git_config_allowed: bool = False
    host_repository_reused: bool = False
    host_workspace_reused: bool = False
    launch_authorized: bool = False

    def __post_init__(self):
        if not isinstance(self.reconstruction_plan, DisposableRepositoryPlan):
            raise RepositoryMaterializationError(
                "reconstruction plan is invalid"
            )
        for name in (
            "materialization_id", "repository_id", "blueprint_id",
            "slice_id", "attempt_id", "disposable_workspace_id",
            "materialization_mode",
        ):
            object.__setattr__(
                self, name, _identity(getattr(self, name), name)
            )
        for name in (
            "worker_request_digest", "blueprint_digest", "slice_digest",
            "source_manifest_digest", "reconstruction_plan_digest",
            "content_manifest_digest",
        ):
            _sha256(getattr(self, name), name)
        plan = self.reconstruction_plan
        request = plan.worker_request
        source = plan.source_evidence
        expected = (
            (self.repository_id, source.repository_id),
            (self.worker_request_digest, request.request_digest),
            (
                self.blueprint_id,
                request.parsed_blueprint.blueprint.blueprint_id,
            ),
            (self.blueprint_digest, request.blueprint_digest),
            (self.slice_id, request.slice_blueprint.slice_id),
            (self.slice_digest, request.slice_digest),
            (self.attempt_id, request.attempt_id),
            (self.pinned_base_sha, plan.pinned_base_sha),
            (self.source_manifest_digest, source.manifest_sha256),
            (self.disposable_workspace_id, plan.disposable_workspace_id),
            (self.reconstruction_plan_digest, plan.plan_sha256),
            (self.materialization_mode, plan.materialization_mode),
            (self.content_manifest_digest, source.manifest_sha256),
        )
        if any(actual != wanted for actual, wanted in expected):
            raise RepositoryMaterializationError(
                "materialization source binding mismatch"
            )
        file_count = len(source.manifest_entries)
        total_bytes = sum(
            entry.size_bytes for entry in source.manifest_entries
        )
        if self.expected_file_count != file_count or (
            self.expected_total_bytes != total_bytes
        ):
            raise RepositoryMaterializationError(
                "materialization size evidence mismatch"
            )
        if (
            type(self.expected_file_count) is not int
            or type(self.expected_total_bytes) is not int
        ):
            raise RepositoryMaterializationError(
                "materialization size evidence is malformed"
            )
        if type(self.verification_requirements) is not tuple or (
            self.verification_requirements != VERIFICATION_REQUIREMENTS
        ):
            raise RepositoryMaterializationError(
                "materialization verification requirements are forged"
            )
        if self.policy_version != POLICY_VERSION:
            raise RepositoryMaterializationError(
                "materialization policy is unsupported"
            )
        if self.materialization_planned is not True or any(
            value is not False
            for value in (
                self.materialization_verified,
                self.materialization_performed,
                self.symlinks_allowed,
                self.git_directory_allowed,
                self.git_hooks_allowed,
                self.inherited_git_config_allowed,
                self.host_repository_reused,
                self.host_workspace_reused,
                self.launch_authorized,
            )
        ):
            raise RepositoryMaterializationError(
                "materialization contract overstates authority or state"
            )
        _sha256(self.contract_sha256, "materialization contract digest")
        if self.contract_sha256 != hashlib.sha256(
            self._payload()
        ).hexdigest():
            raise RepositoryMaterializationError(
                "materialization contract digest mismatch"
            )
        if len(self.canonical_bytes()) > MAX_CONTRACT_BYTES:
            raise RepositoryMaterializationError(
                "materialization contract exceeds byte bound"
            )

    def _body(self):
        return {
            "attempt_id": self.attempt_id,
            "blueprint_digest": self.blueprint_digest,
            "blueprint_id": self.blueprint_id,
            "content_manifest_digest": self.content_manifest_digest,
            "disposable_workspace_id": self.disposable_workspace_id,
            "expected_file_count": self.expected_file_count,
            "expected_total_bytes": self.expected_total_bytes,
            "git_directory_allowed": False,
            "git_hooks_allowed": False,
            "host_repository_reused": False,
            "host_workspace_reused": False,
            "inherited_git_config_allowed": False,
            "launch_authorized": False,
            "materialization_id": self.materialization_id,
            "materialization_mode": self.materialization_mode,
            "materialization_performed": False,
            "materialization_planned": True,
            "materialization_verified": False,
            "pinned_base_sha": self.pinned_base_sha,
            "policy_version": POLICY_VERSION,
            "reconstruction_plan_digest": self.reconstruction_plan_digest,
            "repository_id": self.repository_id,
            "slice_digest": self.slice_digest,
            "slice_id": self.slice_id,
            "source_manifest_digest": self.source_manifest_digest,
            "symlinks_allowed": False,
            "verification_requirements": list(VERIFICATION_REQUIREMENTS),
            "worker_request_digest": self.worker_request_digest,
        }

    def _payload(self):
        return _canonical(self._body())

    def canonical_bytes(self):
        value = self._body()
        value["contract_sha256"] = self.contract_sha256
        return _canonical(value)


def create_repository_materialization_contract(
    reconstruction_plan, materialization_id,
):
    if not isinstance(reconstruction_plan, DisposableRepositoryPlan):
        raise RepositoryMaterializationError("reconstruction plan is invalid")
    request = reconstruction_plan.worker_request
    source = reconstruction_plan.source_evidence
    values = {
        "reconstruction_plan": reconstruction_plan,
        "materialization_id": materialization_id,
        "repository_id": source.repository_id,
        "worker_request_digest": request.request_digest,
        "blueprint_id": request.parsed_blueprint.blueprint.blueprint_id,
        "blueprint_digest": request.blueprint_digest,
        "slice_id": request.slice_blueprint.slice_id,
        "slice_digest": request.slice_digest,
        "attempt_id": request.attempt_id,
        "pinned_base_sha": reconstruction_plan.pinned_base_sha,
        "source_manifest_digest": source.manifest_sha256,
        "disposable_workspace_id": (
            reconstruction_plan.disposable_workspace_id
        ),
        "reconstruction_plan_digest": reconstruction_plan.plan_sha256,
        "materialization_mode": reconstruction_plan.materialization_mode,
        "expected_file_count": len(source.manifest_entries),
        "expected_total_bytes": sum(
            entry.size_bytes for entry in source.manifest_entries
        ),
        "content_manifest_digest": source.manifest_sha256,
    }
    provisional = object.__new__(RepositoryMaterializationContract)
    for name, value in values.items():
        object.__setattr__(provisional, name, value)
    return RepositoryMaterializationContract(
        **values,
        contract_sha256=hashlib.sha256(provisional._payload()).hexdigest(),
    )


@dataclass(frozen=True)
class RepositoryMaterializationReceipt:
    contract: RepositoryMaterializationContract
    materialization_contract_digest: str
    reconstruction_plan_digest: str
    source_manifest_digest: str
    receipt_sha256: str
    status: str = "planned_unverified"
    materialization_planned: bool = True
    materialization_verified: bool = False
    materialization_performed: bool = False
    evidence_collected: bool = False
    launch_authorized: bool = False

    def __post_init__(self):
        if not isinstance(self.contract, RepositoryMaterializationContract):
            raise RepositoryMaterializationError(
                "materialization contract is invalid"
            )
        expected = (
            (
                self.materialization_contract_digest,
                self.contract.contract_sha256,
            ),
            (
                self.reconstruction_plan_digest,
                self.contract.reconstruction_plan_digest,
            ),
            (
                self.source_manifest_digest,
                self.contract.source_manifest_digest,
            ),
        )
        if any(actual != wanted for actual, wanted in expected):
            raise RepositoryMaterializationError(
                "materialization receipt binding mismatch"
            )
        if self.status != "planned_unverified":
            raise RepositoryMaterializationError(
                "materialization receipt status is unsupported"
            )
        if self.materialization_planned is not True or any(
            value is not False
            for value in (
                self.materialization_verified,
                self.materialization_performed,
                self.evidence_collected,
                self.launch_authorized,
            )
        ):
            raise RepositoryMaterializationError(
                "materialization receipt fabricates execution evidence"
            )
        _sha256(self.receipt_sha256, "materialization receipt digest")
        if self.receipt_sha256 != hashlib.sha256(self._payload()).hexdigest():
            raise RepositoryMaterializationError(
                "materialization receipt digest mismatch"
            )
        if len(self.canonical_bytes()) > MAX_CONTRACT_BYTES:
            raise RepositoryMaterializationError(
                "materialization receipt exceeds byte bound"
            )

    def _body(self):
        return {
            "evidence_collected": False,
            "launch_authorized": False,
            "materialization_contract_digest": (
                self.materialization_contract_digest
            ),
            "materialization_performed": False,
            "materialization_planned": True,
            "materialization_verified": False,
            "reconstruction_plan_digest": self.reconstruction_plan_digest,
            "source_manifest_digest": self.source_manifest_digest,
            "status": "planned_unverified",
        }

    def _payload(self):
        return _canonical(self._body())

    def canonical_bytes(self):
        value = self._body()
        value["receipt_sha256"] = self.receipt_sha256
        return _canonical(value)


def create_planned_materialization_receipt(contract):
    if not isinstance(contract, RepositoryMaterializationContract):
        raise RepositoryMaterializationError(
            "materialization contract is invalid"
        )
    values = {
        "contract": contract,
        "materialization_contract_digest": contract.contract_sha256,
        "reconstruction_plan_digest": contract.reconstruction_plan_digest,
        "source_manifest_digest": contract.source_manifest_digest,
    }
    provisional = object.__new__(RepositoryMaterializationReceipt)
    for name, value in values.items():
        object.__setattr__(provisional, name, value)
    return RepositoryMaterializationReceipt(
        **values,
        receipt_sha256=hashlib.sha256(provisional._payload()).hexdigest(),
    )
