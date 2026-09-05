"""Trusted tiny fixture task used by the CB-025 contained trust-chain proof.

This module declares one deterministic, offline, disposable coding task: the
trusted base input, the exact paths a worker is permitted to touch, and the
exact bytes an acceptable candidate must contain.  It is the *system's* copy
of the task, never the worker's: nothing here reads worker-authored output,
and the acceptance rule is content-addressed so a later stage cannot silently
substitute an easier rule.

The task deliberately does not target production MootOS source.  It exists to
exercise the factory, not to be difficult.
"""

import hashlib
import json
from dataclasses import dataclass, field

from .paths import PathCanonicalizationError, canonicalize_repo_path
from .text_safety import utf8_length


class ProofFixtureError(ValueError):
    """Raised when a fixture task contract cannot be safely declared."""


POLICY_VERSION = "cb-proof-fixture-v1"
MAX_FIXTURE_FILES = 8
MAX_FILE_BYTES = 4096
MAX_TOTAL_BYTES = 16384
MAX_PATH_BYTES = 512
MAX_TASK_ID_BYTES = 128
_TASK_TOKEN = object()
_FORBIDDEN_SEGMENTS = frozenset({"node_modules", "__pycache__"})


def _canonical(value):
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")


def _digest(value):
    return hashlib.sha256(value).hexdigest()


def safe_relative_path(value, label):
    """Canonicalize one fixture path and reject forbidden path classes."""
    try:
        canonical = canonicalize_repo_path(value)
    except PathCanonicalizationError as error:
        raise ProofFixtureError(f"{label} is unsafe") from error
    if canonical != value or utf8_length(canonical) > MAX_PATH_BYTES:
        raise ProofFixtureError(f"{label} is not canonical")
    for segment in canonical.split("/"):
        if segment.startswith(".") or segment in _FORBIDDEN_SEGMENTS:
            raise ProofFixtureError(f"{label} names a forbidden path class")
    return canonical


@dataclass(frozen=True)
class FixtureFile:
    """One exact file: trusted base input or expected candidate content."""

    relative_path: str
    content: bytes
    size_bytes: int
    content_sha256: str

    def __post_init__(self):
        safe_relative_path(self.relative_path, "fixture path")
        if not isinstance(self.content, bytes):
            raise ProofFixtureError("fixture content must be bytes")
        if len(self.content) > MAX_FILE_BYTES:
            raise ProofFixtureError("fixture content exceeds byte bound")
        if self.size_bytes != len(self.content) or self.content_sha256 != (
            _digest(self.content)
        ):
            raise ProofFixtureError("fixture content digest mismatch")

    def to_dict(self):
        return {
            "content_sha256": self.content_sha256,
            "relative_path": self.relative_path,
            "size_bytes": self.size_bytes,
        }


def _fixture_files(entries, label):
    if type(entries) is not tuple or not entries:
        raise ProofFixtureError(f"{label} must be a non-empty tuple")
    if len(entries) > MAX_FIXTURE_FILES:
        raise ProofFixtureError(f"{label} exceeds file-count bound")
    files = []
    for value in entries:
        if isinstance(value, FixtureFile):
            files.append(value)
            continue
        if type(value) is not tuple or len(value) != 2:
            raise ProofFixtureError(f"{label} entry is malformed")
        path, content = value
        if not isinstance(content, bytes):
            raise ProofFixtureError(f"{label} content must be bytes")
        files.append(
            FixtureFile(path, content, len(content), _digest(content))
        )
    files.sort(key=lambda item: item.relative_path)
    paths = tuple(item.relative_path for item in files)
    if len(set(paths)) != len(paths) or len(
        {path.casefold() for path in paths}
    ) != len(paths):
        raise ProofFixtureError(f"{label} paths collide")
    if sum(item.size_bytes for item in files) > MAX_TOTAL_BYTES:
        raise ProofFixtureError(f"{label} exceeds total byte bound")
    return tuple(files)


