"""Pure explicit PR publication authorization for MootOS V0.4C Slice 8."""

import hashlib
import json
import re
from dataclasses import dataclass, field

from scripts.capability_build.handoff import DECISION_APPROVE_FOR_PR
from scripts.capability_build.workflow_pr_decision import (
    STATUS_DECISION_RECORDED,
    WorkflowPRDecisionRecording,
)


class PRPublicationAuthorizationError(ValueError):
    """Raised when publication authorization metadata is malformed."""


STATUS_AUTHORIZED = "authorized"
STATUS_NOT_AUTHORIZED = "not_authorized"
OPERATION_CREATE_PULL_REQUEST = "create_pull_request"
EXPECTED_REPOSITORY = "mootmoot1/MootOS"
MAX_IDENTITY_BYTES = 128
MAX_AUTHORIZATION_SUMMARY_BYTES = 128 * 1024
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@/-]*$")
_SHA = re.compile(r"^[0-9a-f]{40,64}$")
_SECRET = re.compile(r"(?i)(?:token|password|secret|api[_-]?key)\s*[:=]")


def _text(value, name, limit=MAX_IDENTITY_BYTES, pattern=_IDENTIFIER):
    if not isinstance(value, str) or not value.strip():
        raise PRPublicationAuthorizationError(f"{name} must be nonblank text")
    value = value.strip()
    if len(value.encode("utf-8")) > limit:
        raise PRPublicationAuthorizationError(f"{name} exceeds {limit} bytes")
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise PRPublicationAuthorizationError(f"{name} contains controls")
    if _SECRET.search(value):
        raise PRPublicationAuthorizationError(
            f"{name} contains secret-like text"
        )
    if pattern is not None and pattern.fullmatch(value) is None:
        raise PRPublicationAuthorizationError(f"{name} is malformed")
    return value


