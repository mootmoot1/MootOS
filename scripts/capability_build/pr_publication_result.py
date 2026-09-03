"""Offline intake for externally reported PR publication outcomes."""

import json
import re
from dataclasses import dataclass, field
from typing import Optional

from scripts.capability_build.pr_publication_action import (
    STATUS_ACTION_PREPARED,
    PRPublicationAction,
    prepare_pr_publication_action,
)
from scripts.capability_build.pr_publication_authorization import (
    OPERATION_CREATE_PULL_REQUEST,
)


class PRPublicationResultError(ValueError):
    """Raised when supplied receipt metadata is malformed or forged."""


OUTCOME_CREATED = "created"
OUTCOME_FAILED = "failed"
OUTCOME_NOT_ATTEMPTED = "not_attempted"
STATUS_PR_CREATED = "pr_created"
STATUS_CREATION_FAILED = "creation_failed"
STATUS_NOT_ATTEMPTED = "not_attempted"
STATUS_RESULT_REJECTED = "result_rejected"
MAX_IDENTITY_BYTES = 256
MAX_EXPLANATION_BYTES = 4096
MAX_PR_PUBLICATION_RESULT_INPUT_BYTES = 16 * 1024
MAX_PR_PUBLICATION_RESULT_SUMMARY_BYTES = 64 * 1024
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@/-]*$")
_SHA = re.compile(r"^[0-9a-f]{40,64}$")
_SECRET = re.compile(
    r"(?i)(?:token|password|secret|api[_-]?key|authorization)\s*[:=]"
)
_RESULT_REJECTED = "External result does not match authoritative action."


def _text(value, name, limit=MAX_IDENTITY_BYTES, pattern=_IDENTIFIER):
    if not isinstance(value, str) or not value.strip():
        raise PRPublicationResultError(f"{name} must be nonblank text")
    value = value.strip()
    if len(value.encode("utf-8")) > limit:
        raise PRPublicationResultError(f"{name} exceeds {limit} bytes")
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise PRPublicationResultError(f"{name} contains controls")
    if _SECRET.search(value):
        raise PRPublicationResultError(f"{name} contains secret-like text")
    if pattern is not None and pattern.fullmatch(value) is None:
        raise PRPublicationResultError(f"{name} is malformed")
    return value


