"""Inert plans for reconstructing disposable repositories at pinned bases."""

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass

from .paths import PathCanonicalizationError, canonicalize_repo_path
from .text_safety import utf8_length
from .worker_request import FrozenWorkerRequest


class SandboxRepositoryError(ValueError):
    """Raised when disposable reconstruction cannot be safely described."""


POLICY_VERSION = "cb-sandbox-repository-v1"
MATERIALIZATION_MODES = ("verified_object_export", "verified_source_archive")
MAX_ENTRIES = 4096
MAX_FILE_BYTES = 64 * 1024 * 1024
MAX_TOTAL_BYTES = 512 * 1024 * 1024
MAX_PLAN_BYTES = 512 * 1024
_IDENTITY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_GIT_SHA = re.compile(r"^[0-9a-f]{40}$")


def _identity(value, name):
    if (
        not isinstance(value, str)
        or _IDENTITY.fullmatch(value or "") is None
        or utf8_length(value) > 256
    ):
        raise SandboxRepositoryError(f"{name} is malformed")
    return value


def _canonical(value):
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")


def _safe_manifest_path(value):
    try:
        canonical = canonicalize_repo_path(value)
    except PathCanonicalizationError as error:
        raise SandboxRepositoryError("manifest path is unsafe") from error
    if canonical != value:
        raise SandboxRepositoryError("manifest path is not canonical")
    parts = tuple(part.casefold() for part in canonical.split("/"))
    if ".git" in parts or ".gitmodules" in parts or (
        len(parts) >= 2 and parts[-2:] == ("hooks", "")
    ):
        raise SandboxRepositoryError("Git control metadata is forbidden")
    if any(part == "hooks" for part in parts[:-1]) and ".git" in parts:
        raise SandboxRepositoryError("Git hooks are forbidden")
    return canonical


@dataclass(frozen=True)
class RepositoryManifestEntry:
    path: str
    entry_type: str
    content_sha256: str
    size_bytes: int
    executable: bool = False

    def __post_init__(self):
        object.__setattr__(self, "path", _safe_manifest_path(self.path))
        if self.entry_type != "regular_file":
            raise SandboxRepositoryError(
                "only regular files may appear in reconstruction manifests"
            )
        if _SHA256.fullmatch(self.content_sha256 or "") is None:
            raise SandboxRepositoryError("file content digest is malformed")
        if type(self.size_bytes) is not int or not (
            0 <= self.size_bytes <= MAX_FILE_BYTES
        ):
            raise SandboxRepositoryError("file size is outside its bound")
        if type(self.executable) is not bool:
            raise SandboxRepositoryError("executable marker must be boolean")

    def to_dict(self):
        return {
            "content_sha256": self.content_sha256,
            "entry_type": self.entry_type,
            "executable": self.executable,
            "path": self.path,
            "size_bytes": self.size_bytes,
        }


def _manifest(entries):
    if not isinstance(entries, (list, tuple)):
        raise SandboxRepositoryError("manifest entries must be a collection")
    entries = tuple(entries)
    if not entries or len(entries) > MAX_ENTRIES or any(
        not isinstance(item, RepositoryManifestEntry) for item in entries
    ):
        raise SandboxRepositoryError(
            "manifest is empty, invalid, or excessive"
        )
    identities = tuple(
        unicodedata.normalize("NFKC", item.path).casefold()
        for item in entries
    )
    if len(identities) != len(set(identities)):
        raise SandboxRepositoryError("manifest paths collide")
    if sum(item.size_bytes for item in entries) > MAX_TOTAL_BYTES:
        raise SandboxRepositoryError("manifest total size exceeds its bound")
    return tuple(sorted(entries, key=lambda item: item.path))


def _manifest_digest(entries):
    return hashlib.sha256(_canonical([
        item.to_dict() for item in entries
    ])).hexdigest()


@dataclass(frozen=True)
class RepositorySourceEvidence:
    repository_id: str
    pinned_base_sha: str
    manifest_entries: tuple
    manifest_sha256: str
    source_evidence_sha256: str
    source_read_only: bool = True
    externally_attested: bool = False

    def __post_init__(self):
        object.__setattr__(
            self,
            "repository_id",
            _identity(self.repository_id, "repository ID"),
        )
        if _GIT_SHA.fullmatch(self.pinned_base_sha or "") is None:
            raise SandboxRepositoryError("pinned base SHA is malformed")
        entries = _manifest(self.manifest_entries)
        object.__setattr__(self, "manifest_entries", entries)
        if self.manifest_sha256 != _manifest_digest(entries):
            raise SandboxRepositoryError("manifest digest mismatch")
        if self.source_read_only is not True or (
            self.externally_attested is not False
        ):
            raise SandboxRepositoryError(
                "source evidence overstates authority"
            )
        if self.source_evidence_sha256 != hashlib.sha256(
            self._payload()
        ).hexdigest():
            raise SandboxRepositoryError("source evidence digest mismatch")

    def _body(self):
        return {
            "externally_attested": False,
            "manifest_entries": [
                item.to_dict() for item in self.manifest_entries
            ],
            "manifest_sha256": self.manifest_sha256,
            "pinned_base_sha": self.pinned_base_sha,
            "repository_id": self.repository_id,
            "source_read_only": True,
        }

    def _payload(self):
        return _canonical(self._body())

    def to_dict(self):
        value = self._body()
        value["source_evidence_sha256"] = self.source_evidence_sha256
        return value


