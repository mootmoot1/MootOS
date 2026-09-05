"""Bounded worker-artifact intake and untrusted quarantine evidence.

This module scans only a supervisor-owned staging root.  It neither executes
workers nor promotes their output: a quarantine package remains untrusted and
is merely eligible for a later, independent verification boundary.
"""

import hashlib
import json
import os
import re
import stat
from dataclasses import dataclass, field, replace
from pathlib import Path

from .paths import PathCanonicalizationError, canonicalize_repo_path
from .text_safety import utf8_length
from .worker_runtime import (
    WorkerExecutionReceipt,
    WorkerRuntimeError,
)


class WorkerArtifactError(ValueError):
    """Raised when artifact evidence cannot be safely admitted."""


POLICY_VERSION = "cb-worker-artifact-v1"
ARTIFACT_INTAKE_ROOT = Path(
    "/private/tmp/mootos-continuous-builder-artifact-intake"
)
MAX_ARTIFACTS = 256
MAX_ARTIFACT_BYTES = 1024 * 1024
MAX_TOTAL_ARTIFACT_BYTES = 8 * 1024 * 1024
MAX_PATH_BYTES = 1024
MAX_RECEIPT_BYTES = 256 * 1024
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SCAN_TOKEN = object()
_SECRET_PATTERNS = (
    (
        "private_key_material",
        re.compile(br"-----BEGIN (?:[A-Z0-9 ]+ )?PRIVATE KEY-----"),
    ),
    ("github_token", re.compile(br"\bgh[pousr]_[A-Za-z0-9]{20,}\b")),
    ("aws_access_key", re.compile(br"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b")),
    (
        "authorization_bearer",
        re.compile(
            br"(?i)\bauthorization\s*:\s*bearer\s*"
            br"[A-Za-z0-9._~+/=-]{8,}"
        ),
    ),
    (
        "credential_assignment",
        re.compile(
            br"(?i)\b(?:api[_-]?key|access[_-]?token|password|passwd|secret|"
            br"aws_secret_access_key)\s*[:=]\s*[\x22\x27]?"
            br"[A-Za-z0-9._~+/=-]{8,}"
        ),
    ),
)
_SENSITIVE_NAME = re.compile(
    r"(?i)(?:^|[/._-])(?:credentials?|id_rsa|id_ed25519|private[_-]?key|"
    r"secrets?|tokens?|passwords?)(?:$|[._-])"
)


def _canonical(value):
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")


def _digest(value):
    return hashlib.sha256(value).hexdigest()


def _sha256(value, name):
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise WorkerArtifactError(f"{name} is malformed")


def _validate_execution(receipt):
    if not isinstance(receipt, WorkerExecutionReceipt):
        raise WorkerArtifactError("worker execution receipt is invalid")
    try:
        replace(receipt.materialization_receipt)
        replace(receipt.enforcement_evidence)
        replace(receipt)
    except WorkerRuntimeError as error:
        raise WorkerArtifactError(
            "worker execution receipt failed authoritative validation"
        ) from error
    materialization = receipt.materialization_receipt
    evidence = receipt.enforcement_evidence
    expected = (
        (receipt.request_digest, materialization.worker_request_digest),
        (receipt.attempt_id, materialization.attempt_id),
        (
            receipt.materialization_receipt_digest,
            materialization.receipt_sha256,
        ),
        (
            receipt.materialization_receipt_digest,
            evidence.materialization_receipt_digest,
        ),
        (receipt.enforcement_evidence_digest, evidence.evidence_sha256),
        (receipt.policy_digest, evidence.policy_digest),
    )
    if any(actual != wanted for actual, wanted in expected):
        raise WorkerArtifactError("artifact execution binding mismatch")
    if receipt.execution_performed is not True or any(
        value is not False
        for value in (
            receipt.worker_output_trusted,
            receipt.result_verified,
            receipt.patch_verified,
            receipt.publication_authorized,
            receipt.queue_transition_authorized,
            receipt.github_authorized,
        )
    ):
        raise WorkerArtifactError(
            "execution receipt overstates artifact trust"
        )