@dataclass(frozen=True)
class PRPublicationResultInput:
    """Bounded external claim; it carries no independent verification."""

    result_id: str
    outcome: str
    idempotency_key: str
    authorization_id: str
    decision_id: str
    job_id: str
    package_id: str
    operation: str
    repository: str
    base_sha: str
    target_branch: str
    source_branch: str
    pr_number: Optional[int] = None
    pr_url: Optional[str] = None
    failure_classification: Optional[str] = None
    explanation: Optional[str] = None

    def __post_init__(self):
        for name in (
            "result_id", "authorization_id", "decision_id", "job_id",
            "package_id", "operation", "repository", "target_branch",
            "source_branch",
        ):
            object.__setattr__(self, name, _text(getattr(self, name), name))
        object.__setattr__(
            self, "idempotency_key",
            _text(self.idempotency_key, "idempotency_key", pattern=_SHA),
        )
        object.__setattr__(
            self, "base_sha", _text(self.base_sha, "base_sha", pattern=_SHA)
        )
        if self.outcome not in {
            OUTCOME_CREATED, OUTCOME_FAILED, OUTCOME_NOT_ATTEMPTED,
        }:
            raise PRPublicationResultError("unknown result outcome")
        if self.pr_url is not None:
            object.__setattr__(
                self, "pr_url", _text(
                    self.pr_url, "pr_url", limit=512, pattern=None
                )
            )
        if self.failure_classification is not None:
            object.__setattr__(
                self, "failure_classification",
                _text(self.failure_classification, "failure_classification"),
            )
        if self.explanation is not None:
            object.__setattr__(
                self, "explanation", _text(
                    self.explanation, "explanation",
                    limit=MAX_EXPLANATION_BYTES, pattern=None,
                )
            )
        if self.outcome == OUTCOME_CREATED:
            if type(self.pr_number) is not int or self.pr_number <= 0:
                raise PRPublicationResultError(
                    "created result requires positive PR number"
                )
            if self.pr_url is None:
                raise PRPublicationResultError(
                    "created result requires canonical PR URL"
                )
            if self.failure_classification or self.explanation:
                raise PRPublicationResultError(
                    "created result cannot include failure metadata"
                )
        else:
            if self.pr_number is not None or self.pr_url is not None:
                raise PRPublicationResultError(
                    "non-created result cannot claim PR identity"
                )
            if self.outcome == OUTCOME_FAILED:
                if self.failure_classification is None:
                    raise PRPublicationResultError(
                        "failed result requires failure classification"
                    )
            elif self.failure_classification is not None:
                raise PRPublicationResultError(
                    "not-attempted result cannot claim failure"
                )
            if self.outcome == OUTCOME_NOT_ATTEMPTED and not self.explanation:
                raise PRPublicationResultError(
                    "not-attempted result requires a reason"
                )
        if len(self.summary().encode("utf-8")) > (
            MAX_PR_PUBLICATION_RESULT_INPUT_BYTES
        ):
            raise PRPublicationResultError("result input exceeds bound")

    def to_dict(self):
        return {
            "authorization_id": self.authorization_id,
            "base_sha": self.base_sha,
            "decision_id": self.decision_id,
            "explanation": self.explanation,
            "failure_classification": self.failure_classification,
            "idempotency_key": self.idempotency_key,
            "job_id": self.job_id,
            "operation": self.operation,
            "outcome": self.outcome,
            "package_id": self.package_id,
            "pr_number": self.pr_number,
            "pr_url": self.pr_url,
            "repository": self.repository,
            "result_id": self.result_id,
            "source_branch": self.source_branch,
            "target_branch": self.target_branch,
        }

    def summary(self):
        return json.dumps(
            self.to_dict(), indent=2, sort_keys=True, ensure_ascii=False
        ) + "\n"


def expected_result_input(action, result_id, outcome, **outcome_metadata):
    """Construct the binding fields an external reporter must echo."""
    if not isinstance(action, PRPublicationAction):
        raise PRPublicationResultError("invalid publication action")
    scope = dict(action.scope) if action.scope is not None else {}
    return PRPublicationResultInput(
        result_id=result_id,
        outcome=outcome,
        idempotency_key=action.idempotency_key or "invalid",
        authorization_id=scope.get("authorization_id", "invalid"),
        decision_id=scope.get("decision_id", "invalid"),
        job_id=scope.get("job_id", "invalid"),
        package_id=scope.get("package_id", "invalid"),
        operation=scope.get("operation", "invalid"),
        repository=scope.get("repository", "invalid"),
        base_sha=scope.get("base_sha", "0" * 40),
        target_branch=scope.get("target_branch", "invalid"),
        source_branch=scope.get("source_branch", "invalid"),
        **outcome_metadata,
    )


def _authoritative(action):
    if (
        action.status != STATUS_ACTION_PREPARED
        or not action.action_prepared
        or not action.authorized
        or action.executed
        or action.execution_performed
    ):
        return False
    return prepare_pr_publication_action(action.authorization) == action


def _mismatch(action, supplied):
    if not _authoritative(action) or action.scope is None:
        return _RESULT_REJECTED
    scope = dict(action.scope)
    expected = {
        "authorization_id": scope["authorization_id"],
        "base_sha": scope["base_sha"],
        "decision_id": scope["decision_id"],
        "idempotency_key": action.idempotency_key,
        "job_id": scope["job_id"],
        "operation": OPERATION_CREATE_PULL_REQUEST,
        "package_id": scope["package_id"],
        "repository": scope["repository"],
        "source_branch": scope["source_branch"],
        "target_branch": scope["target_branch"],
    }
    mismatched = any(
        getattr(supplied, name) != value
        for name, value in expected.items()
    )
    if mismatched:
        return _RESULT_REJECTED
    if supplied.outcome == OUTCOME_CREATED:
        expected_url = (
            f"https://github.com/{scope['repository']}/pull/"
            f"{supplied.pr_number}"
        )
        if supplied.pr_url != expected_url:
            return _RESULT_REJECTED
    return None


