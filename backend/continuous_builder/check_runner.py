"""CB-026B: trusted check selection, reconstruction, and observed evidence.

Only trusted supervisor code calls the factories; no worker-input deserializer
or routing entry point is provided. Python tokens enforce the same in-process
construction boundary as CB-026A, not authentication of arbitrary host code.
Test code runs in a separate Docker container, never in this host interpreter.
"""

import os
import re
import stat
import tempfile
from dataclasses import dataclass, field, fields, replace

from pathlib import Path

from .verifier_core import (
    STATUS_PASSED, StructuralVerificationReceipt, TrustedCandidateContract,
    VerifierCoreError, _canonical, _digest, _tree_digest,
    verify_candidate_structure,
)
from .paths import canonicalize_repo_path, PathCanonicalizationError
from .worker_runtime import _remove_workspace, _safe_bounded_directory


POLICY_VERSION = "cb-trusted-check-runner-v1"
CHECK_ROOT = Path("/private/tmp/mootos-continuous-builder-checks")
MAX_CHECKS = 4
MAX_TOTAL_SECONDS = 120
MAX_TREE_BYTES = 16 * 1024 * 1024
MAX_FILE_BYTES = 1024 * 1024
MAX_FILES = 4096
PROTECTED_CHECK_PATHS = (
    "backend/continuous_builder/check_runner.py",
    "backend/continuous_builder/check_runtime.py",
    "backend/continuous_builder/verifier_core.py",
)
AUTHORITY_FLAGS = (
    "result_trusted", "worker_output_trusted", "externally_verified",
    "publication_authorized", "queue_transition_authorized",
    "github_authorized", "merge_authorized", "main_advancement_authorized",
)
FAILURE_CODES = frozenset({
    "candidate_tree_digest_mismatch", "check_nonzero_exit", "check_timeout",
    "output_bound_exceeded", "execution_uncertain", "cleanup_uncertain",
    "check_plan_binding_mismatch", "candidate_input_invalid",
    "structural_verification_required", "unsupported_check", "invalid_plan",
    "containment_unproven",
})
_TOKEN = object()
_HEX = re.compile(r"[0-9a-f]{64}\Z")
_PATH = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_./-]{0,255}\Z")


class CheckRunnerError(ValueError):
    """Bounded rejection before command authority can be exercised."""

    def __init__(self, code):
        if code not in FAILURE_CODES:
            code = "invalid_plan"
        self.code = code
        super().__init__(code)


def _require(condition, code="invalid_plan"):
    if not condition:
        raise CheckRunnerError(code)


def _hash(value):
    _require(type(value) is str and _HEX.fullmatch(value) is not None)


def _path(value):
    try:
        _require(type(value) is str and _PATH.fullmatch(value) is not None,
                 "candidate_input_invalid")
        _require(canonicalize_repo_path(value) == value,
                 "candidate_input_invalid")
        _require(all(part not in (".git", ".env") for part in value.split("/")),
                 "candidate_input_invalid")
    except PathCanonicalizationError as error:
        raise CheckRunnerError("candidate_input_invalid") from error
    return value


def _json_value(value):
    if isinstance(value, _Sealed):
        return value._body()
    if type(value) is tuple:
        return [_json_value(item) for item in value]
    return value


class _Sealed:
    def _body(self):
        return {
            item.name: _json_value(getattr(self, item.name))
            for item in fields(self)
            if not item.name.startswith("_") and item.name != self._digest_field
        }

    def canonical_bytes(self):
        body = self._body()
        body[self._digest_field] = getattr(self, self._digest_field)
        return _canonical(body)

    def _validate_seal(self):
        _require(self._token is _TOKEN)
        _require(getattr(self, self._digest_field) == _digest(_canonical(self._body())))
        _require(len(self.canonical_bytes()) <= 128 * 1024)


def _seal(cls, **values):
    provisional = object.__new__(cls)
    for key, value in values.items():
        object.__setattr__(provisional, key, value)
    return cls(**values, _token=_TOKEN, **{
        cls._digest_field: _digest(_canonical(provisional._body())),
    })