@dataclass(frozen=True)
class ArtifactInventoryEntry:
    relative_path: str
    artifact_type: str
    size_bytes: int
    content_sha256: str

    def __post_init__(self):
        try:
            canonical = canonicalize_repo_path(self.relative_path)
        except PathCanonicalizationError as error:
            raise WorkerArtifactError("artifact path is unsafe") from error
        if canonical != self.relative_path or (
            utf8_length(canonical) > MAX_PATH_BYTES
        ):
            raise WorkerArtifactError("artifact path is not canonical")
        if self.artifact_type != "regular_file":
            raise WorkerArtifactError("artifact type is unsupported")
        if type(self.size_bytes) is not int or not (
            0 <= self.size_bytes <= MAX_ARTIFACT_BYTES
        ):
            raise WorkerArtifactError("artifact size exceeds bound")
        _sha256(self.content_sha256, "artifact content digest")

    def to_dict(self):
        return {
            "artifact_type": self.artifact_type,
            "content_sha256": self.content_sha256,
            "relative_path": self.relative_path,
            "size_bytes": self.size_bytes,
        }


@dataclass(frozen=True)
class SecretFinding:
    category: str
    relative_path: str
    artifact_sha256: str

    def __post_init__(self):
        if self.category not in {
            "authorization_bearer",
            "aws_access_key",
            "credential_assignment",
            "github_token",
            "private_key_material",
            "sensitive_filename",
        }:
            raise WorkerArtifactError("secret finding category is unsupported")
        try:
            canonical = canonicalize_repo_path(self.relative_path)
        except PathCanonicalizationError as error:
            raise WorkerArtifactError(
                "secret finding path is unsafe"
            ) from error
        if canonical != self.relative_path:
            raise WorkerArtifactError("secret finding path is not canonical")
        _sha256(self.artifact_sha256, "secret finding artifact digest")

    def to_dict(self):
        return {
            "artifact_sha256": self.artifact_sha256,
            "category": self.category,
            "relative_path": self.relative_path,
        }


@dataclass(frozen=True)
class QuarantinedArtifactPackage:
    execution_receipt_digest: str
    attempt_id: str
    request_digest: str
    execution_id: str
    policy_digest: str
    materialization_receipt_digest: str
    workspace_identity: str
    inventory: tuple
    total_artifact_count: int
    total_artifact_bytes: int
    inventory_sha256: str
    package_sha256: str
    policy_version: str = POLICY_VERSION
    artifact_content_trusted: bool = False
    patch_verified: bool = False
    result_verified: bool = False
    externally_verified: bool = False
    publication_authorized: bool = False
    queue_transition_authorized: bool = False
    github_authorized: bool = False
    _scan_token: object = field(default=None, repr=False, compare=False)

    def __post_init__(self):
        if self._scan_token is not _SCAN_TOKEN:
            raise WorkerArtifactError(
                "quarantine package requires trusted observed evidence"
            )
        for name in (
            "execution_receipt_digest", "request_digest", "policy_digest",
            "materialization_receipt_digest", "workspace_identity",
            "inventory_sha256", "package_sha256",
        ):
            _sha256(getattr(self, name), name)
        if type(self.inventory) is not tuple or any(
            not isinstance(entry, ArtifactInventoryEntry)
            for entry in self.inventory
        ):
            raise WorkerArtifactError("artifact inventory is malformed")
        paths = tuple(entry.relative_path for entry in self.inventory)
        if paths != tuple(sorted(paths)) or len(paths) != len(set(paths)):
            raise WorkerArtifactError("artifact inventory is not canonical")
        if len({path.casefold() for path in paths}) != len(paths):
            raise WorkerArtifactError("artifact paths collide by case")
        if self.total_artifact_count != len(self.inventory) or (
            self.total_artifact_bytes
            != sum(entry.size_bytes for entry in self.inventory)
        ):
            raise WorkerArtifactError("artifact inventory totals mismatch")
        if self.total_artifact_count > MAX_ARTIFACTS or (
            self.total_artifact_bytes > MAX_TOTAL_ARTIFACT_BYTES
        ):
            raise WorkerArtifactError("artifact inventory exceeds bound")
        if self.inventory_sha256 != _digest(
            _canonical([entry.to_dict() for entry in self.inventory])
        ):
            raise WorkerArtifactError("artifact inventory digest mismatch")
        if self.policy_version != POLICY_VERSION or any(
            value is not False
            for value in (
                self.artifact_content_trusted,
                self.patch_verified,
                self.result_verified,
                self.externally_verified,
                self.publication_authorized,
                self.queue_transition_authorized,
                self.github_authorized,
            )
        ):
            raise WorkerArtifactError("quarantine package promotes authority")
        if self.package_sha256 != _digest(self._payload()):
            raise WorkerArtifactError("quarantine package digest mismatch")
        if len(self.canonical_bytes()) > MAX_RECEIPT_BYTES:
            raise WorkerArtifactError("quarantine package exceeds byte bound")

    def _body(self):
        return {
            "artifact_content_trusted": False,
            "attempt_id": self.attempt_id,
            "execution_id": self.execution_id,
            "execution_receipt_digest": self.execution_receipt_digest,
            "externally_verified": False,
            "github_authorized": False,
            "inventory": [entry.to_dict() for entry in self.inventory],
            "inventory_sha256": self.inventory_sha256,
            "materialization_receipt_digest": (
                self.materialization_receipt_digest
            ),
            "patch_verified": False,
            "policy_digest": self.policy_digest,
            "policy_version": POLICY_VERSION,
            "publication_authorized": False,
            "queue_transition_authorized": False,
            "request_digest": self.request_digest,
            "result_verified": False,
            "status": "quarantined_untrusted",
            "total_artifact_bytes": self.total_artifact_bytes,
            "total_artifact_count": self.total_artifact_count,
            "workspace_identity": self.workspace_identity,
        }

    def _payload(self):
        return _canonical(self._body())

    def canonical_bytes(self):
        value = self._body()
        value["package_sha256"] = self.package_sha256
        return _canonical(value)


