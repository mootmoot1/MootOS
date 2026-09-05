"""Bounded stdout artifact transport for one contained worker execution.

The worker may propose artifact bytes through one strict JSON envelope on stdout.
This module never trusts those bytes. It proves only that the exact staged bytes
came from the exact stdout captured by a trusted WorkerExecutionReceipt, then
hands the staged files to the existing CB-023 quarantine scanner.

The current bridge is intentionally tiny: the complete stdout must fit inside the
trusted receipt sample. Larger artifact transport belongs in a later runtime
contract rather than silently weakening the receipt boundary.
"""

import base64
import binascii
import hashlib
import json
import os
import re
import shutil
import stat
from dataclasses import dataclass, field, replace
from pathlib import Path

from .paths import PathCanonicalizationError, canonicalize_repo_path
from .worker_artifact import (
    ARTIFACT_INTAKE_ROOT,
    MAX_ARTIFACTS,
    MAX_ARTIFACT_BYTES,
    MAX_PATH_BYTES,
    MAX_TOTAL_ARTIFACT_BYTES,
    ArtifactIntakeResult,
    intake_worker_artifacts,
)
from .worker_runtime import WorkerExecutionReceipt, WorkerRuntimeError


class ArtifactOutputError(ValueError):
    """Raised when stdout cannot establish bounded artifact provenance."""


PROTOCOL_VERSION = "mootos-artifact-output-v1"
MAX_ENVELOPE_BYTES = 4096
MAX_RECEIPT_BYTES = 64 * 1024
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_PROVENANCE_TOKEN = object()


def _canonical(value):
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")


def _digest(value):
    return hashlib.sha256(value).hexdigest()


def _sha256(value, label):
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise ArtifactOutputError(f"{label} is malformed")


def _validate_execution(receipt):
    if not isinstance(receipt, WorkerExecutionReceipt):
        raise ArtifactOutputError("worker execution receipt is invalid")
    try:
        replace(receipt.materialization_receipt)
        replace(receipt.enforcement_evidence)
        replace(receipt)
    except WorkerRuntimeError as error:
        raise ArtifactOutputError(
            "worker execution receipt failed authoritative validation"
        ) from error
    if receipt.execution_performed is not True:
        raise ArtifactOutputError("worker execution did not occur")
    if receipt.termination_uncertain:
        raise ArtifactOutputError("uncertain execution cannot export artifacts")
    if receipt.stdout_size <= 0 or receipt.stdout_size > MAX_ENVELOPE_BYTES:
        raise ArtifactOutputError("worker artifact envelope exceeds transport bound")
    raw = receipt.stdout_sample.encode("utf-8")
    if len(raw) != receipt.stdout_size:
        raise ArtifactOutputError(
            "trusted stdout sample does not contain the complete output"
        )
    if _digest(raw) != receipt.stdout_sha256:
        raise ArtifactOutputError("trusted stdout digest does not match sample")
    return raw


