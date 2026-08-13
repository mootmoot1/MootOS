"""Pure returned-worker intake validation for V0.4A Slice 3.

The intake boundary validates supplied text records only. It does not read
or write files, apply patches, invoke Git, spawn processes, or execute any
returned code. Passing intake is not verification and grants no authority.
"""

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Optional

from scripts.capability_build.scope import (
    FrozenScope,
    ScopeDecision,
    ScopeError,
    normalize_repo_path,
)


class IntakeError(ValueError):
    """Raised when returned-file or worker-summary data is malformed."""


OPERATION_CREATE = "create"
OPERATION_MODIFY = "modify"
SUPPORTED_OPERATIONS = (OPERATION_CREATE, OPERATION_MODIFY)

MAX_RETURNED_FILES = 50
MAX_RETURNED_FILE_BYTES = 64 * 1024
MAX_RETURNED_TOTAL_BYTES = 256 * 1024
MAX_RETURNED_LINE_CHARACTERS = 500
MAX_SUMMARY_CHARACTERS = 20_000

_ALLOWED_CONTENT_CONTROLS = {"\t", "\n", "\r"}

_SECRET_RULES = (
    (
        "openai_style_token",
        re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b"),
    ),
    (
        "github_style_token",
        re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{20,}\b"),
    ),
    (
        "aws_access_key",
        re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
    ),
    (
        "literal_credential",
        re.compile(
            r"(?i)\b(?:api[_-]?key|access[_-]?token|auth[_-]?token|"
            r"client[_-]?secret|password|secret)\b\s*[:=]\s*"
            r"[\"'][^\"'\r\n]{8,}[\"']"
        ),
    ),
)

_DATA_ACCESS_RULES = (
    re.compile(
        r"(?i)\b(?:open|path|read_text|write_text|unlink|remove|rmdir|"
        r"sqlite3\.connect)\s*\([^\r\n)]*[\"'](?:\./)?data"
        r"(?:/|[\"'])"
    ),
    re.compile(
        r"(?im)^\s*(?:cat|cp|mv|rm|sqlite3)\s+[^\r\n]*\bdata/"
    ),
)

_PROCESS_RULES = (
    re.compile(r"\bsubprocess\b"),
    re.compile(r"\bos\s*\.\s*(?:system|popen|spawn[a-z_]*)\s*\("),
    re.compile(r"(?m)^\s*from\s+os\s+import\s+[^\r\n]*(?:system|popen)"),
    re.compile(r"\bshell\s*=\s*True\b"),
)

_GIT_RULES = (
    re.compile(r"(?m)^\s*(?:from|import)\s+(?:git|pygit2|dulwich)(?:\.|\s|$)"),
    re.compile(
        r"(?i)\bgit\s+(?:add|apply|checkout|clean|clone|commit|fetch|"
        r"merge|pull|push|rebase|reset|restore|switch|worktree)\b"
    ),
    re.compile(
        r"[\"']git[\"']\s*,\s*[\"'](?:add|apply|checkout|clean|clone|"
        r"commit|fetch|merge|pull|push|rebase|reset|restore|switch|"
        r"worktree)[\"']"
    ),
)

_RUNTIME_AUTHORITY_NAMES = (
    r"application|auth|main|tool_budget|tool_conversation|tool_executor|"
    r"tool_operations|tool_registry|tool_routes|tool_types|tool_validation"
)
_RUNTIME_AUTHORITY_RULE = re.compile(
    r"(?m)^\s*(?:"
    r"(?:from|import)\s+backend\.(?:"
    + _RUNTIME_AUTHORITY_NAMES
    + r")(?:\.|\s|$)|from\s+backend\s+import\s+(?:"
    + _RUNTIME_AUTHORITY_NAMES
    + r")\b)"
)