@dataclass(frozen=True)
class ArtifactIntakeReceipt:
    execution_receipt_digest: str
    attempt_id: str
    request_digest: str
    execution_id: str
    policy_digest: str
    materialization_receipt_digest: str
    workspace_identity: str
    status: str
    inventory_sha256: str
    total_artifact_count: int
    total_artifact_bytes: int
    findings: tuple
    quarantine_package_digest: str
    receipt_sha256: str
    scan_performed: bool = True
    suspicious_secret_material_detected: bool = False
    scan_passed: bool = True
    quarantine_package_created: bool = True
    artifact_intake_completed: bool = True
    artifact_intake_completed_before_destructive_teardown: bool = False
    worker_container_cleanup_confirmed: bool = False
    execution_workspace_cleanup_confirmed: bool = False
    teardown_uncertain: bool = True
    artifact_content_trusted: bool = False
    patch_verified: bool = False
    result_verified: bool = False
    externally_verified: bool = False
    publication_authorized: bool = False
    queue_transition_authorized: bool = False
    github_authorized: bool = False
    _scan_token: object = field(default=None, repr=False, compare=False)

    def __post_init__(self):
        if self._scan_token is not _SCAN_TOKEN:
            raise WorkerArtifactError(
                "artifact receipt requires trusted observed evidence"
            )
        for name in (
            "execution_receipt_digest", "request_digest", "policy_digest",
            "materialization_receipt_digest", "workspace_identity",
            "inventory_sha256", "receipt_sha256",
        ):
            _sha256(getattr(self, name), name)
        if self.quarantine_package_digest:
            _sha256(
                self.quarantine_package_digest,
                "quarantine package digest",
            )
        if self.status not in {
            "quarantined_untrusted", "rejected_secret_material"
        } or type(self.findings) is not tuple or any(
            not isinstance(finding, SecretFinding) for finding in self.findings
        ):
            raise WorkerArtifactError("artifact intake status is malformed")
        detected = bool(self.findings)
        clean = self.status == "quarantined_untrusted"
        cleanup = not self.teardown_uncertain
        if (
            self.scan_performed is not True
            or self.suspicious_secret_material_detected is not detected
            or self.scan_passed is not clean
            or self.quarantine_package_created is not clean
            or self.artifact_intake_completed is not True
            or self.artifact_intake_completed_before_destructive_teardown
            is not False
            or self.worker_container_cleanup_confirmed is not cleanup
            or self.execution_workspace_cleanup_confirmed is not cleanup
            or bool(self.quarantine_package_digest) is not clean
        ):
            raise WorkerArtifactError("artifact intake evidence is forged")
        if any(
            value is not False
            for value in (
                self.artifact_content_trusted,
                self.patch_verified,
                self.result_verified,
                self.externally_verified,
                self.publication_authorized,
                self.queue_transition_authorized,
                self.github_authorized,
            )
        ):
            raise WorkerArtifactError("artifact intake promotes authority")
        if self.receipt_sha256 != _digest(self._payload()):
            raise WorkerArtifactError("artifact intake digest mismatch")
        if len(self.canonical_bytes()) > MAX_RECEIPT_BYTES:
            raise WorkerArtifactError("artifact intake receipt exceeds bound")

    def _body(self):
        return {
            "artifact_content_trusted": False,
            "artifact_intake_completed": True,
            "artifact_intake_completed_before_destructive_teardown": False,
            "attempt_id": self.attempt_id,
            "execution_id": self.execution_id,
            "execution_receipt_digest": self.execution_receipt_digest,
            "execution_workspace_cleanup_confirmed": (
                self.execution_workspace_cleanup_confirmed
            ),
            "externally_verified": False,
            "findings": [finding.to_dict() for finding in self.findings],
            "github_authorized": False,
            "inventory_sha256": self.inventory_sha256,
            "materialization_receipt_digest": (
                self.materialization_receipt_digest
            ),
            "patch_verified": False,
            "policy_digest": self.policy_digest,
            "publication_authorized": False,
            "quarantine_package_created": self.quarantine_package_created,
            "quarantine_package_digest": self.quarantine_package_digest,
            "queue_transition_authorized": False,
            "request_digest": self.request_digest,
            "result_verified": False,
            "scan_passed": self.scan_passed,
            "scan_performed": True,
            "status": self.status,
            "suspicious_secret_material_detected": (
                self.suspicious_secret_material_detected
            ),
            "teardown_uncertain": self.teardown_uncertain,
            "total_artifact_bytes": self.total_artifact_bytes,
            "total_artifact_count": self.total_artifact_count,
            "worker_container_cleanup_confirmed": (
                self.worker_container_cleanup_confirmed
            ),
            "workspace_identity": self.workspace_identity,
        }

    def _payload(self):
        return _canonical(self._body())

    def canonical_bytes(self):
        value = self._body()
        value["receipt_sha256"] = self.receipt_sha256
        return _canonical(value)


