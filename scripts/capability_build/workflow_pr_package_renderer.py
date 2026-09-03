"""Pure workflow adapter for MootOS V0.4C Slice 4 PR package rendering.

This module renders only the proposal bound to an authoritative workflow PR
package creation result. Rendering never records approval, advances workflow
state, or performs filesystem, process, network, Git, GitHub, backend, or
runtime actions.
"""

import json
from dataclasses import dataclass, field
from typing import Optional

from scripts.capability_build.pr_package import BLOCKED, READY
from scripts.capability_build.pr_package_renderer import (
    PRPackageRenderError,
    PRPackageRendering,
    render_pr_package,
)
from scripts.capability_build.workflow import WorkflowPlan
from scripts.capability_build.workflow_pr_package import (
    STATUS_PR_PACKAGE_CREATED,
    WorkflowPRPackageCreation,
)


class WorkflowPRPackageRenderError(ValueError):
    """Raised when workflow package rendering state is inconsistent."""


SCHEMA_VERSION = 1
STATUS_PR_PACKAGE_RENDERED = "pr_package_rendered"
STATUS_NOT_RENDERED = "not_rendered"
RESULT_STATUSES = (
    STATUS_PR_PACKAGE_RENDERED,
    STATUS_NOT_RENDERED,
)

DISPOSITION_READY_FOR_HUMAN_REVIEW = "ready_for_human_review"
DISPOSITION_BLOCKED_INSPECTION_ONLY = "blocked_inspection_only"
DISPOSITION_NOT_RENDERED = "not_rendered"
DISPOSITIONS = (
    DISPOSITION_READY_FOR_HUMAN_REVIEW,
    DISPOSITION_BLOCKED_INSPECTION_ONLY,
    DISPOSITION_NOT_RENDERED,
)

MAX_WORKFLOW_PR_PACKAGE_RENDERING_SUMMARY_BYTES = 1024 * 1024
_NOT_CREATED_REASON = "Authoritative PR package was not created."
_RENDER_FAILED_REASON = "Authoritative PR package rendering failed closed."


def _stable_reasons(values: object) -> tuple:
    if isinstance(values, (str, bytes)):
        raise WorkflowPRPackageRenderError(
            "blocking_reasons must be a sequence"
        )
    try:
        reasons = tuple(values)
    except TypeError as error:
        raise WorkflowPRPackageRenderError(
            "blocking_reasons must be a sequence"
        ) from error
    if any(not isinstance(reason, str) or not reason for reason in reasons):
        raise WorkflowPRPackageRenderError(
            "blocking_reasons must contain nonblank text"
        )
    return tuple(
        sorted(set(reasons), key=lambda reason: (reason.casefold(), reason))
    )


def _render_authoritative(
    creation: WorkflowPRPackageCreation,
) -> Optional[PRPackageRendering]:
    if (
        creation.status != STATUS_PR_PACKAGE_CREATED
        or not creation.created
        or creation.pr_package is None
    ):
        return None
    try:
        return render_pr_package(creation.pr_package)
    except (PRPackageRenderError, TypeError, ValueError):
        return None


def _expected_disposition(
    rendering: Optional[PRPackageRendering],
) -> str:
    if rendering is None:
        return DISPOSITION_NOT_RENDERED
    if rendering.proposal.readiness_status == READY:
        return DISPOSITION_READY_FOR_HUMAN_REVIEW
    if rendering.proposal.readiness_status == BLOCKED:
        return DISPOSITION_BLOCKED_INSPECTION_ONLY
    raise WorkflowPRPackageRenderError(
        "rendering proposal has unsupported disposition"
    )


def _expected_reasons(
    creation: WorkflowPRPackageCreation,
    rendering: Optional[PRPackageRendering],
) -> tuple:
    if rendering is not None:
        return _stable_reasons(rendering.proposal.blocking_reasons)
    if creation.pr_package is None:
        return _stable_reasons(
            creation.blocking_reasons or (_NOT_CREATED_REASON,)
        )
    return (_RENDER_FAILED_REASON,)


def _source_binding(creation: WorkflowPRPackageCreation) -> dict:
    package = creation.pr_package
    return {
        "package_creation": {
            "created": creation.created,
            "ready_for_pr": creation.ready_for_pr,
            "schema_version": creation.schema_version,
            "status": creation.status,
        },
        "package_identity": (
            None
            if package is None
            else {
                "base_sha": package.base_sha,
                "job_id": package.job_id,
                "package_id": package.package_id,
                "readiness_status": package.readiness_status,
            }
        ),
    }


