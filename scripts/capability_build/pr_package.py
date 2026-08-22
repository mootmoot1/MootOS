"""Pure offline PR package proposal data for MootOS V0.4C Slice 1.

The models in this module describe a bounded proposal for later human
review. They cannot create branches, commits, pull requests, registry
changes, installations, deployments, or approvals, and they perform no
filesystem, process, network, Git, GitHub, backend, or runtime operations.
"""

import json
import re
from dataclasses import dataclass, field
from typing import Any


class PRPackageError(ValueError):
    """Raised when a PR package proposal is unsafe or inconsistent."""


SCHEMA_VERSION = 1

READINESS_READY = "ready"
READINESS_BLOCKED = "blocked"
READY = READINESS_READY
BLOCKED = READINESS_BLOCKED
READINESS_STATUSES = (
    READINESS_READY,
    READINESS_BLOCKED,
)

FILE_OPERATION_CREATE = "create"
FILE_OPERATION_MODIFY = "modify"
FILE_OPERATION_DELETE = "delete"
FILE_OPERATIONS = (
    FILE_OPERATION_CREATE,
    FILE_OPERATION_MODIFY,
    FILE_OPERATION_DELETE,
)

EVIDENCE_PASSED = "passed"
EVIDENCE_FAILED = "failed"
EVIDENCE_BLOCKED = "blocked"
EVIDENCE_INCOMPLETE = "incomplete"
EVIDENCE_NOT_RUN = "not_run"
EVIDENCE_STATUSES = (
    EVIDENCE_PASSED,
    EVIDENCE_FAILED,
    EVIDENCE_BLOCKED,
    EVIDENCE_INCOMPLETE,
    EVIDENCE_NOT_RUN,
)

RISK_LOW = "low"
RISK_MEDIUM = "medium"
RISK_HIGH = "high"
RISK_CRITICAL = "critical"
RISK_LEVELS = (
    RISK_LOW,
    RISK_MEDIUM,
    RISK_HIGH,
    RISK_CRITICAL,
)

MAX_IDENTIFIER_BYTES = 128
MAX_BRANCH_BYTES = 255
MAX_PATH_BYTES = 512
MAX_TITLE_BYTES = 200
MAX_BODY_BYTES = 16 * 1024
MAX_ITEM_TEXT_BYTES = 2 * 1024
MAX_BLOCKING_REASON_BYTES = 2 * 1024
MAX_STRUCTURED_ITEMS = 128
MAX_PR_PACKAGE_SUMMARY_BYTES = 128 * 1024

_IDENTIFIER_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._-]*$"
_CAPABILITY_ID_PATTERN = r"^[a-z0-9][a-z0-9._-]*$"
_BASE_SHA_PATTERN = r"^[0-9a-f]{7,64}$"
_BRANCH_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._/-]*$"
_REPO_PATH_PATTERN = r"^[A-Za-z0-9._/-]+$"
_SENSITIVE_PATTERNS = (
    r"\bsk-[A-Za-z0-9_-]{20,}\b",
    (
        r"(?i)\b(?:api[_-]?key|access[_-]?token|secret|password)"
        r"\s*[:=]\s*[\"']?[A-Za-z0-9_./+-]{16,}"
    ),
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
)


def _has_control(value: str, allow_multiline: bool) -> bool:
    allowed = ("\n", "\t") if allow_multiline else ()
    return any(
        (ord(character) < 32 and character not in allowed)
        or ord(character) == 127
        for character in value
    )


def _reject_sensitive(value: str, field_name: str) -> None:
    if any(re.search(pattern, value) for pattern in _SENSITIVE_PATTERNS):
        raise PRPackageError(
            f"{field_name} contains secret-like material"
        )


def _bounded_text(
    value: Any,
    field_name: str,
    maximum_bytes: int,
    *,
    allow_multiline: bool = False,
) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PRPackageError(f"{field_name} must be nonblank text")
    normalized = value.strip()
    if _has_control(normalized, allow_multiline):
        raise PRPackageError(f"{field_name} contains control characters")
    if len(normalized.encode("utf-8")) > maximum_bytes:
        raise PRPackageError(
            f"{field_name} exceeds {maximum_bytes} bytes"
        )
    _reject_sensitive(normalized, field_name)
    return normalized