@dataclass(frozen=True)
class ArtifactIntakeResult:
    receipt: ArtifactIntakeReceipt
    quarantine_package: object
    _artifact_payloads: tuple = field(repr=False, compare=False)
    _scan_token: object = field(default=None, repr=False, compare=False)

    def __post_init__(self):
        if self._scan_token is not _SCAN_TOKEN:
            raise WorkerArtifactError(
                "artifact intake result requires trusted observed evidence"
            )
        if not isinstance(self.receipt, ArtifactIntakeReceipt):
            raise WorkerArtifactError("artifact intake result is malformed")
        if self.receipt.scan_passed:
            if not isinstance(
                self.quarantine_package, QuarantinedArtifactPackage
            ):
                raise WorkerArtifactError("quarantine package is missing")
            if (
                self.receipt.quarantine_package_digest
                != self.quarantine_package.package_sha256
            ):
                raise WorkerArtifactError("quarantine binding mismatch")
            if type(self._artifact_payloads) is not tuple or len(
                self._artifact_payloads
            ) != len(self.quarantine_package.inventory):
                raise WorkerArtifactError("quarantine payloads are malformed")
            expected = {
                entry.relative_path: (entry.size_bytes, entry.content_sha256)
                for entry in self.quarantine_package.inventory
            }
            observed = {}
            for path, content in self._artifact_payloads:
                if not isinstance(path, str) or not isinstance(content, bytes):
                    raise WorkerArtifactError(
                        "quarantine payload is malformed"
                    )
                observed[path] = (len(content), _digest(content))
            if observed != expected or len(observed) != len(
                self._artifact_payloads
            ):
                raise WorkerArtifactError(
                    "quarantine payload binding mismatch"
                )
        elif self.quarantine_package is not None or self._artifact_payloads:
            raise WorkerArtifactError("rejected artifacts must not be exposed")