def _decode_envelope(raw, receipt):
    if len(raw) > MAX_ENVELOPE_BYTES or not raw.endswith(b"\n"):
        raise ArtifactOutputError("artifact envelope framing is invalid")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ArtifactOutputError("artifact envelope is malformed") from error
    if not isinstance(value, dict) or set(value) != {
        "artifacts",
        "attempt_id",
        "protocol",
        "request_digest",
        "result_verified",
    }:
        raise ArtifactOutputError("artifact envelope fields are not exact")
    if value["protocol"] != PROTOCOL_VERSION:
        raise ArtifactOutputError("artifact protocol version is unsupported")
    if value["attempt_id"] != receipt.attempt_id or (
        value["request_digest"] != receipt.request_digest
    ):
        raise ArtifactOutputError("artifact envelope execution binding mismatch")
    if value["result_verified"] is not False:
        raise ArtifactOutputError("worker artifact envelope overstates verification")
    artifacts = value["artifacts"]
    if not isinstance(artifacts, list) or not (0 < len(artifacts) <= MAX_ARTIFACTS):
        raise ArtifactOutputError("artifact envelope count is invalid")

    decoded = []
    total = 0
    seen = set()
    seen_folded = set()
    for item in artifacts:
        if not isinstance(item, dict) or set(item) != {
            "content_base64", "content_sha256", "path"
        }:
            raise ArtifactOutputError("artifact entry fields are not exact")
        path = item["path"]
        if not isinstance(path, str):
            raise ArtifactOutputError("artifact path is malformed")
        try:
            canonical = canonicalize_repo_path(path)
        except PathCanonicalizationError as error:
            raise ArtifactOutputError("artifact path is unsafe") from error
        if canonical != path or len(path.encode("utf-8")) > MAX_PATH_BYTES:
            raise ArtifactOutputError("artifact path is not canonical")
        folded = path.casefold()
        if path in seen or folded in seen_folded:
            raise ArtifactOutputError("artifact paths collide")
        seen.add(path)
        seen_folded.add(folded)
        encoded = item["content_base64"]
        expected_digest = item["content_sha256"]
        if not isinstance(encoded, str):
            raise ArtifactOutputError("artifact payload metadata is malformed")
        _sha256(expected_digest, "artifact payload digest")
        try:
            content = base64.b64decode(encoded.encode("ascii"), validate=True)
        except (UnicodeEncodeError, binascii.Error) as error:
            raise ArtifactOutputError("artifact payload encoding is invalid") from error
        if len(content) > MAX_ARTIFACT_BYTES:
            raise ArtifactOutputError("artifact payload exceeds individual bound")
        if _digest(content) != expected_digest:
            raise ArtifactOutputError("artifact payload digest mismatch")
        total += len(content)
        if total > MAX_TOTAL_ARTIFACT_BYTES:
            raise ArtifactOutputError("artifact payloads exceed total bound")
        decoded.append((path, content, expected_digest))
    decoded.sort(key=lambda item: item[0])
    return tuple(decoded)


def _safe_root(root):
    allowed = ARTIFACT_INTAKE_ROOT
    if not allowed.is_absolute() or ".." in allowed.parts or allowed.is_symlink():
        raise ArtifactOutputError("artifact intake authority is unsafe")
    allowed.mkdir(mode=0o700, parents=True, exist_ok=True)
    if allowed.is_symlink():
        raise ArtifactOutputError("artifact intake authority is a symlink")
    metadata = allowed.stat()
    if metadata.st_uid != os.geteuid() or stat.S_IMODE(metadata.st_mode) & 0o077:
        raise ArtifactOutputError("artifact intake authority ownership is unsafe")
    root = Path(root)
    if not root.is_absolute() or root.parent != allowed:
        raise ArtifactOutputError("artifact staging root is outside authority")
    if root.exists() or root.is_symlink():
        raise ArtifactOutputError("artifact staging identity already exists")
    root.mkdir(mode=0o700, parents=False, exist_ok=False)
    return root


def _stage(root, artifacts):
    try:
        for relative, content, _ in artifacts:
            destination = root.joinpath(*relative.split("/"))
            current = root
            for part in relative.split("/")[:-1]:
                current = current / part
                if current.exists():
                    if current.is_symlink() or not current.is_dir():
                        raise ArtifactOutputError("artifact parent path is unsafe")
                else:
                    current.mkdir(mode=0o700, exist_ok=False)
            if destination.exists() or destination.is_symlink():
                raise ArtifactOutputError("artifact destination already exists")
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
            if hasattr(os, "O_NOFOLLOW"):
                flags |= os.O_NOFOLLOW
            descriptor = os.open(destination, flags, 0o600)
            try:
                with os.fdopen(descriptor, "wb", closefd=False) as stream:
                    stream.write(content)
                    stream.flush()
            finally:
                os.close(descriptor)
            metadata = destination.lstat()
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
                raise ArtifactOutputError("staged artifact filesystem type is unsafe")
            if destination.read_bytes() != content:
                raise ArtifactOutputError("staged artifact bytes changed")
    except Exception:
        if not _cleanup(root):
            raise ArtifactOutputError(
                "artifact staging cleanup failed after staging error"
            )
        raise