def _identifier(value: Any, field_name: str, pattern: Any) -> str:
    normalized = _bounded_text(
        value,
        field_name,
        MAX_IDENTIFIER_BYTES,
    )
    if re.fullmatch(pattern, normalized) is None:
        raise PRPackageError(f"{field_name} is malformed")
    return normalized


def _branch_name(value: Any, field_name: str) -> str:
    branch = _bounded_text(value, field_name, MAX_BRANCH_BYTES)
    if re.fullmatch(_BRANCH_PATTERN, branch) is None:
        raise PRPackageError(f"{field_name} is unsafe")
    if (
        branch.endswith(("/", ".", ".lock"))
        or "//" in branch
        or ".." in branch
        or "@{" in branch
    ):
        raise PRPackageError(f"{field_name} is unsafe")
    components = branch.split("/")
    if any(
        not component
        or component in (".", "..")
        or component.startswith(".")
        or component.endswith((".", ".lock"))
        for component in components
    ):
        raise PRPackageError(f"{field_name} is unsafe")
    return branch


def _repo_path(value: Any) -> str:
    path = _bounded_text(value, "file path", MAX_PATH_BYTES)
    if (
        re.fullmatch(_REPO_PATH_PATTERN, path) is None
        or path.startswith("/")
        or path.endswith("/")
        or "//" in path
        or "\\" in path
    ):
        raise PRPackageError("file path is unsafe")
    components = path.split("/")
    if any(component in ("", ".", "..") for component in components):
        raise PRPackageError("file path is unsafe")
    return path


def _structured_items(
    values: Any,
    field_name: str,
    item_type: Any,
    identity: Any,
    ordering: Any,
) -> tuple:
    if isinstance(values, (str, bytes)):
        raise PRPackageError(f"{field_name} must be a sequence")
    try:
        items = tuple(values)
    except TypeError as error:
        raise PRPackageError(f"{field_name} must be a sequence") from error
    if not items:
        raise PRPackageError(f"{field_name} must not be empty")
    if len(items) > MAX_STRUCTURED_ITEMS:
        raise PRPackageError(
            f"{field_name} exceeds {MAX_STRUCTURED_ITEMS} items"
        )
    if any(not isinstance(item, item_type) for item in items):
        raise PRPackageError(
            f"{field_name} must contain {item_type.__name__} values"
        )
    identities = [identity(item) for item in items]
    if len(identities) != len(set(identities)):
        raise PRPackageError(f"{field_name} contains duplicates")
    return tuple(sorted(items, key=ordering))


def _blocking_reasons(values: Any) -> tuple:
    if isinstance(values, (str, bytes)):
        raise PRPackageError("blocking_reasons must be a sequence")
    try:
        reasons = tuple(values)
    except TypeError as error:
        raise PRPackageError(
            "blocking_reasons must be a sequence"
        ) from error
    if len(reasons) > MAX_STRUCTURED_ITEMS:
        raise PRPackageError(
            f"blocking_reasons exceeds {MAX_STRUCTURED_ITEMS} items"
        )
    normalized = tuple(
        _bounded_text(
            reason,
            "blocking reason",
            MAX_BLOCKING_REASON_BYTES,
        )
        for reason in reasons
    )
    identities = [reason.casefold() for reason in normalized]
    if len(identities) != len(set(identities)):
        raise PRPackageError("blocking_reasons contains duplicates")
    return tuple(
        sorted(normalized, key=lambda reason: (reason.casefold(), reason))
    )


@dataclass(frozen=True)
class PRFileSummary:
    """One bounded changed-file description without file content."""

    path: str
    operation: str
    summary: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "path", _repo_path(self.path))
        if self.operation not in FILE_OPERATIONS:
            raise PRPackageError(
                f"unsupported file operation: {self.operation!r}"
            )
        object.__setattr__(
            self,
            "summary",
            _bounded_text(
                self.summary,
                "file summary",
                MAX_ITEM_TEXT_BYTES,
            ),
        )

    def to_dict(self) -> dict:
        return {
            "operation": self.operation,
            "path": self.path,
            "summary": self.summary,
        }


@dataclass(frozen=True)
class PREvidenceSummary:
    """One verification result without command arguments or output."""

    check_name: str
    status: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "check_name",
            _identifier(
                self.check_name,
                "evidence check name",
                _IDENTIFIER_PATTERN,
            ),
        )
        if self.status not in EVIDENCE_STATUSES:
            raise PRPackageError(
                f"unsupported evidence status: {self.status!r}"
            )

    def to_dict(self) -> dict:
        return {
            "check_name": self.check_name,
            "status": self.status,
        }


