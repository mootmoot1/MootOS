"""Inert executor-neutral PR action envelope for MootOS V0.4C Slice 9."""

import hashlib
import json
from dataclasses import dataclass, field
from typing import Optional

from scripts.capability_build.pr_publication_authorization import (
    OPERATION_CREATE_PULL_REQUEST,
    STATUS_AUTHORIZED,
    PRPublicationAuthorization,
    authorize_pr_publication,
)


class PRPublicationActionError(ValueError):
    """Raised when an action envelope is inconsistent or forged."""


STATUS_ACTION_PREPARED = "action_prepared"
STATUS_NOT_PREPARED = "not_prepared"
MAX_PR_PUBLICATION_ACTION_SUMMARY_BYTES = 512 * 1024
_INVALID_AUTHORIZATION = "Publication authorization is not authoritative."


def _authoritative(authorization):
    if (
        authorization.status != STATUS_AUTHORIZED
        or not authorization.authorized
        or authorization.action_prepared
        or authorization.execution_performed
        or authorization.supplied.operation != OPERATION_CREATE_PULL_REQUEST
    ):
        return False
    expected = authorize_pr_publication(
        authorization.decision_recording, authorization.supplied
    )
    return expected == authorization


def _scope(authorization):
    decision = authorization.decision_recording
    review = decision.review
    package = review.source_rendering.pr_package_creation.pr_package
    rendering = review.source_rendering.rendering
    if package is None or rendering is None:
        return None
    supplied = authorization.supplied
    values = {
        "authorization_id": supplied.authorization_id,
        "base_sha": package.base_sha,
        "body": rendering.pr_body,
        "body_sha256": supplied.body_sha256,
        "decision_id": decision.supplied.decision_id,
        "job_id": package.job_id,
        "operation": OPERATION_CREATE_PULL_REQUEST,
        "package_id": package.package_id,
        "repository": supplied.repository,
        "source_branch": package.proposed_branch_name,
        "target_branch": package.target_branch,
        "title": package.proposed_pr_title,
        "title_sha256": supplied.title_sha256,
    }
    return tuple(sorted(values.items()))


def _identity(scope):
    canonical = json.dumps(
        dict(scope), sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class PRPublicationAction:
    """One exact permission-bearing packet with no execution facility."""

    authorization: PRPublicationAuthorization
    status: str
    scope: Optional[tuple]
    idempotency_key: Optional[str]
    blocking_reasons: tuple
    authorized: bool = field(init=False)
    action_prepared: bool = field(init=False)
    executed: bool = field(default=False, init=False)
    execution_performed: bool = field(default=False, init=False)
    github_action_performed: bool = field(default=False, init=False)
    git_action_performed: bool = field(default=False, init=False)
    authorizer_identity_bound: bool = field(init=False)
    authorizer_authenticated: bool = field(default=False, init=False)
    runtime_authority: bool = field(default=False, init=False)

    def __post_init__(self):
        if not isinstance(self.authorization, PRPublicationAuthorization):
            raise PRPublicationActionError("invalid publication authorization")
        valid = _authoritative(self.authorization)
        expected_scope = _scope(self.authorization) if valid else None
        expected_status = (
            STATUS_ACTION_PREPARED if valid else STATUS_NOT_PREPARED
        )
        expected_key = _identity(expected_scope) if valid else None
        expected_reasons = () if valid else (_INVALID_AUTHORIZATION,)
        if (
            self.status != expected_status
            or self.scope != expected_scope
            or self.idempotency_key != expected_key
            or tuple(self.blocking_reasons) != expected_reasons
        ):
            raise PRPublicationActionError("action envelope is forged")
        object.__setattr__(self, "authorized", valid)
        object.__setattr__(self, "action_prepared", valid)
        object.__setattr__(
            self,
            "authorizer_identity_bound",
            valid and self.authorization.authorizer_identity_bound,
        )
        if len(self.summary().encode("utf-8")) > (
            MAX_PR_PUBLICATION_ACTION_SUMMARY_BYTES
        ):
            raise PRPublicationActionError("action summary exceeds bound")

    def to_dict(self):
        return {
            "authority": {
                "action_prepared": self.action_prepared,
                "authorized": self.authorized,
                "authorizer_authenticated": self.authorizer_authenticated,
                "authorizer_identity_bound": self.authorizer_identity_bound,
                "executed": self.executed,
                "execution_performed": self.execution_performed,
                "git_action_performed": self.git_action_performed,
                "github_action_performed": self.github_action_performed,
                "runtime_authority": self.runtime_authority,
            },
            "blocking_reasons": list(self.blocking_reasons),
            "idempotency_key": self.idempotency_key,
            "scope": None if self.scope is None else dict(self.scope),
            "status": self.status,
        }

    def summary(self):
        return json.dumps(
            self.to_dict(), indent=2, sort_keys=True, ensure_ascii=False
        ) + "\n"


def prepare_pr_publication_action(authorization):
    if not isinstance(authorization, PRPublicationAuthorization):
        raise PRPublicationActionError("invalid publication authorization")
    valid = _authoritative(authorization)
    scope = _scope(authorization) if valid else None
    return PRPublicationAction(
        authorization=authorization,
        status=STATUS_ACTION_PREPARED if valid else STATUS_NOT_PREPARED,
        scope=scope,
        idempotency_key=_identity(scope) if valid else None,
        blocking_reasons=() if valid else (_INVALID_AUTHORIZATION,),
    )