@dataclass(frozen=True)
class PRPublicationResult:
    """Immutable receipt for one structurally validated external claim."""

    action: PRPublicationAction
    supplied: PRPublicationResultInput
    status: str
    blocking_reasons: tuple
    result_recorded: bool = field(init=False)
    externally_reported: bool = field(init=False)
    external_attempt_reported: bool = field(init=False)
    external_success_reported: bool = field(init=False)
    externally_verified: bool = field(default=False, init=False)
    reporter_authenticated: bool = field(default=False, init=False)
    execution_performed_by_this_module: bool = field(default=False, init=False)
    github_action_performed: bool = field(default=False, init=False)
    git_action_performed: bool = field(default=False, init=False)
    runtime_authority: bool = field(default=False, init=False)

    def __post_init__(self):
        if not isinstance(self.action, PRPublicationAction):
            raise PRPublicationResultError("invalid publication action")
        if not isinstance(self.supplied, PRPublicationResultInput):
            raise PRPublicationResultError("invalid external result input")
        reason = _mismatch(self.action, self.supplied)
        expected_status = STATUS_RESULT_REJECTED
        if reason is None:
            expected_status = {
                OUTCOME_CREATED: STATUS_PR_CREATED,
                OUTCOME_FAILED: STATUS_CREATION_FAILED,
                OUTCOME_NOT_ATTEMPTED: STATUS_NOT_ATTEMPTED,
            }[self.supplied.outcome]
        expected_reasons = () if reason is None else (reason,)
        if (
            self.status != expected_status
            or tuple(self.blocking_reasons) != expected_reasons
        ):
            raise PRPublicationResultError("publication result is forged")
        object.__setattr__(self, "result_recorded", reason is None)
        object.__setattr__(self, "externally_reported", reason is None)
        object.__setattr__(
            self, "external_attempt_reported",
            reason is None and self.supplied.outcome != OUTCOME_NOT_ATTEMPTED,
        )
        object.__setattr__(
            self, "external_success_reported",
            reason is None and self.supplied.outcome == OUTCOME_CREATED,
        )
        if len(self.summary().encode("utf-8")) > (
            MAX_PR_PUBLICATION_RESULT_SUMMARY_BYTES
        ):
            raise PRPublicationResultError("publication result exceeds bound")

    def to_dict(self):
        return {
            "audit": {
                "execution_performed_by_this_module": (
                    self.execution_performed_by_this_module
                ),
                "external_attempt_reported": self.external_attempt_reported,
                "external_success_reported": self.external_success_reported,
                "externally_reported": self.externally_reported,
                "externally_verified": self.externally_verified,
                "git_action_performed": self.git_action_performed,
                "github_action_performed": self.github_action_performed,
                "result_recorded": self.result_recorded,
                "reporter_authenticated": self.reporter_authenticated,
                "runtime_authority": self.runtime_authority,
            },
            "blocking_reasons": list(self.blocking_reasons),
            "receipt": self.supplied.to_dict(),
            "status": self.status,
        }

    def summary(self):
        return json.dumps(
            self.to_dict(), indent=2, sort_keys=True, ensure_ascii=False
        ) + "\n"


def record_pr_publication_result(action, supplied):
    if not isinstance(action, PRPublicationAction):
        raise PRPublicationResultError("invalid publication action")
    if not isinstance(supplied, PRPublicationResultInput):
        raise PRPublicationResultError("invalid external result input")
    reason = _mismatch(action, supplied)
    status = STATUS_RESULT_REJECTED
    if reason is None:
        status = {
            OUTCOME_CREATED: STATUS_PR_CREATED,
            OUTCOME_FAILED: STATUS_CREATION_FAILED,
            OUTCOME_NOT_ATTEMPTED: STATUS_NOT_ATTEMPTED,
        }[supplied.outcome]
    return PRPublicationResult(
        action=action,
        supplied=supplied,
        status=status,
        blocking_reasons=() if reason is None else (reason,),
    )