@dataclass(frozen=True)
class PRRiskSummary:
    """One bounded risk and mitigation statement."""

    risk_id: str
    level: str
    summary: str
    mitigation: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "risk_id",
            _identifier(self.risk_id, "risk id", _IDENTIFIER_PATTERN),
        )
        if self.level not in RISK_LEVELS:
            raise PRPackageError(f"unsupported risk level: {self.level!r}")
        for field_name in ("summary", "mitigation"):
            object.__setattr__(
                self,
                field_name,
                _bounded_text(
                    getattr(self, field_name),
                    f"risk {field_name}",
                    MAX_ITEM_TEXT_BYTES,
                ),
            )

    def to_dict(self) -> dict:
        return {
            "level": self.level,
            "mitigation": self.mitigation,
            "risk_id": self.risk_id,
            "summary": self.summary,
        }


@dataclass(frozen=True)
class PRRollbackNote:
    """One ordered, descriptive rollback note with no executable action."""

    order: int
    instruction: str

    def __post_init__(self) -> None:
        if (
            isinstance(self.order, bool)
            or not isinstance(self.order, int)
            or self.order <= 0
        ):
            raise PRPackageError("rollback order must be a positive integer")
        object.__setattr__(
            self,
            "instruction",
            _bounded_text(
                self.instruction,
                "rollback instruction",
                MAX_ITEM_TEXT_BYTES,
            ),
        )

    def to_dict(self) -> dict:
        return {
            "instruction": self.instruction,
            "order": self.order,
        }


@dataclass(frozen=True)
class PRChecklistItem:
    """One inert human-review prompt without approval state."""

    item_id: str
    description: str
    required: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "item_id",
            _identifier(
                self.item_id,
                "checklist item id",
                _IDENTIFIER_PATTERN,
            ),
        )
        object.__setattr__(
            self,
            "description",
            _bounded_text(
                self.description,
                "checklist description",
                MAX_ITEM_TEXT_BYTES,
            ),
        )
        if not isinstance(self.required, bool):
            raise PRPackageError("checklist required must be a boolean")

    def to_dict(self) -> dict:
        return {
            "description": self.description,
            "item_id": self.item_id,
            "required": self.required,
        }