@dataclass(frozen=True)
class TrustedCheckDefinition(_Sealed):
    check_id: str
    argv: tuple
    working_directory: str
    timeout_seconds: int
    max_stdout_bytes: int
    max_stderr_bytes: int
    expected_exit_codes: tuple
    definition_sha256: str
    _token: object = field(default=None, repr=False, compare=False)
    _digest_field = "definition_sha256"

    def __post_init__(self):
        self._validate_seal()
        _require(type(self.check_id) is str and re.fullmatch(
            r"[a-z][a-z0-9_-]{0,63}", self.check_id) is not None)
        _require(self.working_directory == "/candidate")
        _require(type(self.argv) is tuple and len(self.argv) <= 32)
        _require(self.expected_exit_codes == (0,)
                 and type(self.expected_exit_codes) is tuple
                 and type(self.expected_exit_codes[0]) is int)
        for value, limit in ((self.timeout_seconds, 30),
                             (self.max_stdout_bytes, 65536),
                             (self.max_stderr_bytes, 65536)):
            _require(type(value) is int and 1 <= value <= limit)
        _require(len(self.argv) >= 5 and self.argv[:3] == (
            "/usr/local/bin/python3", "-I", "-m"), "unsupported_check")
        tool = self.argv[3]
        _require(tool in _PREFIXES, "unsupported_check")
        prefix = _PREFIXES[tool]
        _require(self.argv[:len(prefix)] == prefix, "unsupported_check")
        targets = self.argv[len(prefix):]
        _require(0 < len(targets) <= 8 and len(set(targets)) == len(targets))
        for target in targets:
            _path(target)
            _require(target.endswith(".py"), "unsupported_check")


_PREFIXES = {
    "pytest": ("/usr/local/bin/python3", "-I", "-m", "pytest", "-q",
               "-p", "no:cacheprovider", "--noconftest", "-c", "/dev/null",
               "--rootdir=/candidate", "-o", "pythonpath=/candidate", "--"),
    "flake8": ("/usr/local/bin/python3", "-I", "-m", "flake8",
               "--isolated", "--jobs=1", "--"),
}


def create_trusted_check(*, check_id, tool, targets, timeout_seconds=10,
                         max_stdout_bytes=16384, max_stderr_bytes=16384):
    """Trusted policy factory, deliberately no argv/options/shell argument."""
    _require(type(tool) is str and tool in _PREFIXES, "unsupported_check")
    _require(type(targets) is tuple)
    return _seal(TrustedCheckDefinition, check_id=check_id,
                 argv=_PREFIXES[tool] + targets, working_directory="/candidate",
                 timeout_seconds=timeout_seconds, max_stdout_bytes=max_stdout_bytes,
                 max_stderr_bytes=max_stderr_bytes, expected_exit_codes=(0,))


@dataclass(frozen=True)
class TrustedCheckImage(_Sealed):
    image_digest: str
    config_sha256: str
    architecture: str
    image_sha256: str
    _token: object = field(default=None, repr=False, compare=False)
    _digest_field = "image_sha256"

    def __post_init__(self):
        self._validate_seal()
        _hash(self.image_digest)
        _hash(self.config_sha256)
        _require(self.architecture in ("amd64", "arm64"))

    @property
    def reference(self):
        return "mootos/trusted-check-runner@sha256:" + self.image_digest


def create_trusted_check_image(*, image_digest, config_sha256, architecture):
    """Pin an already-provisioned, system-reviewed offline toolchain image."""
    return _seal(TrustedCheckImage, image_digest=image_digest,
                 config_sha256=config_sha256, architecture=architecture)