@dataclass(frozen=True)
class WorkflowPRPackageRendering:
    """Immutable rendering result bound to one workflow package creation."""

    pr_package_creation: WorkflowPRPackageCreation
    rendering: Optional[PRPackageRendering]
    workflow: WorkflowPlan
    status: str
    disposition: str
    blocking_reasons: tuple
    schema_version: int = field(default=SCHEMA_VERSION, init=False)
    rendered: bool = field(init=False)
    ready_for_human_review: bool = field(init=False)
    inspection_only: bool = field(init=False)
    next_allowed_steps: tuple = field(init=False)
    offline_only: bool = field(default=True, init=False)
    proposal_only: bool = field(default=True, init=False)
    github_action_performed: bool = field(default=False, init=False)
    git_action_performed: bool = field(default=False, init=False)
    human_decision_recorded: bool = field(default=False, init=False)
    autonomous: bool = field(default=False, init=False)
    runtime_authority: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        if not isinstance(
            self.pr_package_creation,
            WorkflowPRPackageCreation,
        ):
            raise WorkflowPRPackageRenderError(
                "pr_package_creation must be a WorkflowPRPackageCreation"
            )
        if self.rendering is not None and not isinstance(
            self.rendering,
            PRPackageRendering,
        ):
            raise WorkflowPRPackageRenderError(
                "rendering must be a PRPackageRendering or None"
            )
        if not isinstance(self.workflow, WorkflowPlan):
            raise WorkflowPRPackageRenderError(
                "workflow must be a WorkflowPlan"
            )
        if self.status not in RESULT_STATUSES:
            raise WorkflowPRPackageRenderError(
                f"unsupported workflow rendering status: {self.status!r}"
            )
        if self.disposition not in DISPOSITIONS:
            raise WorkflowPRPackageRenderError(
                f"unsupported rendering disposition: {self.disposition!r}"
            )

        expected = _render_authoritative(self.pr_package_creation)
        if self.rendering != expected:
            raise WorkflowPRPackageRenderError(
                "rendering does not match authoritative PR package creation"
            )
        rendered = expected is not None
        expected_status = (
            STATUS_PR_PACKAGE_RENDERED if rendered else STATUS_NOT_RENDERED
        )
        if self.status != expected_status:
            raise WorkflowPRPackageRenderError(
                "result status does not match rendering result"
            )
        expected_disposition = _expected_disposition(expected)
        if self.disposition != expected_disposition:
            raise WorkflowPRPackageRenderError(
                "disposition does not match proposal readiness"
            )
        reasons = _stable_reasons(self.blocking_reasons)
        if reasons != _expected_reasons(self.pr_package_creation, expected):
            raise WorkflowPRPackageRenderError(
                "blocking reasons do not match rendering result"
            )
        if self.workflow is not self.pr_package_creation.workflow:
            raise WorkflowPRPackageRenderError(
                "PR package rendering must preserve the exact workflow"
            )

        object.__setattr__(self, "blocking_reasons", reasons)
        object.__setattr__(self, "rendered", rendered)
        object.__setattr__(
            self,
            "ready_for_human_review",
            expected_disposition == DISPOSITION_READY_FOR_HUMAN_REVIEW,
        )
        object.__setattr__(
            self,
            "inspection_only",
            expected_disposition == DISPOSITION_BLOCKED_INSPECTION_ONLY,
        )
        object.__setattr__(
            self,
            "next_allowed_steps",
            self.workflow.next_allowed_steps,
        )

        if len(self.summary().encode("utf-8")) > (
            MAX_WORKFLOW_PR_PACKAGE_RENDERING_SUMMARY_BYTES
        ):
            raise WorkflowPRPackageRenderError(
                "workflow PR package rendering summary exceeds "
                f"{MAX_WORKFLOW_PR_PACKAGE_RENDERING_SUMMARY_BYTES} bytes"
            )

    def to_dict(self) -> dict:
        """Return deterministic sanitized workflow rendering metadata."""
        return {
            "authority": {
                "autonomous": self.autonomous,
                "git_action_performed": self.git_action_performed,
                "github_action_performed": self.github_action_performed,
                "human_decision_recorded": self.human_decision_recorded,
                "offline_only": self.offline_only,
                "proposal_only": self.proposal_only,
                "runtime_authority": self.runtime_authority,
            },
            "blocking_reasons": list(self.blocking_reasons),
            "disposition": self.disposition,
            "inspection_only": self.inspection_only,
            "next_allowed_steps": list(self.next_allowed_steps),
            "ready_for_human_review": self.ready_for_human_review,
            "rendered": self.rendered,
            "rendering": (
                None if self.rendering is None else self.rendering.to_dict()
            ),
            "schema_version": self.schema_version,
            "source_binding": _source_binding(self.pr_package_creation),
            "status": self.status,
            "workflow": self.workflow.to_dict(),
        }

    def summary(self) -> str:
        """Return stable bounded JSON for offline human inspection."""
        return json.dumps(
            self.to_dict(),
            indent=2,
            sort_keys=True,
            ensure_ascii=False,
        ) + "\n"


def render_pr_package_from_workflow_creation(
    creation: WorkflowPRPackageCreation,
) -> WorkflowPRPackageRendering:
    """Render the proposal bound to an authoritative workflow result."""
    if not isinstance(creation, WorkflowPRPackageCreation):
        raise WorkflowPRPackageRenderError(
            "creation must be a WorkflowPRPackageCreation"
        )

    rendering = _render_authoritative(creation)
    disposition = _expected_disposition(rendering)
    return WorkflowPRPackageRendering(
        pr_package_creation=creation,
        rendering=rendering,
        workflow=creation.workflow,
        status=(
            STATUS_PR_PACKAGE_RENDERED
            if rendering is not None
            else STATUS_NOT_RENDERED
        ),
        disposition=disposition,
        blocking_reasons=_expected_reasons(creation, rendering),
    )