def _digest(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class PRPublicationAuthorizationInput:
    """Explicit human-supplied scope for one future PR publication."""

    authorization_id: str
    authorizer_id: str
    decision_id: str
    job_id: str
    package_id: str
    repository: str
    target_branch: str
    base_sha: str
    source_branch: str
    title_sha256: str
    body_sha256: str
    operation: str = OPERATION_CREATE_PULL_REQUEST
    authorizer_authenticated: bool = field(default=False, init=False)

    def __post_init__(self):
        for name in (
            "authorization_id", "authorizer_id", "decision_id", "job_id",
            "package_id", "repository", "target_branch", "source_branch",
        ):
            object.__setattr__(self, name, _text(getattr(self, name), name))
        for name in ("base_sha", "title_sha256", "body_sha256"):
            object.__setattr__(
                self, name, _text(getattr(self, name), name, pattern=_SHA)
            )
        if self.operation != OPERATION_CREATE_PULL_REQUEST:
            raise PRPublicationAuthorizationError("unsupported operation")

    def to_dict(self):
        return {
            "authorization_id": self.authorization_id,
            "authorizer_authenticated": self.authorizer_authenticated,
            "authorizer_id": self.authorizer_id,
            "base_sha": self.base_sha,
            "body_sha256": self.body_sha256,
            "decision_id": self.decision_id,
            "job_id": self.job_id,
            "operation": self.operation,
            "package_id": self.package_id,
            "repository": self.repository,
            "source_branch": self.source_branch,
            "target_branch": self.target_branch,
            "title_sha256": self.title_sha256,
        }


def expected_authorization_input(decision, authorization_id, authorizer_id):
    """Return explicit metadata a human may separately choose to supply."""
    review = decision.review
    package = review.source_rendering.pr_package_creation.pr_package
    rendering = review.source_rendering.rendering
    if package is None or rendering is None:
        raise PRPublicationAuthorizationError("decision chain has no package")
    return PRPublicationAuthorizationInput(
        authorization_id=authorization_id,
        authorizer_id=authorizer_id,
        decision_id=decision.supplied.decision_id,
        job_id=package.job_id,
        package_id=package.package_id,
        repository=EXPECTED_REPOSITORY,
        target_branch=package.target_branch,
        base_sha=package.base_sha,
        source_branch=package.proposed_branch_name,
        title_sha256=_digest(package.proposed_pr_title),
        body_sha256=_digest(rendering.pr_body),
    )


def _mismatch(decision, supplied):
    if (
        decision.status != STATUS_DECISION_RECORDED
        or not decision.decision_recorded
        or decision.decision != DECISION_APPROVE_FOR_PR
        or not decision.eligible_for_pr_authorization
    ):
        return "Recorded decision is not eligible for PR authorization."
    expected = expected_authorization_input(
        decision, supplied.authorization_id, supplied.authorizer_id
    )
    for name in expected.to_dict():
        if name in ("authorizer_authenticated",):
            continue
        if getattr(supplied, name) != getattr(expected, name):
            return f"Authorization {name} does not match decision chain."
    return None


@dataclass(frozen=True)
class PRPublicationAuthorization:
    """One exact authorization record with no execution capability."""

    decision_recording: WorkflowPRDecisionRecording
    supplied: PRPublicationAuthorizationInput
    status: str
    blocking_reasons: tuple
    authorized: bool = field(init=False)
    authorizer_identity_bound: bool = field(init=False)
    authorizer_authenticated: bool = field(default=False, init=False)
    single_purpose: bool = field(default=True, init=False)
    action_prepared: bool = field(default=False, init=False)
    execution_performed: bool = field(default=False, init=False)
    git_action_performed: bool = field(default=False, init=False)
    github_action_performed: bool = field(default=False, init=False)
    runtime_authority: bool = field(default=False, init=False)

    def __post_init__(self):
        if not isinstance(
            self.decision_recording, WorkflowPRDecisionRecording
        ):
            raise PRPublicationAuthorizationError(
                "invalid decision recording"
            )
        if not isinstance(self.supplied, PRPublicationAuthorizationInput):
            raise PRPublicationAuthorizationError(
                "invalid authorization input"
            )
        reason = _mismatch(self.decision_recording, self.supplied)
        expected_status = (
            STATUS_AUTHORIZED if reason is None else STATUS_NOT_AUTHORIZED
        )
        expected_reasons = () if reason is None else (reason,)
        if (
            self.status != expected_status
            or tuple(self.blocking_reasons) != expected_reasons
        ):
            raise PRPublicationAuthorizationError(
                "authorization result is forged"
            )
        object.__setattr__(self, "authorized", reason is None)
        object.__setattr__(self, "authorizer_identity_bound", reason is None)
        if len(self.summary().encode("utf-8")) > (
            MAX_AUTHORIZATION_SUMMARY_BYTES
        ):
            raise PRPublicationAuthorizationError(
                "authorization summary exceeds bound"
            )

    def to_dict(self):
        return {
            "authority": {
                "action_prepared": self.action_prepared,
                "authorized": self.authorized,
                "authorizer_authenticated": self.authorizer_authenticated,
                "authorizer_identity_bound": self.authorizer_identity_bound,
                "execution_performed": self.execution_performed,
                "git_action_performed": self.git_action_performed,
                "github_action_performed": self.github_action_performed,
                "runtime_authority": self.runtime_authority,
                "single_purpose": self.single_purpose,
            },
            "blocking_reasons": list(self.blocking_reasons),
            "scope": self.supplied.to_dict(),
            "status": self.status,
        }

    def summary(self):
        return json.dumps(self.to_dict(), indent=2, sort_keys=True) + "\n"


def authorize_pr_publication(decision, supplied):
    if not isinstance(decision, WorkflowPRDecisionRecording):
        raise PRPublicationAuthorizationError("invalid decision recording")
    if not isinstance(supplied, PRPublicationAuthorizationInput):
        raise PRPublicationAuthorizationError("invalid authorization input")
    reason = _mismatch(decision, supplied)
    return PRPublicationAuthorization(
        decision_recording=decision,
        supplied=supplied,
        status=STATUS_AUTHORIZED if reason is None else STATUS_NOT_AUTHORIZED,
        blocking_reasons=() if reason is None else (reason,),
    )