def intake_worker_artifacts(execution_receipt, artifact_root):
    """Observe a bounded staging root and return untrusted quarantine data."""
    _validate_execution(execution_receipt)
    root = Path(artifact_root)
    allowed = ARTIFACT_INTAKE_ROOT
    if not root.is_absolute() or root.parent != allowed or (
        root.name != execution_receipt.execution_id
    ):
        raise WorkerArtifactError("artifact root is outside intake authority")
    if allowed.is_symlink() or root.is_symlink():
        raise WorkerArtifactError("artifact root must not be a symlink")
    try:
        allowed_resolved = allowed.resolve(strict=True)
        root_resolved = root.resolve(strict=True)
    except OSError as error:
        raise WorkerArtifactError("artifact root is unavailable") from error
    if root_resolved.parent != allowed_resolved:
        raise WorkerArtifactError("artifact root escapes intake authority")

    observed = []
    payloads = []
    total_bytes = 0
    for path in root.rglob("*"):
        metadata = path.lstat()
        if stat.S_ISDIR(metadata.st_mode):
            continue
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
            raise WorkerArtifactError("artifact filesystem type is unsafe")
        try:
            relative = path.relative_to(root).as_posix()
            canonical = canonicalize_repo_path(relative)
        except (ValueError, PathCanonicalizationError) as error:
            raise WorkerArtifactError("artifact path escapes root") from error
        if canonical != relative or utf8_length(relative) > MAX_PATH_BYTES:
            raise WorkerArtifactError("artifact path is not canonical")
        try:
            path.resolve(strict=True).relative_to(root_resolved)
        except (OSError, ValueError) as error:
            raise WorkerArtifactError("artifact path escapes root") from error
        if metadata.st_size > MAX_ARTIFACT_BYTES:
            raise WorkerArtifactError("artifact exceeds individual size bound")
        content = _read_regular_artifact(path, metadata)
        size = len(content)
        if size > MAX_ARTIFACT_BYTES:
            raise WorkerArtifactError("artifact exceeds individual size bound")
        total_bytes += size
        if total_bytes > MAX_TOTAL_ARTIFACT_BYTES:
            raise WorkerArtifactError("artifact total bytes exceed bound")
        entry = ArtifactInventoryEntry(
            relative, "regular_file", size, _digest(content)
        )
        observed.append(entry)
        payloads.append((relative, content))
        if len(observed) > MAX_ARTIFACTS:
            raise WorkerArtifactError("artifact count exceeds bound")

    observed.sort(key=lambda entry: entry.relative_path)
    payloads.sort(key=lambda item: item[0])
    paths = tuple(entry.relative_path for entry in observed)
    if len(paths) != len(set(paths)) or (
        len({path.casefold() for path in paths}) != len(paths)
    ):
        raise WorkerArtifactError("artifact paths collide")
    inventory = tuple(observed)
    inventory_digest = _digest(
        _canonical([entry.to_dict() for entry in inventory])
    )
    findings = _scan_secrets(inventory, tuple(payloads))
    package = None
    if not findings:
        body = _package_values(execution_receipt, inventory, inventory_digest)
        provisional = object.__new__(QuarantinedArtifactPackage)
        for name, value in body.items():
            object.__setattr__(provisional, name, value)
        object.__setattr__(provisional, "policy_version", POLICY_VERSION)
        package = QuarantinedArtifactPackage(
            **body,
            package_sha256=_digest(provisional._payload()),
            _scan_token=_SCAN_TOKEN,
        )
    receipt = _intake_receipt(
        execution_receipt, inventory, inventory_digest, findings, package
    )
    safe_payloads = tuple(payloads) if package is not None else ()
    return ArtifactIntakeResult(
        receipt, package, safe_payloads, _scan_token=_SCAN_TOKEN
    )