@dataclass(frozen=True)
class TrustedCheckPlan(_Sealed):
    structural_receipt_sha256: str
    candidate_tree_sha256: str
    pinned_base_sha: str
    worker_request_digest: str
    checks: tuple
    image: TrustedCheckImage
    policy_version: str
    plan_sha256: str
    _contract: TrustedCandidateContract = field(repr=False, compare=False)
    _structural: StructuralVerificationReceipt = field(repr=False, compare=False)
    _token: object = field(default=None, repr=False, compare=False)
    _digest_field = "plan_sha256"

    def __post_init__(self):
        self._validate_seal()
        _require(self.policy_version == POLICY_VERSION)
        _require(type(self._contract) is TrustedCandidateContract)
        _require(type(self._structural) is StructuralVerificationReceipt)
        _require(type(self.image) is TrustedCheckImage)
        replace(self.image)
        try:
            contract, structural = replace(self._contract), replace(self._structural)
        except VerifierCoreError as error:
            raise CheckRunnerError("check_plan_binding_mismatch") from error
        _require(structural.status == STATUS_PASSED, "structural_verification_required")
        _require((self.structural_receipt_sha256, self.candidate_tree_sha256,
                  self.pinned_base_sha, self.worker_request_digest) == (
                      structural.receipt_sha256, structural.candidate_tree_sha256,
                      contract.pinned_base_sha, contract.worker_request_digest),
                 "check_plan_binding_mismatch")
        _require((structural.contract_sha256, structural.pinned_base_sha,
                  structural.request_digest, structural.base_tree_sha256) == (
                      contract.contract_sha256, contract.pinned_base_sha,
                      contract.worker_request_digest, contract.base_tree_sha256),
                 "check_plan_binding_mismatch")
        _require(set(PROTECTED_CHECK_PATHS).issubset(contract.protected_paths))
        _require(type(self.checks) is tuple and 1 <= len(self.checks) <= MAX_CHECKS)
        _require(all(type(check) is TrustedCheckDefinition for check in self.checks))
        _require(len({check.check_id for check in self.checks}) == len(self.checks))
        _require(sum(check.timeout_seconds for check in self.checks) <= MAX_TOTAL_SECONDS)
        for check in self.checks:
            replace(check)
            targets = check.argv[len(_PREFIXES[check.argv[3]]):]
            if check.argv[3] == "pytest":
                _require(set(targets).issubset(contract.protected_paths))
                _require(set(targets).issubset(contract.base_content()))


def create_trusted_check_plan(contract, structural_receipt, *, checks, image):
    _require(type(structural_receipt) is StructuralVerificationReceipt)
    return _seal(TrustedCheckPlan,
                 structural_receipt_sha256=structural_receipt.receipt_sha256,
                 candidate_tree_sha256=structural_receipt.candidate_tree_sha256,
                 pinned_base_sha=structural_receipt.pinned_base_sha,
                 worker_request_digest=structural_receipt.request_digest,
                 checks=checks, image=image, policy_version=POLICY_VERSION,
                 _contract=contract, _structural=structural_receipt)


@dataclass(frozen=True)
class TrustedCheckResult(_Sealed):
    check_id: str
    argv_sha256: str
    start_sequence: int
    finish_sequence: int
    container_id: str
    containment_sha256: str
    execution_performed: bool
    exit_code: object
    stdout_size: int
    stdout_sha256: str
    stderr_size: int
    stderr_sha256: str
    output_complete: bool
    timeout_observed: bool
    termination_confirmed: bool
    cleanup_confirmed: bool
    failure_codes: tuple
    result_sha256: str
    _token: object = field(default=None, repr=False, compare=False)
    _digest_field = "result_sha256"

    def __post_init__(self):
        self._validate_seal()
        for value in (self.argv_sha256, self.containment_sha256,
                      self.stdout_sha256, self.stderr_sha256):
            _hash(value)
        _require(type(self.start_sequence) is int and self.start_sequence >= 0)
        _require(self.finish_sequence == self.start_sequence + 1)
        _require(self.exit_code is None or type(self.exit_code) is int)
        for value in (self.stdout_size, self.stderr_size):
            _require(type(value) is int and 0 <= value <= 65537)
        for name in ("execution_performed", "output_complete", "timeout_observed",
                     "termination_confirmed", "cleanup_confirmed"):
            _require(type(getattr(self, name)) is bool)
        _validate_codes(self.failure_codes)
        if not self.failure_codes:
            _require(self.execution_performed and self.exit_code == 0
                     and self.output_complete and not self.timeout_observed
                     and self.termination_confirmed and self.cleanup_confirmed)
        _require(not self.timeout_observed or "check_timeout" in self.failure_codes)
        _require(self.cleanup_confirmed or "cleanup_uncertain" in self.failure_codes)
        _require(self.termination_confirmed or "execution_uncertain" in self.failure_codes)
        _require(self.output_complete or bool(set(self.failure_codes) & {
            "output_bound_exceeded", "execution_uncertain", "check_timeout"}))


def _validate_codes(codes):
    _require(type(codes) is tuple and codes == tuple(sorted(set(codes))))
    _require(set(codes).issubset(FAILURE_CODES))