def create_repository_source_evidence(
    repository_id, pinned_base_sha, manifest_entries,
):
    entries = _manifest(manifest_entries)
    manifest_sha256 = _manifest_digest(entries)
    provisional = object.__new__(RepositorySourceEvidence)
    values = {
        "repository_id": repository_id,
        "pinned_base_sha": pinned_base_sha,
        "manifest_entries": entries,
        "manifest_sha256": manifest_sha256,
        "source_read_only": True,
        "externally_attested": False,
    }
    for name, value in values.items():
        object.__setattr__(provisional, name, value)
    digest = hashlib.sha256(provisional._payload()).hexdigest()
    return RepositorySourceEvidence(
        **values, source_evidence_sha256=digest
    )


@dataclass(frozen=True)
class DisposableRepositoryPlan:
    worker_request: FrozenWorkerRequest
    source_evidence: RepositorySourceEvidence
    disposable_workspace_id: str
    materialization_mode: str
    request_digest: str
    blueprint_digest: str
    slice_digest: str
    scope_digest: str
    pinned_base_sha: str
    plan_sha256: str
    policy_version: str = POLICY_VERSION
    workspace_disposable: bool = True
    source_read_only: bool = True
    shared_git_directory: bool = False
    git_hooks_enabled: bool = False
    inherited_git_config: bool = False
    host_repository_writable: bool = False
    symlinks_allowed: bool = False
    host_workspace_reused: bool = False
    launch_authorized: bool = False
    materialized: bool = False

    def __post_init__(self):
        if not isinstance(self.worker_request, FrozenWorkerRequest):
            raise SandboxRepositoryError("worker request is invalid")
        if not isinstance(self.source_evidence, RepositorySourceEvidence):
            raise SandboxRepositoryError("repository source is invalid")
        workspace = _identity(
            self.disposable_workspace_id, "disposable workspace ID"
        )
        if not workspace.startswith("disposable-"):
            raise SandboxRepositoryError(
                "workspace is not explicitly disposable"
            )
        if self.materialization_mode not in MATERIALIZATION_MODES:
            raise SandboxRepositoryError("materialization mode is unsupported")
        request = self.worker_request
        expected = (
            (self.request_digest, request.request_digest),
            (self.blueprint_digest, request.blueprint_digest),
            (self.slice_digest, request.slice_digest),
            (self.scope_digest, request.scope_digest),
            (self.pinned_base_sha, request.job.base_sha),
            (self.pinned_base_sha, self.source_evidence.pinned_base_sha),
        )
        if any(actual != wanted for actual, wanted in expected):
            raise SandboxRepositoryError(
                "reconstruction source binding mismatch"
            )
        if self.policy_version != POLICY_VERSION:
            raise SandboxRepositoryError(
                "reconstruction policy version is unsupported"
            )
        required_true = (self.workspace_disposable, self.source_read_only)
        required_false = (
            self.shared_git_directory,
            self.git_hooks_enabled,
            self.inherited_git_config,
            self.host_repository_writable,
            self.symlinks_allowed,
            self.host_workspace_reused,
            self.launch_authorized,
            self.materialized,
        )
        if any(value is not True for value in required_true) or any(
            value is not False for value in required_false
        ):
            raise SandboxRepositoryError(
                "reconstruction plan violates disposable isolation"
            )
        if self.plan_sha256 != hashlib.sha256(self._payload()).hexdigest():
            raise SandboxRepositoryError("reconstruction plan digest mismatch")
        if len(self.canonical_bytes()) > MAX_PLAN_BYTES:
            raise SandboxRepositoryError(
                "reconstruction plan exceeds byte bound"
            )

    def _body(self):
        return {
            "blueprint_digest": self.blueprint_digest,
            "git_hooks_enabled": False,
            "host_repository_writable": False,
            "host_workspace_reused": False,
            "inherited_git_config": False,
            "launch_authorized": False,
            "materialization_mode": self.materialization_mode,
            "materialized": False,
            "pinned_base_sha": self.pinned_base_sha,
            "policy_version": self.policy_version,
            "repository_source": self.source_evidence.to_dict(),
            "request_digest": self.request_digest,
            "scope_digest": self.scope_digest,
            "shared_git_directory": False,
            "slice_digest": self.slice_digest,
            "source_read_only": True,
            "symlinks_allowed": False,
            "workspace_disposable": True,
            "disposable_workspace_id": self.disposable_workspace_id,
        }

    def _payload(self):
        return _canonical(self._body())

    def canonical_bytes(self):
        value = self._body()
        value["plan_sha256"] = self.plan_sha256
        return _canonical(value)


def create_disposable_repository_plan(
    worker_request, source_evidence, disposable_workspace_id,
    materialization_mode="verified_object_export",
):
    if not isinstance(worker_request, FrozenWorkerRequest):
        raise SandboxRepositoryError("worker request is invalid")
    if not isinstance(source_evidence, RepositorySourceEvidence):
        raise SandboxRepositoryError("repository source is invalid")
    values = {
        "worker_request": worker_request,
        "source_evidence": source_evidence,
        "disposable_workspace_id": disposable_workspace_id,
        "materialization_mode": materialization_mode,
        "request_digest": worker_request.request_digest,
        "blueprint_digest": worker_request.blueprint_digest,
        "slice_digest": worker_request.slice_digest,
        "scope_digest": worker_request.scope_digest,
        "pinned_base_sha": worker_request.job.base_sha,
        "policy_version": POLICY_VERSION,
        "workspace_disposable": True,
        "source_read_only": True,
        "shared_git_directory": False,
        "git_hooks_enabled": False,
        "inherited_git_config": False,
        "host_repository_writable": False,
        "symlinks_allowed": False,
        "host_workspace_reused": False,
        "launch_authorized": False,
        "materialized": False,
    }
    provisional = object.__new__(DisposableRepositoryPlan)
    for name, value in values.items():
        object.__setattr__(provisional, name, value)
    digest = hashlib.sha256(provisional._payload()).hexdigest()
    return DisposableRepositoryPlan(**values, plan_sha256=digest)
