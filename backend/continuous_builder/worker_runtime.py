"""Bounded Docker supervisor for one authorized offline fixture worker.

Docker control exists only in this host-side adapter.  Worker input cannot
select an executable, Docker option, mount, environment variable, network,
credential, or follow-on authority.
"""

import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping, Optional

from .docker_runtime_contract import ENTRYPOINT_ARGV
from .runtime_enforcement import (
    RuntimeCancellationSemantics,
    RuntimeExecutionHandleContract,
    RuntimeFoundationReadinessReceipt,
)
from .text_safety import utf8_length


class WorkerRuntimeError(RuntimeError):
    """Raised when exact CB-022 execution cannot be proven safely."""


POLICY_VERSION = "cb-worker-runtime-v1"
DOCKER_EXECUTABLES = (
    Path("/usr/local/bin/docker"),
    Path("/usr/bin/docker"),
)
RUNTIME_ROOT = Path("/var/tmp/mootos-continuous-builder")
DOCKER_HOME_ROOT = Path("/var/tmp/mootos-continuous-builder-docker-home")
CONTAINER_SOURCE = "/source"
CONTAINER_WORKSPACE = "/workspace"
CONTAINER_USER = "65532:65532"
FIXTURE_OUTPUT = "cb022-fixture-output.json"
MAX_COMMAND_BYTES = 1024 * 1024
MAX_SAMPLE_BYTES = 4096
MAX_RECEIPT_BYTES = 128 * 1024
_IDENTITY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@-]{0,255}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_CONTAINER_ID = re.compile(r"^[0-9a-f]{12,64}$")
_SENSITIVE_ENV = re.compile(
    r"(?i)(token|key|password|secret|auth|credential|cookie|session|ssh|aws|"
    r"github|gitlab|azure|gcp)"
)
_MATERIALIZATION_TOKEN = object()
_ENFORCEMENT_TOKEN = object()
_EXECUTION_RECEIPT_TOKEN = object()


def _identity(value, name):
    if (
        not isinstance(value, str)
        or _IDENTITY.fullmatch(value or "") is None
        or utf8_length(value) > 256
    ):
        raise WorkerRuntimeError(f"{name} is malformed")
    return value


def _sha256(value, name):
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise WorkerRuntimeError(f"{name} is malformed")
    return value


def _canonical(value):
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")


def _digest(value):
    return hashlib.sha256(value).hexdigest()


def _bounded_text(value):
    return value[:MAX_SAMPLE_BYTES].decode("utf-8", errors="replace")


@dataclass(frozen=True)
class _CommandResult:
    returncode: int
    stdout: bytes
    stderr: bytes

    def __post_init__(self):
        if type(self.returncode) is not int:
            raise WorkerRuntimeError("Docker return code is malformed")
        if not isinstance(self.stdout, bytes) or not isinstance(
            self.stderr, bytes
        ):
            raise WorkerRuntimeError("Docker output is malformed")
        if len(self.stdout) + len(self.stderr) > MAX_COMMAND_BYTES:
            raise WorkerRuntimeError("Docker command output exceeds bound")