@dataclass(frozen=True)
class FixtureTaskContract:
    """Immutable, content-addressed declaration of the tiny proof task."""

    task_id: str
    base_fixture: tuple
    allowed_paths: tuple
    expected_artifacts: tuple
    max_artifact_count: int
    base_fixture_sha256: str
    allowed_paths_sha256: str
    acceptance_rule_sha256: str
    task_sha256: str
    policy_version: str = POLICY_VERSION
    result_trusted: bool = False
    worker_output_trusted: bool = False
    _task_token: object = field(default=None, repr=False, compare=False)

    def __post_init__(self):
        if self._task_token is not _TASK_TOKEN:
            raise ProofFixtureError("fixture task requires a trusted factory")
        if self.policy_version != POLICY_VERSION:
            raise ProofFixtureError("fixture task policy is unsupported")
        if not isinstance(self.task_id, str) or not self.task_id or (
            utf8_length(self.task_id) > MAX_TASK_ID_BYTES
        ):
            raise ProofFixtureError("fixture task ID is malformed")
        for name in ("base_fixture", "expected_artifacts"):
            value = getattr(self, name)
            if type(value) is not tuple or not value or any(
                not isinstance(item, FixtureFile) for item in value
            ):
                raise ProofFixtureError(f"{name} is malformed")
            paths = tuple(item.relative_path for item in value)
            if paths != tuple(sorted(paths)) or len(set(paths)) != len(paths):
                raise ProofFixtureError(f"{name} is not canonical")
        if type(self.allowed_paths) is not tuple or not self.allowed_paths:
            raise ProofFixtureError("allowed paths are malformed")
        for path in self.allowed_paths:
            safe_relative_path(path, "allowed path")
        if self.allowed_paths != tuple(sorted(self.allowed_paths)) or len(
            set(self.allowed_paths)
        ) != len(self.allowed_paths):
            raise ProofFixtureError("allowed paths are not canonical")
        if len({path.casefold() for path in self.allowed_paths}) != len(
            self.allowed_paths
        ):
            raise ProofFixtureError("allowed paths collide by case")
        if type(self.max_artifact_count) is not int or not (
            1 <= self.max_artifact_count <= len(self.allowed_paths)
        ):
            raise ProofFixtureError("artifact count bound is malformed")
        outside = tuple(
            item.relative_path for item in self.expected_artifacts
            if item.relative_path not in self.allowed_paths
        )
        if outside:
            raise ProofFixtureError(
                "expected artifacts fall outside the declared boundary"
            )
        if self.result_trusted is not False or (
            self.worker_output_trusted is not False
        ):
            raise ProofFixtureError("fixture task promotes trust")
        if self.base_fixture_sha256 != _digest(
            _canonical([item.to_dict() for item in self.base_fixture])
        ):
            raise ProofFixtureError("base fixture digest mismatch")
        if self.allowed_paths_sha256 != _digest(
            _canonical(list(self.allowed_paths))
        ):
            raise ProofFixtureError("allowed path digest mismatch")
        if self.acceptance_rule_sha256 != _digest(
            _canonical(self._acceptance_body())
        ):
            raise ProofFixtureError("acceptance rule digest mismatch")
        if self.task_sha256 != _digest(self._payload()):
            raise ProofFixtureError("fixture task digest mismatch")

    def base_content(self):
        """Trusted base bytes by path, for independent reconstruction."""
        return {item.relative_path: item.content for item in self.base_fixture}

    def expected_content(self):
        """Exact bytes an acceptable candidate must contain, by path."""
        return {
            item.relative_path: item.content
            for item in self.expected_artifacts
        }

    def _acceptance_body(self):
        return {
            "expected_artifacts": [
                item.to_dict() for item in self.expected_artifacts
            ],
            "policy_version": POLICY_VERSION,
            "rule": "exact_bytes_at_each_expected_path",
        }

    def _body(self):
        return {
            "acceptance_rule_sha256": self.acceptance_rule_sha256,
            "allowed_paths": list(self.allowed_paths),
            "allowed_paths_sha256": self.allowed_paths_sha256,
            "base_fixture": [item.to_dict() for item in self.base_fixture],
            "base_fixture_sha256": self.base_fixture_sha256,
            "max_artifact_count": self.max_artifact_count,
            "policy_version": POLICY_VERSION,
            "result_trusted": False,
            "task_id": self.task_id,
            "worker_output_trusted": False,
        }

    def _payload(self):
        return _canonical(self._body())

    def canonical_bytes(self):
        value = self._body()
        value["task_sha256"] = self.task_sha256
        return _canonical(value)


def create_fixture_task_contract(
    *,
    task_id,
    base_fixture,
    allowed_paths,
    expected_artifacts,
    max_artifact_count=None,
):
    """Build one immutable fixture task contract, failing closed."""
    base = _fixture_files(tuple(base_fixture), "base fixture")
    expected = _fixture_files(tuple(expected_artifacts), "expected artifacts")
    if type(allowed_paths) is not tuple:
        allowed_paths = tuple(allowed_paths)
    allowed = tuple(sorted(allowed_paths))
    values = {
        "task_id": task_id,
        "base_fixture": base,
        "allowed_paths": allowed,
        "expected_artifacts": expected,
        "max_artifact_count": (
            len(allowed) if max_artifact_count is None else max_artifact_count
        ),
        "base_fixture_sha256": _digest(
            _canonical([item.to_dict() for item in base])
        ),
        "allowed_paths_sha256": _digest(_canonical(list(allowed))),
    }
    provisional = object.__new__(FixtureTaskContract)
    for name, value in values.items():
        object.__setattr__(provisional, name, value)
    object.__setattr__(provisional, "policy_version", POLICY_VERSION)
    acceptance = _digest(_canonical(provisional._acceptance_body()))
    object.__setattr__(provisional, "acceptance_rule_sha256", acceptance)
    return FixtureTaskContract(
        **values,
        acceptance_rule_sha256=acceptance,
        task_sha256=_digest(provisional._payload()),
        _task_token=_TASK_TOKEN,
    )


def create_increment_value_task():
    """The CB-025 proof task: rewrite ``value.txt`` from ``1`` to ``2``."""
    return create_fixture_task_contract(
        task_id="cb025-increment-value",
        base_fixture=(("value.txt", b"1\n"),),
        allowed_paths=("value.txt",),
        expected_artifacts=(("value.txt", b"2\n"),),
        max_artifact_count=1,
    )