def _status(codes):
    if set(codes) & {"execution_uncertain", "cleanup_uncertain", "containment_unproven"}:
        return "checks_uncertain"
    if "check_timeout" in codes:
        return "checks_timed_out"
    return "checks_failed" if codes else "checks_passed"


def _outcome(plan, results, codes):
    # Stable outcome identity; actual receipt still binds random workspace,
    # container identities and exact observed output. No invented timestamps.
    return _digest(_canonical({
        "plan_sha256": plan.plan_sha256, "failure_codes": codes,
        "checks": [(r.check_id, r.argv_sha256, r.exit_code, r.failure_codes)
                   for r in results],
    }))


@dataclass(frozen=True)
class TrustedCheckExecutionReceipt(_Sealed):
    plan_sha256: str
    structural_receipt_sha256: str
    candidate_tree_sha256: str
    workspace_identity_sha256: str
    pinned_base_sha: str
    worker_request_digest: str
    results: tuple
    status: str
    failure_codes: tuple
    cleanup_confirmed: bool
    outcome_sha256: str
    receipt_sha256: str
    policy_version: str = POLICY_VERSION
    result_trusted: bool = False
    worker_output_trusted: bool = False
    externally_verified: bool = False
    publication_authorized: bool = False
    queue_transition_authorized: bool = False
    github_authorized: bool = False
    merge_authorized: bool = False
    main_advancement_authorized: bool = False
    _plan: object = field(default=None, repr=False, compare=False)
    _token: object = field(default=None, repr=False, compare=False)
    _digest_field = "receipt_sha256"

    def __post_init__(self):
        self._validate_seal()
        _require(all(getattr(self, flag) is False for flag in AUTHORITY_FLAGS))
        _require(self.policy_version == POLICY_VERSION)
        _require(type(self._plan) is TrustedCheckPlan)
        plan = replace(self._plan)
        for name in ("plan_sha256", "structural_receipt_sha256", "candidate_tree_sha256",
                     "pinned_base_sha", "worker_request_digest"):
            _require(getattr(self, name) == getattr(plan, name))
        _hash(self.workspace_identity_sha256)
        _require(type(self.results) is tuple and len(self.results) <= len(plan.checks))
        _validate_codes(self.failure_codes)
        for index, result in enumerate(self.results):
            _require(type(result) is TrustedCheckResult)
            replace(result)
            _require(result.check_id == plan.checks[index].check_id)
            _require(result.argv_sha256 == _digest(_canonical(plan.checks[index].argv)))
            _require(result.start_sequence == index * 2)
            _require(set(result.failure_codes).issubset(self.failure_codes))
        _require(self.status == _status(self.failure_codes))
        _require(type(self.cleanup_confirmed) is bool)
        _require(self.cleanup_confirmed or "cleanup_uncertain" in self.failure_codes)
        if self.status == "checks_passed":
            _require(len(self.results) == len(plan.checks) and self.cleanup_confirmed)
        _require(self.outcome_sha256 == _outcome(plan, self.results, self.failure_codes))


def _validate_tree(files):
    _require(type(files) is dict and 0 < len(files) <= MAX_FILES,
             "candidate_input_invalid")
    total = 0
    folded = {path.casefold() for path in files if type(path) is str}
    _require(len(folded) == len(files), "candidate_input_invalid")
    for path, content in sorted(files.items()):
        _path(path)
        _require(type(content) is bytes and len(content) <= MAX_FILE_BYTES,
                 "candidate_input_invalid")
        total += len(content)
        _require(total <= MAX_TREE_BYTES,
                 "candidate_input_invalid")
        parts = path.split("/")
        _require(not any("/".join(parts[:i]).casefold() in folded
                         for i in range(1, len(parts))), "candidate_input_invalid")


def _observe_tree(root):
    observed = {}
    for path in root.rglob("*"):
        metadata = path.lstat()
        _require(not stat.S_ISLNK(metadata.st_mode), "candidate_input_invalid")
        if stat.S_ISDIR(metadata.st_mode):
            continue
        _require(stat.S_ISREG(metadata.st_mode) and metadata.st_nlink == 1
                 and metadata.st_size <= MAX_FILE_BYTES, "candidate_input_invalid")
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(fd, "rb") as stream:
            content = stream.read(MAX_FILE_BYTES + 1)
        observed[path.relative_to(root).as_posix()] = content
        _require(len(observed) <= MAX_FILES, "candidate_input_invalid")
    _validate_tree(observed)
    return _tree_digest(observed)