@dataclass(frozen=True)
class PRPackageProposal:
    """Immutable PR-ready metadata with no GitHub or approval authority."""

    package_id: str
    job_id: str
    capability_id: str
    base_sha: str
    target_branch: str
    proposed_branch_name: str
    proposed_commit_title: str
    proposed_pr_title: str
    proposed_pr_body: str
    changed_files: tuple
    evidence: tuple
    risks: tuple
    rollback_notes: tuple
    human_checklist: tuple
    readiness_status: str
    blocking_reasons: tuple = ()
    schema_version: int = field(default=SCHEMA_VERSION, init=False)
    offline_only: bool = field(default=True, init=False)
    proposal_only: bool = field(default=True, init=False)
    github_action_performed: bool = field(default=False, init=False)
    git_action_performed: bool = field(default=False, init=False)
    human_approval_recorded: bool = field(default=False, init=False)
    runtime_authority: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "package_id",
            _identifier(
                self.package_id,
                "package id",
                _IDENTIFIER_PATTERN,
            ),
        )
        object.__setattr__(
            self,
            "job_id",
            _identifier(self.job_id, "job id", _IDENTIFIER_PATTERN),
        )
        object.__setattr__(
            self,
            "capability_id",
            _identifier(
                self.capability_id,
                "capability id",
                _CAPABILITY_ID_PATTERN,
            ),
        )
        object.__setattr__(
            self,
            "base_sha",
            _identifier(self.base_sha, "base sha", _BASE_SHA_PATTERN),
        )

        target_branch = _branch_name(self.target_branch, "target branch")
        proposed_branch = _branch_name(
            self.proposed_branch_name,
            "proposed branch name",
        )
        if target_branch == proposed_branch:
            raise PRPackageError(
                "proposed branch name must differ from target branch"
            )
        object.__setattr__(self, "target_branch", target_branch)
        object.__setattr__(
            self,
            "proposed_branch_name",
            proposed_branch,
        )

        for field_name in (
            "proposed_commit_title",
            "proposed_pr_title",
        ):
            object.__setattr__(
                self,
                field_name,
                _bounded_text(
                    getattr(self, field_name),
                    field_name,
                    MAX_TITLE_BYTES,
                ),
            )
        object.__setattr__(
            self,
            "proposed_pr_body",
            _bounded_text(
                self.proposed_pr_body,
                "proposed_pr_body",
                MAX_BODY_BYTES,
                allow_multiline=True,
            ),
        )

        object.__setattr__(
            self,
            "changed_files",
            _structured_items(
                self.changed_files,
                "changed_files",
                PRFileSummary,
                lambda item: item.path.casefold(),
                lambda item: (
                    item.path.casefold(),
                    item.path,
                    item.operation,
                ),
            ),
        )
        object.__setattr__(
            self,
            "evidence",
            _structured_items(
                self.evidence,
                "evidence",
                PREvidenceSummary,
                lambda item: item.check_name.casefold(),
                lambda item: (
                    item.check_name.casefold(),
                    item.check_name,
                ),
            ),
        )
        object.__setattr__(
            self,
            "risks",
            _structured_items(
                self.risks,
                "risks",
                PRRiskSummary,
                lambda item: item.risk_id.casefold(),
                lambda item: (item.risk_id.casefold(), item.risk_id),
            ),
        )
        object.__setattr__(
            self,
            "rollback_notes",
            _structured_items(
                self.rollback_notes,
                "rollback_notes",
                PRRollbackNote,
                lambda item: item.order,
                lambda item: item.order,
            ),
        )
        object.__setattr__(
            self,
            "human_checklist",
            _structured_items(
                self.human_checklist,
                "human_checklist",
                PRChecklistItem,
                lambda item: item.item_id.casefold(),
                lambda item: (item.item_id.casefold(), item.item_id),
            ),
        )

        if self.readiness_status not in READINESS_STATUSES:
            raise PRPackageError(
                f"unsupported readiness status: {self.readiness_status!r}"
            )
        reasons = _blocking_reasons(self.blocking_reasons)
        if self.readiness_status == READINESS_READY and reasons:
            raise PRPackageError(
                "ready proposals cannot contain blocking reasons"
            )
        if self.readiness_status == READINESS_BLOCKED and not reasons:
            raise PRPackageError(
                "blocked proposals require blocking reasons"
            )
        object.__setattr__(self, "blocking_reasons", reasons)

        if len(self.summary().encode("utf-8")) > (
            MAX_PR_PACKAGE_SUMMARY_BYTES
        ):
            raise PRPackageError(
                "PR package summary exceeds "
                f"{MAX_PR_PACKAGE_SUMMARY_BYTES} bytes"
            )

    def to_dict(self) -> dict:
        """Return stable bounded proposal metadata for human inspection."""
        return {
            "authority": {
                "git_action_performed": self.git_action_performed,
                "github_action_performed": self.github_action_performed,
                "human_approval_recorded": self.human_approval_recorded,
                "offline_only": self.offline_only,
                "proposal_only": self.proposal_only,
                "runtime_authority": self.runtime_authority,
            },
            "base_sha": self.base_sha,
            "blocking_reasons": list(self.blocking_reasons),
            "capability_id": self.capability_id,
            "changed_files": [
                item.to_dict() for item in self.changed_files
            ],
            "evidence": [item.to_dict() for item in self.evidence],
            "human_checklist": [
                item.to_dict() for item in self.human_checklist
            ],
            "job_id": self.job_id,
            "package_id": self.package_id,
            "proposal": {
                "branch_name": self.proposed_branch_name,
                "commit_title": self.proposed_commit_title,
                "pr_body": self.proposed_pr_body,
                "pr_title": self.proposed_pr_title,
                "target_branch": self.target_branch,
            },
            "readiness_status": self.readiness_status,
            "risks": [item.to_dict() for item in self.risks],
            "rollback_notes": [
                item.to_dict() for item in self.rollback_notes
            ],
            "schema_version": self.schema_version,
        }

    def summary(self) -> str:
        """Return deterministic JSON without operational or raw artifacts."""
        return json.dumps(
            self.to_dict(),
            indent=2,
            sort_keys=True,
            ensure_ascii=False,
        ) + "\n"