def _read_regular_artifact(path, observed_metadata):
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
        try:
            opened = os.fstat(descriptor)
            if (
                not stat.S_ISREG(opened.st_mode)
                or opened.st_nlink != 1
                or opened.st_dev != observed_metadata.st_dev
                or opened.st_ino != observed_metadata.st_ino
            ):
                raise WorkerArtifactError(
                    "artifact changed during structural intake"
                )
            chunks = []
            remaining = MAX_ARTIFACT_BYTES + 1
            while remaining:
                chunk = os.read(descriptor, min(65536, remaining))
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
            content = b"".join(chunks)
            if len(content) > MAX_ARTIFACT_BYTES or len(content) != (
                opened.st_size
            ):
                raise WorkerArtifactError(
                    "artifact changed or exceeds its size bound"
                )
            return content
        finally:
            os.close(descriptor)
    except WorkerArtifactError:
        raise
    except OSError as error:
        raise WorkerArtifactError(
            "artifact could not be safely read"
        ) from error


def _scan_secrets(inventory, payloads):
    by_path = {entry.relative_path: entry for entry in inventory}
    findings = set()
    for relative_path, content in payloads:
        entry = by_path[relative_path]
        if _SENSITIVE_NAME.search(relative_path):
            findings.add(
                ("sensitive_filename", relative_path, entry.content_sha256)
            )
        for category, pattern in _SECRET_PATTERNS:
            if pattern.search(content):
                findings.add((category, relative_path, entry.content_sha256))
    return tuple(
        SecretFinding(*value)
        for value in sorted(findings, key=lambda item: (item[1], item[0]))
    )


def _package_values(receipt, inventory, inventory_digest):
    materialization = receipt.materialization_receipt
    return {
        "execution_receipt_digest": receipt.receipt_sha256,
        "attempt_id": receipt.attempt_id,
        "request_digest": receipt.request_digest,
        "execution_id": receipt.execution_id,
        "policy_digest": receipt.policy_digest,
        "materialization_receipt_digest": (
            receipt.materialization_receipt_digest
        ),
        "workspace_identity": materialization.workspace_instance_digest,
        "inventory": inventory,
        "total_artifact_count": len(inventory),
        "total_artifact_bytes": sum(entry.size_bytes for entry in inventory),
        "inventory_sha256": inventory_digest,
    }


def _intake_receipt(receipt, inventory, inventory_digest, findings, package):
    clean = package is not None
    cleanup_confirmed = (
        receipt.cleanup_confirmed and not receipt.termination_uncertain
    )
    values = {
        "execution_receipt_digest": receipt.receipt_sha256,
        "attempt_id": receipt.attempt_id,
        "request_digest": receipt.request_digest,
        "execution_id": receipt.execution_id,
        "policy_digest": receipt.policy_digest,
        "materialization_receipt_digest": (
            receipt.materialization_receipt_digest
        ),
        "workspace_identity": (
            receipt.materialization_receipt.workspace_instance_digest
        ),
        "status": (
            "quarantined_untrusted" if clean
            else "rejected_secret_material"
        ),
        "inventory_sha256": inventory_digest,
        "total_artifact_count": len(inventory),
        "total_artifact_bytes": sum(entry.size_bytes for entry in inventory),
        "findings": findings,
        "quarantine_package_digest": (
            package.package_sha256 if package is not None else ""
        ),
        "scan_performed": True,
        "suspicious_secret_material_detected": bool(findings),
        "scan_passed": clean,
        "quarantine_package_created": clean,
        "artifact_intake_completed": True,
        "artifact_intake_completed_before_destructive_teardown": False,
        "worker_container_cleanup_confirmed": cleanup_confirmed,
        "execution_workspace_cleanup_confirmed": cleanup_confirmed,
        "teardown_uncertain": not cleanup_confirmed,
    }
    provisional = object.__new__(ArtifactIntakeReceipt)
    for name, value in values.items():
        object.__setattr__(provisional, name, value)
    return ArtifactIntakeReceipt(
        **values,
        receipt_sha256=_digest(provisional._payload()),
        _scan_token=_SCAN_TOKEN,
    )