def _required_text(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise IntakeError(f"{field_name} is required and cannot be blank")
    return value.strip()


def _validate_text_content(content: Any) -> str:
    if not isinstance(content, str):
        raise IntakeError("Returned file content must be text")
    try:
        encoded = content.encode("utf-8")
    except UnicodeEncodeError as error:
        message = "Returned file content must be valid UTF-8 text"
        raise IntakeError(message) from error
    if len(encoded) > MAX_RETURNED_FILE_BYTES:
        raise IntakeError(
            f"Returned file content exceeds {MAX_RETURNED_FILE_BYTES} bytes"
        )
    for character in content:
        if (
            unicodedata.category(character) == "Cc"
            and character not in _ALLOWED_CONTENT_CONTROLS
        ):
            raise IntakeError(
                "Returned file content contains binary/control characters"
            )
    if any(
        len(line) > MAX_RETURNED_LINE_CHARACTERS
        for line in content.splitlines()
    ):
        raise IntakeError(
            "Returned file content exceeds the maximum line length"
        )
    return content


@dataclass(frozen=True)
class ReturnedFile:
    """One worker-returned file represented as inert UTF-8 text."""

    path: str
    operation: str
    content: str

    def __post_init__(self) -> None:
        if isinstance(self.path, str) and any(
            unicodedata.category(character) == "Cc"
            for character in self.path
        ):
            raise IntakeError(
                "Unsafe returned path: control characters are forbidden"
            )
        try:
            normalized_path = normalize_repo_path(self.path)
        except ScopeError as error:
            raise IntakeError(f"Unsafe returned path: {error}") from error
        if self.operation not in SUPPORTED_OPERATIONS:
            raise IntakeError(
                f"Unsupported returned-file operation: {self.operation!r}"
            )
        content = _validate_text_content(self.content)
        object.__setattr__(self, "path", normalized_path)
        object.__setattr__(self, "content", content)


@dataclass(frozen=True)
class WorkerSummary:
    """Optional untrusted worker narrative; never evidence or authority."""

    summary: str
    tests_run: tuple = ()

    def __post_init__(self) -> None:
        summary = _required_text(self.summary, "worker summary")
        if len(summary) > MAX_SUMMARY_CHARACTERS:
            raise IntakeError("Worker summary is too large")
        if isinstance(self.tests_run, (str, bytes)):
            raise IntakeError("tests_run must be a sequence of text entries")
        try:
            tests = tuple(
                _required_text(item, "declared test")
                for item in self.tests_run
            )
        except TypeError as error:
            raise IntakeError(
                "tests_run must be a sequence of text entries"
            ) from error
        object.__setattr__(self, "summary", summary)
        object.__setattr__(self, "tests_run", tests)

    def to_dict(self) -> dict:
        return {"summary": self.summary, "tests_run": list(self.tests_run)}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "WorkerSummary":
        if not isinstance(data, Mapping):
            raise IntakeError("Worker summary metadata must be an object")
        fields = {"summary", "tests_run"}
        unknown = set(data) - fields
        missing = fields - set(data)
        if unknown:
            names = ", ".join(sorted(unknown))
            raise IntakeError(f"Unknown worker-summary field(s): {names}")
        if missing:
            names = ", ".join(sorted(missing))
            raise IntakeError(f"Missing worker-summary field(s): {names}")
        return cls(summary=data["summary"], tests_run=data["tests_run"])


@dataclass(frozen=True)
class FileIntakeDecision:
    """Deterministic scope and safety decision for one returned file."""

    path: str
    operation: str
    accepted: bool
    scope_category: str
    scope_explanation: str
    blocking_findings: tuple = field(default_factory=tuple)


@dataclass(frozen=True)
class IntakeResult:
    """Structured fail-closed result for an entire returned package."""

    accepted: bool
    blocking_findings: tuple
    warnings: tuple
    touched_files: tuple
    file_decisions: tuple


def _path_identity(path: str) -> str:
    return unicodedata.normalize("NFC", path).casefold()


def _scope_decision(scope: FrozenScope, item: ReturnedFile) -> ScopeDecision:
    if item.operation == OPERATION_CREATE:
        return scope.decision_for_create(item.path)
    return scope.decision_for_modify(item.path)


def _safety_findings(item: ReturnedFile) -> tuple:
    findings = []
    for name, rule in _SECRET_RULES:
        if rule.search(item.content):
            findings.append(
                f"{item.path}: secret-like content detected ({name})"
            )
    if any(rule.search(item.content) for rule in _DATA_ACCESS_RULES):
        findings.append(
            f"{item.path}: returned content attempts to access data/"
        )
    if any(rule.search(item.content) for rule in _PROCESS_RULES):
        findings.append(
            f"{item.path}: subprocess or shell execution is forbidden"
        )
    if any(rule.search(item.content) for rule in _GIT_RULES):
        findings.append(
            f"{item.path}: Git automation is forbidden"
        )
    if _RUNTIME_AUTHORITY_RULE.search(item.content):
        findings.append(
            f"{item.path}: backend runtime-authority import is forbidden"
        )
    return tuple(sorted(set(findings)))


def _coerce_returned_files(values: Iterable[ReturnedFile]) -> tuple:
    if isinstance(values, (str, bytes)):
        raise IntakeError("returned_files must be a sequence")
    try:
        items = tuple(values)
    except TypeError as error:
        raise IntakeError("returned_files must be a sequence") from error
    if len(items) > MAX_RETURNED_FILES:
        raise IntakeError(
            f"Returned package exceeds {MAX_RETURNED_FILES} files"
        )
    if any(not isinstance(item, ReturnedFile) for item in items):
        raise IntakeError(
            "returned_files may contain only ReturnedFile values"
        )
    total_bytes = sum(len(item.content.encode("utf-8")) for item in items)
    if total_bytes > MAX_RETURNED_TOTAL_BYTES:
        raise IntakeError(
            f"Returned package exceeds {MAX_RETURNED_TOTAL_BYTES} bytes"
        )
    return tuple(
        sorted(
            items,
            key=lambda item: (
                _path_identity(item.path),
                item.path,
                item.operation,
                item.content,
            ),
        )
    )


def validate_returned_files(
    scope: FrozenScope,
    returned_files: Iterable[ReturnedFile],
    worker_summary: Optional[WorkerSummary] = None,
) -> IntakeResult:
    """Validate one inert returned package against its frozen write scope."""
    if not isinstance(scope, FrozenScope):
        raise IntakeError("scope must be a FrozenScope")
    if worker_summary is not None and not isinstance(
        worker_summary, WorkerSummary
    ):
        raise IntakeError("worker_summary must be a WorkerSummary")

    items = _coerce_returned_files(returned_files)
    if not items:
        return IntakeResult(
            accepted=False,
            blocking_findings=("returned package contains no files",),
            warnings=(),
            touched_files=(),
            file_decisions=(),
        )

    identities = {}
    for item in items:
        identities.setdefault(_path_identity(item.path), []).append(item)

    package_findings = []
    duplicate_findings = {}
    for identity, duplicates in identities.items():
        if len(duplicates) < 2:
            continue
        paths = tuple(sorted({item.path for item in duplicates}))
        operations = tuple(sorted({item.operation for item in duplicates}))
        display_path = paths[0]
        finding = f"duplicate returned path: {display_path}"
        package_findings.append(finding)
        duplicate_findings.setdefault(identity, []).append(finding)
        if len(operations) > 1:
            conflict = (
                f"conflicting operations for returned path: {display_path} "
                f"({', '.join(operations)})"
            )
            package_findings.append(conflict)
            duplicate_findings[identity].append(conflict)

    decisions = []
    for item in items:
        scope_decision = _scope_decision(scope, item)
        findings = list(duplicate_findings.get(_path_identity(item.path), ()))
        if not scope_decision.allowed:
            findings.append(
                f"{item.path}: {scope_decision.explanation}"
            )
        findings.extend(_safety_findings(item))
        stable_findings = tuple(sorted(set(findings)))
        package_findings.extend(stable_findings)
        decisions.append(
            FileIntakeDecision(
                path=item.path,
                operation=item.operation,
                accepted=not stable_findings,
                scope_category=scope_decision.category,
                scope_explanation=scope_decision.explanation,
                blocking_findings=stable_findings,
            )
        )

    warnings = ()
    if worker_summary is not None and not worker_summary.tests_run:
        warnings = ("worker summary declares no tests run",)

    stable_package_findings = tuple(sorted(set(package_findings)))
    touched_files = tuple(
        sorted(
            {item.path for item in items},
            key=lambda path: (_path_identity(path), path),
        )
    )
    return IntakeResult(
        accepted=not stable_package_findings,
        blocking_findings=stable_package_findings,
        warnings=warnings,
        touched_files=touched_files,
        file_decisions=tuple(decisions),
    )