def _cleanup(root):
    try:
        if root.is_symlink():
            return False
        if root.exists():
            shutil.rmtree(root)
        return not root.exists() and not root.is_symlink()
    except OSError:
        return False


@dataclass(frozen=True)
class ArtifactOutputProvenanceReceipt:
    execution_receipt_digest: str
    execution_id: str
    container_id: str
    attempt_id: str
    request_digest: str
    policy_digest: str
    stdout_sha256: str
    stdout_size: int
    artifact_manifest: tuple
    artifact_manifest_sha256: str
    intake_receipt_digest: str
    quarantine_package_digest: str
    receipt_sha256: str
    protocol_version: str = PROTOCOL_VERSION
    stdout_complete_in_trusted_receipt: bool = True
    artifact_bytes_bound_to_execution_stdout: bool = True
    artifact_content_provenance_proven: bool = True
    worker_output_trusted: bool = False
    result_verified: bool = False
    patch_verified: bool = False
    publication_authorized: bool = False
    queue_transition_authorized: bool = False
    github_authorized: bool = False
    merge_authorized: bool = False
    _token: object = field(default=None, repr=False, compare=False)

    def __post_init__(self):
        if self._token is not _PROVENANCE_TOKEN:
            raise ArtifactOutputError("provenance receipt requires trusted evidence")
        if self.protocol_version != PROTOCOL_VERSION:
            raise ArtifactOutputError("provenance protocol version mismatch")
        for label, value in (
            ("execution receipt digest", self.execution_receipt_digest),
            ("request digest", self.request_digest),
            ("policy digest", self.policy_digest),
            ("stdout digest", self.stdout_sha256),
            ("artifact manifest digest", self.artifact_manifest_sha256),
            ("intake receipt digest", self.intake_receipt_digest),
        ):
            _sha256(value, label)
        if self.quarantine_package_digest:
            _sha256(self.quarantine_package_digest, "quarantine digest")
        if type(self.stdout_size) is not int or not (
            0 < self.stdout_size <= MAX_ENVELOPE_BYTES
        ):
            raise ArtifactOutputError("provenance stdout size is invalid")
        if type(self.artifact_manifest) is not tuple or not self.artifact_manifest:
            raise ArtifactOutputError("provenance manifest is malformed")
        if self.artifact_manifest_sha256 != _digest(
            _canonical(list(self.artifact_manifest))
        ):
            raise ArtifactOutputError("provenance manifest digest mismatch")
        if any(value is not True for value in (
            self.stdout_complete_in_trusted_receipt,
            self.artifact_bytes_bound_to_execution_stdout,
            self.artifact_content_provenance_proven,
        )):
            raise ArtifactOutputError("provenance receipt does not prove provenance")
        if any(value is not False for value in (
            self.worker_output_trusted,
            self.result_verified,
            self.patch_verified,
            self.publication_authorized,
            self.queue_transition_authorized,
            self.github_authorized,
            self.merge_authorized,
        )):
            raise ArtifactOutputError("provenance receipt promotes authority")
        if self.receipt_sha256 != _digest(self._payload()):
            raise ArtifactOutputError("provenance receipt digest mismatch")
        if len(self.canonical_bytes()) > MAX_RECEIPT_BYTES:
            raise ArtifactOutputError("provenance receipt exceeds byte bound")

    def _body(self):
        return {
            "artifact_bytes_bound_to_execution_stdout": True,
            "artifact_content_provenance_proven": True,
            "artifact_manifest": list(self.artifact_manifest),
            "artifact_manifest_sha256": self.artifact_manifest_sha256,
            "attempt_id": self.attempt_id,
            "container_id": self.container_id,
            "execution_id": self.execution_id,
            "execution_receipt_digest": self.execution_receipt_digest,
            "github_authorized": False,
            "intake_receipt_digest": self.intake_receipt_digest,
            "merge_authorized": False,
            "patch_verified": False,
            "policy_digest": self.policy_digest,
            "protocol_version": PROTOCOL_VERSION,
            "publication_authorized": False,
            "quarantine_package_digest": self.quarantine_package_digest,
            "queue_transition_authorized": False,
            "request_digest": self.request_digest,
            "result_verified": False,
            "stdout_complete_in_trusted_receipt": True,
            "stdout_sha256": self.stdout_sha256,
            "stdout_size": self.stdout_size,
            "worker_output_trusted": False,
        }

    def _payload(self):
        return _canonical(self._body())

    def canonical_bytes(self):
        value = self._body()
        value["receipt_sha256"] = self.receipt_sha256
        return _canonical(value)