def _materialize(root, base, candidate, plan):
    _validate_tree(base)
    _validate_tree(candidate)
    _require(_tree_digest(base) == plan._contract.base_tree_sha256,
             "candidate_tree_digest_mismatch")
    _require(_tree_digest(candidate) == plan.candidate_tree_sha256,
             "candidate_tree_digest_mismatch")
    root.mkdir(mode=0o755)
    root.chmod(0o755)
    for path, content in sorted(candidate.items()):
        target = root / path
        target.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o444)
        with os.fdopen(fd, "wb") as stream:
            stream.write(content)
            os.fchmod(stream.fileno(), 0o444)
    # umask must not accidentally deny the fixed nonroot container user.
    # The enclosing supervisor-owned workspace remains private (0700).
    for directory in root.rglob("*"):
        if directory.is_dir():
            directory.chmod(0o755)
    _require(_observe_tree(root) == plan.candidate_tree_sha256,
             "candidate_tree_digest_mismatch")


def run_trusted_checks(plan, contract, execution_receipt, intake_result):
    """No worker claims, commands, host paths, env or runtime injection accepted."""
    _require(type(plan) is TrustedCheckPlan)
    replace(plan)
    try:
        structural = verify_candidate_structure(contract, execution_receipt, intake_result)
    except (VerifierCoreError, TypeError, ValueError) as error:
        raise CheckRunnerError("check_plan_binding_mismatch") from error
    _require(structural.canonical_bytes() == plan._structural.canonical_bytes(),
             "check_plan_binding_mismatch")
    base = contract.base_content()
    candidate = dict(base)
    candidate.update(intake_result._artifact_payloads)
    _validate_tree(base)
    _validate_tree(candidate)
    for check in plan.checks:
        _require(set(check.argv[len(_PREFIXES[check.argv[3]]):]).issubset(candidate),
                 "check_plan_binding_mismatch")
    # Reuse CB-022 private-root ownership checks and bounded cleanup. Its
    # DockerWorkerRuntime cannot safely be generalized: it has a fixed worker
    # entrypoint and captures Docker logs only after execution has completed.
    authority = _safe_bounded_directory(CHECK_ROOT, "verifier workspace root")
    workspace = Path(tempfile.mkdtemp(prefix="check-", dir=authority))
    identity = _digest(str(workspace).encode())
    results, failures = [], set()
    try:
        root = workspace / "candidate"
        _materialize(root, base, candidate, plan)
        from .check_runtime import execute_checks
        for index, observed in enumerate(execute_checks(plan, root)):
            result = _seal(TrustedCheckResult, **observed,
                           check_id=plan.checks[index].check_id,
                           argv_sha256=_digest(_canonical(plan.checks[index].argv)),
                           start_sequence=2 * index, finish_sequence=2 * index + 1)
            results.append(result)
            failures.update(result.failure_codes)
        _require(_observe_tree(root) == plan.candidate_tree_sha256,
                 "candidate_tree_digest_mismatch")
    except CheckRunnerError as error:
        failures.add(error.code)
    except (OSError, ValueError):
        failures.add("execution_uncertain")
    finally:
        cleanup = _remove_workspace(workspace)
        if not cleanup:
            failures.add("cleanup_uncertain")
    if len(results) != len(plan.checks) and not failures:
        failures.add("execution_uncertain")
    codes = tuple(sorted(failures))
    return _seal(TrustedCheckExecutionReceipt,
                 plan_sha256=plan.plan_sha256,
                 structural_receipt_sha256=plan.structural_receipt_sha256,
                 candidate_tree_sha256=plan.candidate_tree_sha256,
                 workspace_identity_sha256=identity, pinned_base_sha=plan.pinned_base_sha,
                 worker_request_digest=plan.worker_request_digest,
                 results=tuple(results), status=_status(codes), failure_codes=codes,
                 cleanup_confirmed=cleanup and all(r.cleanup_confirmed for r in results),
                 outcome_sha256=_outcome(plan, results, codes), _plan=plan)