class _DockerCli:
    """Fixed, argv-only Docker control for the trusted supervisor."""

    def __init__(self):
        paths = tuple(path for path in DOCKER_EXECUTABLES if path.is_file())
        if not paths:
            raise WorkerRuntimeError(
                "trusted Docker executable is unavailable"
            )
        self._executable = paths[0]
        docker_home, docker_config = _safe_docker_home()
        self._environment = {
            "HOME": str(docker_home),
            "DOCKER_CONFIG": str(docker_config),
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
            "PATH": "/usr/local/bin:/usr/bin:/bin",
        }

    def run(self, arguments, timeout):
        if type(arguments) is not tuple or any(
            not isinstance(value, str) for value in arguments
        ):
            raise WorkerRuntimeError(
                "Docker arguments must be a fixed argv tuple"
            )
        if type(timeout) not in (int, float) or timeout <= 0:
            raise WorkerRuntimeError("Docker timeout is invalid")
        argv = (str(self._executable),) + arguments
        try:
            completed = subprocess.run(
                argv,
                capture_output=True,
                check=False,
                env=self._environment,
                shell=False,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired as error:
            raise WorkerRuntimeError(
                "Docker supervisor command timed out"
            ) from error
        result = _CommandResult(
            completed.returncode, completed.stdout, completed.stderr
        )
        return result


@dataclass(frozen=True)
class VerifiedMaterializationReceipt:
    materialization_id: str
    materialization_contract_digest: str
    reconstruction_plan_digest: str
    source_manifest_digest: str
    worker_request_digest: str
    attempt_id: str
    pinned_base_sha: str
    workspace_instance_digest: str
    observed_manifest_digest: str
    observed_file_count: int
    observed_total_bytes: int
    receipt_sha256: str
    materialization_performed: bool = True
    materialization_verified: bool = True
    exact_manifest_match: bool = True
    no_extra_files: bool = True
    no_symlinks: bool = True
    no_path_escape: bool = True
    source_read_only: bool = True
    workspace_disposable: bool = True
    host_repository_reused: bool = False
    launch_authorized: bool = False
    _verification_token: object = field(
        default=None, repr=False, compare=False
    )

    def __post_init__(self):
        if self._verification_token is not _MATERIALIZATION_TOKEN:
            raise WorkerRuntimeError(
                "verified materialization requires trusted observed evidence"
            )
        _identity(self.materialization_id, "materialization ID")
        _identity(self.attempt_id, "attempt ID")
        for name in (
            "materialization_contract_digest",
            "reconstruction_plan_digest",
            "source_manifest_digest",
            "worker_request_digest",
            "workspace_instance_digest",
            "observed_manifest_digest",
        ):
            _sha256(getattr(self, name), name)
        if not re.fullmatch(r"[0-9a-f]{40}", self.pinned_base_sha or ""):
            raise WorkerRuntimeError("pinned base SHA is malformed")
        if type(self.observed_file_count) is not int or (
            self.observed_file_count < 0
        ) or type(self.observed_total_bytes) is not int or (
            self.observed_total_bytes < 0
        ):
            raise WorkerRuntimeError(
                "observed materialization size is malformed"
            )
        required_true = (
            self.materialization_performed,
            self.materialization_verified,
            self.exact_manifest_match,
            self.no_extra_files,
            self.no_symlinks,
            self.no_path_escape,
            self.source_read_only,
            self.workspace_disposable,
        )
        if any(value is not True for value in required_true) or (
            self.host_repository_reused is not False
            or self.launch_authorized is not False
        ):
            raise WorkerRuntimeError("materialization receipt is forged")
        if self.receipt_sha256 != _digest(self._payload()):
            raise WorkerRuntimeError("materialization receipt digest mismatch")

    def _body(self):
        return {
            "attempt_id": self.attempt_id,
            "exact_manifest_match": True,
            "host_repository_reused": False,
            "launch_authorized": False,
            "materialization_contract_digest": (
                self.materialization_contract_digest
            ),
            "materialization_id": self.materialization_id,
            "materialization_performed": True,
            "materialization_verified": True,
            "no_extra_files": True,
            "no_path_escape": True,
            "no_symlinks": True,
            "observed_file_count": self.observed_file_count,
            "observed_manifest_digest": self.observed_manifest_digest,
            "observed_total_bytes": self.observed_total_bytes,
            "pinned_base_sha": self.pinned_base_sha,
            "reconstruction_plan_digest": self.reconstruction_plan_digest,
            "source_manifest_digest": self.source_manifest_digest,
            "source_read_only": True,
            "worker_request_digest": self.worker_request_digest,
            "workspace_disposable": True,
            "workspace_instance_digest": self.workspace_instance_digest,
        }

    def _payload(self):
        return _canonical(self._body())

    def canonical_bytes(self):
        value = self._body()
        value["receipt_sha256"] = self.receipt_sha256
        return _canonical(value)


@dataclass
class _MaterializedWorkspace:
    root: Path
    source_root: Path
    receipt: VerifiedMaterializationReceipt


def _safe_bounded_directory(path, error_label):
    if not path.is_absolute() or ".." in path.parts:
        raise WorkerRuntimeError(f"{error_label} is unsafe")
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    if path.is_symlink():
        raise WorkerRuntimeError(f"{error_label} cannot be a symlink")
    resolved = path.resolve(strict=True)
    metadata = resolved.stat()
    if metadata.st_uid != os.geteuid() or stat.S_IMODE(
        metadata.st_mode
    ) & 0o077:
        raise WorkerRuntimeError(f"{error_label} ownership is unsafe")
    return resolved


def _safe_runtime_root():
    return _safe_bounded_directory(RUNTIME_ROOT, "runtime workspace root")


def _safe_docker_home():
    home = _safe_bounded_directory(DOCKER_HOME_ROOT, "docker supervisor home")
    docker_config = _safe_bounded_directory(
        home / ".docker", "docker supervisor config directory"
    )
    return home, docker_config


def _write_exact_source(contract, source_files):
    if not isinstance(source_files, Mapping):
        raise WorkerRuntimeError("source files must be a mapping")
    source_files = dict(source_files)
    manifest = contract.contract.reconstruction_plan.source_evidence
    expected = {entry.path: entry for entry in manifest.manifest_entries}
    if set(source_files) != set(expected):
        raise WorkerRuntimeError("source file set does not match manifest")
    root = _safe_runtime_root()
    instance_name = "execution-" + _digest(
        contract.receipt_sha256.encode("ascii")
    )[:24]
    execution_root = root / instance_name
    if execution_root.exists() or execution_root.is_symlink():
        raise WorkerRuntimeError(
            "disposable workspace identity already exists"
        )
    source_root = execution_root / "source"
    source_root.mkdir(mode=0o700, parents=True, exist_ok=False)
    try:
        for relative in sorted(expected):
            content = source_files[relative]
            entry = expected[relative]
            if not isinstance(content, bytes):
                raise WorkerRuntimeError("source content must be bytes")
            if len(content) != entry.size_bytes or _digest(content) != (
                entry.content_sha256
            ):
                raise WorkerRuntimeError("source content digest mismatch")
            destination = source_root.joinpath(*relative.split("/"))
            destination.parent.mkdir(
                mode=0o700, parents=True, exist_ok=True
            )
            if destination.is_symlink():
                raise WorkerRuntimeError(
                    "materialization symlink is forbidden"
                )
            descriptor = os.open(
                destination,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                0o600,
            )
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(content)
            destination.chmod(0o444)
        observed = _scan_source(source_root)
        expected_body = [
            entry.to_dict() for entry in manifest.manifest_entries
        ]
        observed_digest = _digest(_canonical(observed))
        if observed != expected_body or observed_digest != (
            manifest.manifest_sha256
        ):
            raise WorkerRuntimeError("materialized manifest mismatch")
        for directory, _, _ in os.walk(source_root, topdown=False):
            Path(directory).chmod(0o555)
        execution_root.chmod(0o700)
        values = {
            "materialization_id": contract.contract.materialization_id,
            "materialization_contract_digest": (
                contract.materialization_contract_digest
            ),
            "reconstruction_plan_digest": contract.reconstruction_plan_digest,
            "source_manifest_digest": contract.source_manifest_digest,
            "worker_request_digest": (
                contract.contract.worker_request_digest
            ),
            "attempt_id": contract.contract.attempt_id,
            "pinned_base_sha": contract.contract.pinned_base_sha,
            "workspace_instance_digest": _digest(
                instance_name.encode("utf-8")
            ),
            "observed_manifest_digest": observed_digest,
            "observed_file_count": len(observed),
            "observed_total_bytes": sum(
                item["size_bytes"] for item in observed
            ),
        }
        provisional = object.__new__(VerifiedMaterializationReceipt)
        for name, value in values.items():
            object.__setattr__(provisional, name, value)
        receipt = VerifiedMaterializationReceipt(
            **values,
            receipt_sha256=_digest(provisional._payload()),
            _verification_token=_MATERIALIZATION_TOKEN,
        )
        return _MaterializedWorkspace(execution_root, source_root, receipt)
    except Exception:
        _remove_workspace(execution_root)
        raise


def _scan_source(source_root):
    observed = []
    for directory, directories, files in os.walk(
        source_root, topdown=True, followlinks=False
    ):
        directories.sort()
        files.sort()
        base = Path(directory)
        if stat.S_ISLNK(base.lstat().st_mode):
            raise WorkerRuntimeError("materialized directory is a symlink")
        for name in files:
            path = base / name
            metadata = path.lstat()
            if not stat.S_ISREG(metadata.st_mode):
                raise WorkerRuntimeError("materialized entry is not regular")
            relative = path.relative_to(source_root).as_posix()
            content = path.read_bytes()
            observed.append({
                "content_sha256": _digest(content),
                "entry_type": "regular_file",
                "executable": bool(metadata.st_mode & 0o111),
                "path": relative,
                "size_bytes": len(content),
            })
    return sorted(observed, key=lambda item: item["path"])


def _remove_workspace(path):
    if not path.exists() and not path.is_symlink():
        return True
    try:
        if path.is_symlink():
            return False
        for directory, directories, files in os.walk(path, topdown=False):
            for name in files:
                (Path(directory) / name).chmod(0o600)
            for name in directories:
                child = Path(directory) / name
                if child.is_symlink():
                    return False
                child.chmod(0o700)
            Path(directory).chmod(0o700)
        shutil.rmtree(path)
        return not path.exists()
    except OSError:
        return False


@dataclass(frozen=True)
class RuntimeEnforcementEvidence:
    container_id: str
    runtime_inspect_digest: str
    image_inspect_digest: str
    container_inspect_digest: str
    runtime_descriptor_digest: str
    image_contract_digest: str
    policy_digest: str
    materialization_receipt_digest: str
    evidence_sha256: str
    network_disabled: bool = True
    exact_mounts_verified: bool = True
    non_privileged: bool = True
    host_namespaces_denied: bool = True
    docker_control_absent: bool = True
    credentials_absent: bool = True
    environment_allowlist_verified: bool = True
    memory_limit_verified: bool = True
    cpu_limit_verified: bool = True
    pid_limit_verified: bool = True
    writable_storage_bounded: bool = True
    output_capture_bounded: bool = True
    runtime_isolation_verified: bool = True
    launch_authorized_for_container: bool = True
    execution_performed: bool = False
    _verification_token: object = field(
        default=None, repr=False, compare=False
    )

    def __post_init__(self):
        if self._verification_token is not _ENFORCEMENT_TOKEN:
            raise WorkerRuntimeError(
                "runtime enforcement requires trusted observed evidence"
            )
        if _CONTAINER_ID.fullmatch(self.container_id or "") is None:
            raise WorkerRuntimeError("container identity is malformed")
        for name in (
            "runtime_inspect_digest", "image_inspect_digest",
            "container_inspect_digest",
            "runtime_descriptor_digest", "image_contract_digest",
            "policy_digest", "materialization_receipt_digest",
        ):
            _sha256(getattr(self, name), name)
        required_true = (
            self.network_disabled,
            self.exact_mounts_verified,
            self.non_privileged,
            self.host_namespaces_denied,
            self.docker_control_absent,
            self.credentials_absent,
            self.environment_allowlist_verified,
            self.memory_limit_verified,
            self.cpu_limit_verified,
            self.pid_limit_verified,
            self.writable_storage_bounded,
            self.output_capture_bounded,
            self.runtime_isolation_verified,
            self.launch_authorized_for_container,
        )
        if any(value is not True for value in required_true) or (
            self.execution_performed is not False
        ):
            raise WorkerRuntimeError("runtime enforcement evidence is forged")
        if self.evidence_sha256 != _digest(self._payload()):
            raise WorkerRuntimeError("runtime enforcement digest mismatch")

    def _body(self):
        return {
            "container_id": self.container_id,
            "cpu_limit_verified": True,
            "credentials_absent": True,
            "docker_control_absent": True,
            "environment_allowlist_verified": True,
            "exact_mounts_verified": True,
            "execution_performed": False,
            "host_namespaces_denied": True,
            "image_contract_digest": self.image_contract_digest,
            "image_inspect_digest": self.image_inspect_digest,
            "launch_authorized_for_container": True,
            "materialization_receipt_digest": (
                self.materialization_receipt_digest
            ),
            "memory_limit_verified": True,
            "network_disabled": True,
            "non_privileged": True,
            "output_capture_bounded": True,
            "pid_limit_verified": True,
            "policy_digest": self.policy_digest,
            "runtime_descriptor_digest": self.runtime_descriptor_digest,
            "runtime_inspect_digest": self.runtime_inspect_digest,
            "runtime_isolation_verified": True,
            "writable_storage_bounded": True,
            "container_inspect_digest": self.container_inspect_digest,
        }

    def _payload(self):
        return _canonical(self._body())

    def canonical_bytes(self):
        value = self._body()
        value["evidence_sha256"] = self.evidence_sha256
        return _canonical(value)


@dataclass(frozen=True)
class WorkerExecutionReceipt:
    materialization_receipt: VerifiedMaterializationReceipt
    enforcement_evidence: RuntimeEnforcementEvidence
    execution_id: str
    container_id: str
    supervisor_owner_id: str
    lifecycle_states: tuple
    final_state: str
    exit_code: Optional[int]
    started_at: str
    ended_at: str
    stdout_size: int
    stdout_sha256: str
    stdout_sample: str
    stderr_size: int
    stderr_sha256: str
    stderr_sample: str
    action_digest: str
    authorization_digest: str
    request_digest: str
    attempt_id: str
    worker_provider_id: str
    sandbox_provider_id: str
    policy_digest: str
    reconstruction_plan_digest: str
    materialization_receipt_digest: str
    runtime_descriptor_digest: str
    image_contract_digest: str
    enforcement_evidence_digest: str
    receipt_sha256: str
    timeout_observed: bool
    cancellation_requested: bool
    cancellation_confirmed: bool
    termination_uncertain: bool
    cleanup_confirmed: bool
    execution_performed: bool = True
    runtime_isolation_verified: bool = True
    materialization_verified: bool = True
    worker_output_trusted: bool = False
    result_verified: bool = False
    patch_verified: bool = False
    externally_verified: bool = False
    publication_authorized: bool = False
    queue_transition_authorized: bool = False
    github_authorized: bool = False
    _verification_token: object = field(
        default=None, repr=False, compare=False
    )

    def __post_init__(self):
        if self._verification_token is not _EXECUTION_RECEIPT_TOKEN:
            raise WorkerRuntimeError(
                "execution receipt requires trusted runtime evidence"
            )
        if not isinstance(
            self.materialization_receipt, VerifiedMaterializationReceipt
        ) or not isinstance(
            self.enforcement_evidence, RuntimeEnforcementEvidence
        ):
            raise WorkerRuntimeError("runtime evidence is malformed")
        for name in (
            "execution_id", "container_id", "supervisor_owner_id",
            "attempt_id", "worker_provider_id", "sandbox_provider_id",
        ):
            _identity(getattr(self, name), name)
        for name in (
            "stdout_sha256", "stderr_sha256", "action_digest",
            "authorization_digest", "request_digest", "policy_digest",
            "reconstruction_plan_digest", "materialization_receipt_digest",
            "runtime_descriptor_digest", "image_contract_digest",
            "enforcement_evidence_digest",
        ):
            _sha256(getattr(self, name), name)
        allowed_states = {
            "prepared", "launching", "running", "cancel_requested",
            "cancelled", "succeeded", "failed", "timed_out", "crashed",
            "termination_uncertain",
        }
        if not self.lifecycle_states or any(
            state_name not in allowed_states
            for state_name in self.lifecycle_states
        ) or self.final_state != self.lifecycle_states[-1]:
            raise WorkerRuntimeError("runtime lifecycle is malformed")
        if self.final_state == "succeeded" and self.exit_code != 0:
            raise WorkerRuntimeError(
                "success requires an observed zero exit code"
            )
        expected_prefix = ("prepared", "launching", "running")
        if self.lifecycle_states[:3] != expected_prefix or (
            len(self.lifecycle_states) not in (4, 5)
        ):
            raise WorkerRuntimeError("runtime lifecycle sequence is invalid")
        if len(self.lifecycle_states) == 5 and (
            self.lifecycle_states[3] != "cancel_requested"
            or self.final_state not in ("cancelled", "termination_uncertain")
        ):
            raise WorkerRuntimeError("cancellation lifecycle is invalid")
        if len(self.lifecycle_states) == 4 and self.final_state not in (
            "succeeded", "failed", "timed_out", "crashed",
            "termination_uncertain",
        ):
            raise WorkerRuntimeError("terminal lifecycle is invalid")
        for size, sample in (
            (self.stdout_size, self.stdout_sample),
            (self.stderr_size, self.stderr_sample),
        ):
            if (
                type(size) is not int
                or size < 0
                or not isinstance(sample, str)
            ):
                raise WorkerRuntimeError(
                    "runtime output metadata is malformed"
                )
            if utf8_length(sample) > MAX_SAMPLE_BYTES * 3:
                raise WorkerRuntimeError("runtime output sample exceeds bound")
        if self.termination_uncertain and self.final_state != (
            "termination_uncertain"
        ):
            raise WorkerRuntimeError(
                "uncertain termination state is inconsistent"
            )
        if self.cancellation_confirmed and self.final_state != "cancelled":
            raise WorkerRuntimeError(
                "cancellation confirmation is inconsistent"
            )
        if any(
            value is not False
            for value in (
                self.result_verified,
                self.patch_verified,
                self.externally_verified,
                self.publication_authorized,
                self.queue_transition_authorized,
                self.github_authorized,
            )
        ):
            raise WorkerRuntimeError("runtime result promotes authority")
        if (
            self.execution_performed is not True
            or self.runtime_isolation_verified is not True
            or self.materialization_verified is not True
            or self.worker_output_trusted is not False
        ):
            raise WorkerRuntimeError("execution receipt overstates trust")
        if (
            self.materialization_receipt.receipt_sha256
            != self.materialization_receipt_digest
            or self.enforcement_evidence.evidence_sha256
            != self.enforcement_evidence_digest
            or self.enforcement_evidence.materialization_receipt_digest
            != self.materialization_receipt_digest
        ):
            raise WorkerRuntimeError("runtime evidence binding mismatch")
        if self.receipt_sha256 != _digest(self._payload()):
            raise WorkerRuntimeError(
                "worker execution receipt digest mismatch"
            )
        if len(self.canonical_bytes()) > MAX_RECEIPT_BYTES:
            raise WorkerRuntimeError("worker execution receipt exceeds bound")

    def _body(self):
        return {
            "action_digest": self.action_digest,
            "attempt_id": self.attempt_id,
            "authorization_digest": self.authorization_digest,
            "cancellation_confirmed": self.cancellation_confirmed,
            "cancellation_requested": self.cancellation_requested,
            "cleanup_confirmed": self.cleanup_confirmed,
            "container_id": self.container_id,
            "ended_at": self.ended_at,
            "enforcement_evidence_digest": self.enforcement_evidence_digest,
            "exit_code": self.exit_code,
            "externally_verified": False,
            "execution_performed": True,
            "final_state": self.final_state,
            "github_authorized": False,
            "image_contract_digest": self.image_contract_digest,
            "lifecycle_states": list(self.lifecycle_states),
            "materialization_receipt_digest": (
                self.materialization_receipt_digest
            ),
            "materialization_verified": True,
            "patch_verified": False,
            "policy_digest": self.policy_digest,
            "publication_authorized": False,
            "queue_transition_authorized": False,
            "reconstruction_plan_digest": self.reconstruction_plan_digest,
            "request_digest": self.request_digest,
            "result_verified": False,
            "runtime_descriptor_digest": self.runtime_descriptor_digest,
            "runtime_isolation_verified": True,
            "sandbox_provider_id": self.sandbox_provider_id,
            "started_at": self.started_at,
            "stderr_sample": self.stderr_sample,
            "stderr_sha256": self.stderr_sha256,
            "stderr_size": self.stderr_size,
            "stdout_sample": self.stdout_sample,
            "stdout_sha256": self.stdout_sha256,
            "stdout_size": self.stdout_size,
            "supervisor_owner_id": self.supervisor_owner_id,
            "termination_uncertain": self.termination_uncertain,
            "timeout_observed": self.timeout_observed,
            "worker_provider_id": self.worker_provider_id,
            "worker_output_trusted": False,
            "execution_id": self.execution_id,
        }

    def _payload(self):
        return _canonical(self._body())

    def canonical_bytes(self):
        value = self._body()
        value["receipt_sha256"] = self.receipt_sha256
        return _canonical(value)


class DockerWorkerRuntime:
    """Synchronous one-worker Docker lifecycle with no retry or persistence."""

    def __init__(self, poll_interval=0.05):
        if type(poll_interval) not in (int, float) or poll_interval < 0:
            raise WorkerRuntimeError("poll interval is invalid")
        self._docker = _DockerCli()
        self._poll_interval = poll_interval

    def execute(
        self,
        foundation,
        source_files,
        execution_handle,
        cancellation_semantics=None,
    ):
        self._validate_foundation(foundation)
        self._validate_execution_handle(foundation, execution_handle)
        execution_id = execution_handle.execution_id
        supervisor_owner_id = execution_handle.supervisor_owner_id
        if cancellation_semantics is not None:
            self._validate_cancellation(
                execution_handle, cancellation_semantics
            )
        workspace = _write_exact_source(
            foundation.materialization_receipt, source_files
        )
        container_id = None
        cleanup_confirmed = False
        states = ["prepared"]
        started_at = _timestamp()
        ended_at = started_at
        stdout = b""
        stderr = b""
        exit_code = None
        timed_out = False
        cancellation_confirmed = False
        uncertain = False
        evidence = None
        try:
            runtime_inspect = self._inspect_runtime(foundation)
            image_inspect = self._inspect_image(foundation)
            states.append("launching")
            container_id = self._create_container(
                foundation, workspace, execution_id
            )
            container_inspect = self._inspect_container(container_id)
            evidence = self._verify_enforcement(
                foundation,
                workspace,
                container_id,
                runtime_inspect,
                image_inspect,
                container_inspect,
            )
            self._require_success(
                self._docker.run(("start", container_id), 30),
                "container start",
            )
            states.append("running")
            deadline = time.monotonic() + (
                foundation.provider_preflight.policy.resources.max_wall_seconds
            )
            if cancellation_semantics is not None:
                states.append("cancel_requested")
                final_state, exit_code, cancellation_confirmed = self._cancel(
                    container_id
                )
                uncertain = final_state == "termination_uncertain"
                states.append(final_state)
            else:
                final_state, exit_code, timed_out, uncertain = self._poll(
                    container_id, deadline
                )
                states.append(final_state)
            logs = self._docker.run(("logs", container_id), 30)
            stdout, stderr = logs.stdout, logs.stderr
            resources = foundation.provider_preflight.policy.resources
            if len(stdout) > resources.max_output_bytes or len(
                stderr
            ) > resources.max_log_bytes:
                raise WorkerRuntimeError("worker output exceeds policy bound")
            ended_at = _timestamp()
        finally:
            container_clean = True
            if container_id is not None:
                try:
                    removed = self._docker.run(
                        ("rm", "--force", container_id), 30
                    )
                    container_clean = removed.returncode == 0
                except WorkerRuntimeError:
                    container_clean = False
            workspace_clean = _remove_workspace(workspace.root)
            cleanup_confirmed = container_clean and workspace_clean
        if evidence is None:
            raise WorkerRuntimeError("runtime enforcement was not established")
        return _execution_receipt(
            foundation,
            evidence,
            workspace.receipt,
            execution_id,
            container_id,
            supervisor_owner_id,
            tuple(states),
            exit_code,
            started_at,
            ended_at,
            stdout,
            stderr,
            timed_out,
            cancellation_semantics is not None,
            cancellation_confirmed,
            uncertain,
            cleanup_confirmed,
        )

    @staticmethod
    def _validate_foundation(foundation):
        if not isinstance(foundation, RuntimeFoundationReadinessReceipt):
            raise WorkerRuntimeError("runtime foundation receipt is invalid")
        action = foundation.action
        authorization = action.authorization
        request = authorization.request
        plan = foundation.provider_preflight.repository_plan
        materialization = foundation.materialization_receipt
        enforcement = foundation.enforcement_contract
        expected = (
            (foundation.action_digest, action.action_digest),
            (
                foundation.authorization_digest,
                authorization.authorization_digest,
            ),
            (foundation.request_digest, request.request_digest),
            (foundation.attempt_id, request.attempt_id),
            (
                foundation.worker_provider_id,
                authorization.worker.provider_id,
            ),
            (
                foundation.sandbox_provider_id,
                foundation.provider_preflight.provider_descriptor.provider_id,
            ),
            (
                foundation.policy_digest,
                enforcement.sandbox_policy.policy_sha256,
            ),
            (foundation.reconstruction_plan_digest, plan.plan_sha256),
            (
                foundation.materialization_receipt_digest,
                materialization.receipt_sha256,
            ),
            (
                foundation.runtime_descriptor_digest,
                enforcement.runtime_descriptor.descriptor_sha256,
            ),
            (
                foundation.image_contract_digest,
                enforcement.worker_image.contract_sha256,
            ),
            (foundation.pinned_base_sha, request.job.base_sha),
        )
        if any(actual != wanted for actual, wanted in expected):
            raise WorkerRuntimeError("runtime foundation binding mismatch")
        if not authorization.authorized or not action.action_prepared:
            raise WorkerRuntimeError(
                "worker action is not authorized and prepared"
            )
        if (
            foundation.status != "foundation_ready_unverified"
            or not foundation.enforcement_requirements_structurally_satisfied
            or enforcement.status != "contract_satisfied"
        ):
            raise WorkerRuntimeError(
                "runtime foundation is not structurally ready"
            )
        image = enforcement.worker_image
        if image.network_required or image.credentials_required:
            raise WorkerRuntimeError(
                "offline worker cannot require network or credentials"
            )

    @staticmethod
    def _validate_execution_handle(foundation, handle):
        if not isinstance(handle, RuntimeExecutionHandleContract):
            raise WorkerRuntimeError("execution handle contract is invalid")
        if handle.readiness_receipt != foundation:
            raise WorkerRuntimeError("execution handle foundation mismatch")
        expected = (
            (handle.action_digest, foundation.action_digest),
            (handle.authorization_digest, foundation.authorization_digest),
            (handle.request_digest, foundation.request_digest),
            (handle.policy_digest, foundation.policy_digest),
            (
                handle.reconstruction_plan_digest,
                foundation.reconstruction_plan_digest,
            ),
            (
                handle.materialization_receipt_digest,
                foundation.materialization_receipt_digest,
            ),
            (
                handle.runtime_descriptor_digest,
                foundation.runtime_descriptor_digest,
            ),
            (handle.image_contract_digest, foundation.image_contract_digest),
            (handle.attempt_id, foundation.attempt_id),
        )
        if any(actual != wanted for actual, wanted in expected):
            raise WorkerRuntimeError("execution handle binding mismatch")

    @staticmethod
    def _validate_cancellation(handle, semantics):
        if not isinstance(semantics, RuntimeCancellationSemantics):
            raise WorkerRuntimeError("cancellation semantics are invalid")
        if semantics.handle_contract != handle or (
            semantics.execution_id != handle.execution_id
            or semantics.supervisor_owner_id != handle.supervisor_owner_id
            or semantics.handle_contract_digest
            != handle.handle_contract_sha256
        ):
            raise WorkerRuntimeError("cancellation target binding mismatch")

    def _inspect_image(self, foundation):
        image = foundation.enforcement_contract.worker_image
        result = self._docker.run(
            ("image", "inspect", image.image_reference), 30
        )
        self._require_success(result, "local pinned image inspection")
        payload = _one_json_object(result.stdout, "image inspection")
        repo_digests = payload.get("RepoDigests") or []
        config = payload.get("Config") or {}
        if (
            image.image_reference not in repo_digests
            or payload.get("Id") != "sha256:" + image.config_sha256
            or payload.get("Os") != image.platform
            or payload.get("Architecture") != image.architecture
            or tuple(config.get("Entrypoint") or ()) != ENTRYPOINT_ARGV
            or config.get("Cmd") not in (None, [])
        ):
            raise WorkerRuntimeError("local image identity or config mismatch")
        return payload

    def _inspect_runtime(self, foundation):
        descriptor = foundation.enforcement_contract.runtime_descriptor
        result = self._docker.run(
            ("version", "--format", "{{json .Server}}"), 30
        )
        self._require_success(result, "Docker runtime inspection")
        payload = _json_object(result.stdout, "Docker runtime inspection")
        if (
            payload.get("Version") != descriptor.engine_version
            or payload.get("ApiVersion") != descriptor.engine_api_version
            or payload.get("Os") != descriptor.platform
            or payload.get("Arch") != descriptor.architecture
        ):
            raise WorkerRuntimeError("Docker runtime identity mismatch")
        return payload

    def _create_container(self, foundation, workspace, execution_id):
        policy = foundation.provider_preflight.policy
        image = foundation.enforcement_contract.worker_image
        resources = policy.resources
        workspace_bytes = min(
            resources.max_memory_bytes // 2,
            resources.max_file_bytes,
        )
        required_bytes = resources.max_output_bytes
        if workspace_bytes < required_bytes:
            raise WorkerRuntimeError(
                "writable workspace limit is insufficient"
            )
        cpu_count = resources.max_cpu_millis / 1000
        name = "cb022-" + _digest(execution_id.encode("utf-8"))[:20]
        environment = {
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
            "PYTHONHASHSEED": "0",
        }
        if set(policy.environment_allowlist) != set(environment) or any(
            _SENSITIVE_ENV.search(name) for name in environment
        ):
            raise WorkerRuntimeError("worker environment policy is unsafe")
        source_mount = (
            f"type=bind,src={workspace.source_root},"
            f"dst={CONTAINER_SOURCE},readonly"
        )
        arguments = [
            "create", "--name", name,
            "--network", "none",
            "--read-only",
            "--cap-drop", "ALL",
            "--security-opt", "no-new-privileges:true",
            "--user", CONTAINER_USER,
            "--pids-limit", str(resources.max_processes),
            "--memory", str(resources.max_memory_bytes),
            "--cpus", f"{cpu_count:.3f}",
            "--log-driver", "local",
            "--log-opt", f"max-size={resources.max_log_bytes}b",
            "--log-opt", "max-file=1",
            "--mount", source_mount,
            "--tmpfs", (
                f"{CONTAINER_WORKSPACE}:rw,nosuid,nodev,noexec,"
                f"size={workspace_bytes},nr_inodes={resources.max_files},"
                "uid=65532,gid=65532,mode=0700"
            ),
            "--tmpfs", (
                "/tmp:rw,nosuid,nodev,noexec,size=16777216,"
                "uid=65532,gid=65532,mode=0700"
            ),
            "--workdir", CONTAINER_WORKSPACE,
        ]
        for name in sorted(environment):
            arguments.extend(("--env", f"{name}={environment[name]}"))
        arguments.extend((
            "--entrypoint", ENTRYPOINT_ARGV[0],
            image.image_reference,
            foundation.attempt_id,
            foundation.request_digest,
            CONTAINER_WORKSPACE,
        ))
        result = self._docker.run(tuple(arguments), 30)
        self._require_success(result, "container creation")
        container_id = result.stdout.decode("ascii", errors="strict").strip()
        if _CONTAINER_ID.fullmatch(container_id or "") is None:
            raise WorkerRuntimeError("Docker returned an invalid container ID")
        return container_id

    def _inspect_container(self, container_id):
        result = self._docker.run(("inspect", container_id), 30)
        self._require_success(result, "container inspection")
        return _one_json_object(result.stdout, "container inspection")

    @staticmethod
    def _verify_enforcement(
        foundation, workspace, container_id, runtime_inspect, image_inspect,
        container_inspect,
    ):
        policy = foundation.provider_preflight.policy
        resources = policy.resources
        host = container_inspect.get("HostConfig") or {}
        config = container_inspect.get("Config") or {}
        mounts = container_inspect.get("Mounts") or []
        state = container_inspect.get("State") or {}
        expected_env = {"LANG=C.UTF-8", "LC_ALL=C.UTF-8", "PYTHONHASHSEED=0"}
        mount_ok = len(mounts) == 1 and (
            mounts[0].get("Source") == str(workspace.source_root)
            and mounts[0].get("Destination") == CONTAINER_SOURCE
            and mounts[0].get("RW") is False
        )
        tmpfs = host.get("Tmpfs") or {}
        workspace_bytes = min(
            resources.max_memory_bytes // 2,
            resources.max_file_bytes,
        )
        expected_tmpfs = {
            CONTAINER_WORKSPACE: (
                "rw,nosuid,nodev,noexec,"
                f"size={workspace_bytes},nr_inodes={resources.max_files},"
                "uid=65532,gid=65532,mode=0700"
            ),
            "/tmp": (
                "rw,nosuid,nodev,noexec,size=16777216,"
                "uid=65532,gid=65532,mode=0700"
            ),
        }
        security = set(host.get("SecurityOpt") or ())
        capabilities = set(host.get("CapDrop") or ())
        expected_nano_cpus = resources.max_cpu_millis * 1000000
        checks = (
            container_inspect.get("Id") == container_id,
            state.get("Status") == "created",
            container_inspect.get("Image")
            == "sha256:"
            + foundation.enforcement_contract.worker_image.config_sha256,
            host.get("NetworkMode") == "none",
            host.get("Privileged") is False,
            host.get("ReadonlyRootfs") is True,
            host.get("PidMode") in ("", None),
            host.get("IpcMode") in ("", "private", None),
            host.get("Memory") == resources.max_memory_bytes,
            host.get("NanoCpus") == expected_nano_cpus,
            host.get("PidsLimit") == resources.max_processes,
            "ALL" in capabilities,
            "no-new-privileges:true" in security
            or "no-new-privileges" in security,
            mount_ok,
            tmpfs == expected_tmpfs,
            set(config.get("Env") or ()) == expected_env,
            config.get("User") == CONTAINER_USER,
            config.get("Entrypoint") == [ENTRYPOINT_ARGV[0]],
            config.get("Image")
            == foundation.enforcement_contract.worker_image.image_reference,
        )
        if not all(checks):
            raise WorkerRuntimeError("Docker containment inspection failed")
        values = {
            "container_id": container_id,
            "runtime_inspect_digest": _digest(_canonical(runtime_inspect)),
            "image_inspect_digest": _digest(_canonical(image_inspect)),
            "container_inspect_digest": _digest(_canonical(container_inspect)),
            "runtime_descriptor_digest": foundation.runtime_descriptor_digest,
            "image_contract_digest": foundation.image_contract_digest,
            "policy_digest": foundation.policy_digest,
            "materialization_receipt_digest": workspace.receipt.receipt_sha256,
        }
        provisional = object.__new__(RuntimeEnforcementEvidence)
        for name, value in values.items():
            object.__setattr__(provisional, name, value)
        return RuntimeEnforcementEvidence(
            **values,
            evidence_sha256=_digest(provisional._payload()),
            _verification_token=_ENFORCEMENT_TOKEN,
        )

    def _poll(self, container_id, deadline):
        while True:
            if time.monotonic() >= deadline:
                final_state, exit_code, confirmed = self._cancel_container(
                    container_id
                )
                if confirmed:
                    return "timed_out", exit_code, True, False
                return "termination_uncertain", exit_code, True, True
            try:
                inspection = self._inspect_container(container_id)
            except WorkerRuntimeError:
                return "termination_uncertain", None, False, True
            state = inspection.get("State") or {}
            if state.get("Running") is True:
                if self._poll_interval:
                    time.sleep(self._poll_interval)
                continue
            if state.get("Status") == "exited" and state.get("FinishedAt"):
                exit_code = state.get("ExitCode")
                if type(exit_code) is not int:
                    return "crashed", None, False, False
                return (
                    "succeeded" if exit_code == 0 else "failed",
                    exit_code,
                    False,
                    False,
                )
            if state.get("Dead") is True or state.get("OOMKilled") is True:
                return "crashed", state.get("ExitCode"), False, False
            return "termination_uncertain", state.get("ExitCode"), False, True

    def _cancel(self, container_id):
        final_state, exit_code, confirmed = self._cancel_container(
            container_id
        )
        if confirmed:
            return "cancelled", exit_code, True
        return "termination_uncertain", exit_code, False

    def _cancel_container(self, container_id):
        stopped = self._docker.run(("stop", "--time", "2", container_id), 10)
        if stopped.returncode != 0:
            killed = self._docker.run(("kill", container_id), 10)
            if killed.returncode != 0:
                return "termination_uncertain", None, False
        try:
            inspection = self._inspect_container(container_id)
        except WorkerRuntimeError:
            return "termination_uncertain", None, False
        state = inspection.get("State") or {}
        if state.get("Running") is False and state.get("Status") in (
            "exited", "dead"
        ):
            return "cancelled", state.get("ExitCode"), True
        return "termination_uncertain", state.get("ExitCode"), False

    @staticmethod
    def _require_success(result, operation):
        if result.returncode != 0:
            detail = _bounded_text(result.stderr).strip()
            raise WorkerRuntimeError(
                f"{operation} failed" + (f": {detail}" if detail else "")
            )


def _one_json_object(raw, name):
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise WorkerRuntimeError(f"{name} is malformed") from error
    if not isinstance(value, list) or len(value) != 1 or not isinstance(
        value[0], dict
    ):
        raise WorkerRuntimeError(f"{name} must contain exactly one object")
    return value[0]


def _json_object(raw, name):
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise WorkerRuntimeError(f"{name} is malformed") from error
    if not isinstance(value, dict):
        raise WorkerRuntimeError(f"{name} must contain one object")
    return value


def _timestamp():
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


def _execution_receipt(
    foundation,
    evidence,
    materialization_receipt,
    execution_id,
    container_id,
    supervisor_owner_id,
    states,
    exit_code,
    started_at,
    ended_at,
    stdout,
    stderr,
    timed_out,
    cancellation_requested,
    cancellation_confirmed,
    uncertain,
    cleanup_confirmed,
):
    values = {
        "materialization_receipt": materialization_receipt,
        "enforcement_evidence": evidence,
        "execution_id": execution_id,
        "container_id": container_id,
        "supervisor_owner_id": supervisor_owner_id,
        "lifecycle_states": states,
        "final_state": states[-1],
        "exit_code": exit_code,
        "started_at": started_at,
        "ended_at": ended_at,
        "stdout_size": len(stdout),
        "stdout_sha256": _digest(stdout),
        "stdout_sample": _bounded_text(stdout),
        "stderr_size": len(stderr),
        "stderr_sha256": _digest(stderr),
        "stderr_sample": _bounded_text(stderr),
        "action_digest": foundation.action_digest,
        "authorization_digest": foundation.authorization_digest,
        "request_digest": foundation.request_digest,
        "attempt_id": foundation.attempt_id,
        "worker_provider_id": foundation.worker_provider_id,
        "sandbox_provider_id": foundation.sandbox_provider_id,
        "policy_digest": foundation.policy_digest,
        "reconstruction_plan_digest": foundation.reconstruction_plan_digest,
        "materialization_receipt_digest": (
            evidence.materialization_receipt_digest
        ),
        "runtime_descriptor_digest": foundation.runtime_descriptor_digest,
        "image_contract_digest": foundation.image_contract_digest,
        "enforcement_evidence_digest": evidence.evidence_sha256,
        "timeout_observed": timed_out,
        "cancellation_requested": cancellation_requested,
        "cancellation_confirmed": cancellation_confirmed,
        "termination_uncertain": uncertain,
        "cleanup_confirmed": cleanup_confirmed,
    }
    provisional = object.__new__(WorkerExecutionReceipt)
    for name, value in values.items():
        object.__setattr__(provisional, name, value)
    return WorkerExecutionReceipt(
        **values,
        receipt_sha256=_digest(provisional._payload()),
        _verification_token=_EXECUTION_RECEIPT_TOKEN,
    )