@dataclass(frozen=True)
class ArtifactOutputProvenanceResult:
    provenance_receipt: ArtifactOutputProvenanceReceipt
    intake_result: ArtifactIntakeResult


def bridge_execution_stdout_to_artifact_intake(execution_receipt):
    """Stage exact bounded stdout artifacts, then run existing CB-023 intake."""
    raw = _validate_execution(execution_receipt)
    artifacts = _decode_envelope(raw, execution_receipt)
    root = ARTIFACT_INTAKE_ROOT / execution_receipt.execution_id
    root = _safe_root(root)
    result = None
    try:
        _stage(root, artifacts)
        intake = intake_worker_artifacts(execution_receipt, root)
        manifest = tuple(
            {
                "content_sha256": digest,
                "path": path,
                "size_bytes": len(content),
            }
            for path, content, digest in artifacts
        )
        if intake.receipt.total_artifact_count != len(manifest) or (
            intake.receipt.total_artifact_bytes
            != sum(item["size_bytes"] for item in manifest)
        ):
            raise ArtifactOutputError("CB-023 intake totals do not match stdout")
        if intake.quarantine_package is not None:
            observed = tuple(
                {
                    "content_sha256": entry.content_sha256,
                    "path": entry.relative_path,
                    "size_bytes": entry.size_bytes,
                }
                for entry in intake.quarantine_package.inventory
            )
            if observed != manifest:
                raise ArtifactOutputError("CB-023 quarantine differs from stdout")
        manifest_digest = _digest(_canonical(list(manifest)))
        values = {
            "execution_receipt_digest": execution_receipt.receipt_sha256,
            "execution_id": execution_receipt.execution_id,
            "container_id": execution_receipt.container_id,
            "attempt_id": execution_receipt.attempt_id,
            "request_digest": execution_receipt.request_digest,
            "policy_digest": execution_receipt.policy_digest,
            "stdout_sha256": execution_receipt.stdout_sha256,
            "stdout_size": execution_receipt.stdout_size,
            "artifact_manifest": manifest,
            "artifact_manifest_sha256": manifest_digest,
            "intake_receipt_digest": intake.receipt.receipt_sha256,
            "quarantine_package_digest": (
                intake.quarantine_package.package_sha256
                if intake.quarantine_package is not None else ""
            ),
        }
        provisional = object.__new__(ArtifactOutputProvenanceReceipt)
        for name, value in values.items():
            object.__setattr__(provisional, name, value)
        receipt = ArtifactOutputProvenanceReceipt(
            **values,
            receipt_sha256=_digest(provisional._payload()),
            _token=_PROVENANCE_TOKEN,
        )
        result = ArtifactOutputProvenanceResult(receipt, intake)
    finally:
        if not _cleanup(root):
            raise ArtifactOutputError("artifact staging cleanup is uncertain")
    return result
