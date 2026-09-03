"""Pure Markdown rendering for MootOS V0.4C PR packages.

This module turns an existing offline PR package proposal into bounded
human-readable Markdown. It performs no Git, GitHub, filesystem, registry,
installation, deployment, approval, process, network, or runtime action.
"""

import json
from dataclasses import dataclass, field

from scripts.capability_build.pr_package import (
    MAX_PR_PACKAGE_SUMMARY_BYTES,
    PRPackageProposal,
)


class PRPackageRenderError(ValueError):
    """Raised when PR package rendering input or output is unsafe."""


SCHEMA_VERSION = 1
# The proposal's bounded JSON is at most 128 KiB. Doubling that bound leaves
# deterministic room for Markdown headings and list syntax without reducing
# any valid proposal field or silently truncating review content.
MAX_RENDERED_PR_BODY_BYTES = 2 * MAX_PR_PACKAGE_SUMMARY_BYTES
MAX_REVIEW_SUMMARY_BYTES = 16 * 1024


def _has_control(value: str) -> bool:
    return any(
        (ord(character) < 32 and character not in ("\n", "\t"))
        or ord(character) == 127
        for character in value
    )


def _bounded_text(value: object, field_name: str, maximum_bytes: int) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PRPackageRenderError(f"{field_name} must be nonblank text")
    normalized = value.strip()
    if _has_control(normalized):
        raise PRPackageRenderError(f"{field_name} contains control characters")
    if len(normalized.encode("utf-8")) > maximum_bytes:
        raise PRPackageRenderError(
            f"{field_name} exceeds {maximum_bytes} bytes"
        )
    return normalized


def _require_package(proposal: object) -> PRPackageProposal:
    if not isinstance(proposal, PRPackageProposal):
        raise PRPackageRenderError("proposal must be a PRPackageProposal")
    return proposal


def _bullet(value: str) -> str:
    return f"- {value}"


def _changed_files(proposal: PRPackageProposal) -> str:
    return "\n".join(
        _bullet(
            f"`{item.path}` (`{item.operation}`): {item.summary}"
        )
        for item in proposal.changed_files
    )


def _evidence(proposal: PRPackageProposal) -> str:
    return "\n".join(
        _bullet(f"`{item.check_name}`: {item.status}")
        for item in proposal.evidence
    )


def _risks(proposal: PRPackageProposal) -> str:
    return "\n".join(
        _bullet(
            f"`{item.risk_id}` ({item.level}): "
            f"{item.summary} Mitigation: {item.mitigation}"
        )
        for item in proposal.risks
    )


def _rollback(proposal: PRPackageProposal) -> str:
    return "\n".join(
        f"{item.order}. {item.instruction}"
        for item in proposal.rollback_notes
    )


def _checklist(proposal: PRPackageProposal) -> str:
    return "\n".join(
        f"- [ ] {item.description}"
        for item in proposal.human_checklist
    )


def _blocking_reasons(proposal: PRPackageProposal) -> str:
    if not proposal.blocking_reasons:
        return "None"
    return "\n".join(_bullet(reason) for reason in proposal.blocking_reasons)


def render_pr_body(proposal: PRPackageProposal) -> str:
    """Render a deterministic Markdown body for later human PR creation."""
    package = _require_package(proposal)
    body = (
        "## Summary\n\n"
        f"{package.proposed_pr_body}\n\n"
        "## Package\n\n"
        f"- Package: `{package.package_id}`\n"
        f"- Job: `{package.job_id}`\n"
        f"- Capability: `{package.capability_id}`\n"
        f"- Base SHA: `{package.base_sha}`\n"
        f"- Target branch: `{package.target_branch}`\n"
        f"- Proposed branch: `{package.proposed_branch_name}`\n"
        f"- Readiness: `{package.readiness_status}`\n\n"
        "## Changed Files\n\n"
        f"{_changed_files(package)}\n\n"
        "## Evidence\n\n"
        f"{_evidence(package)}\n\n"
        "## Risks\n\n"
        f"{_risks(package)}\n\n"
        "## Rollback\n\n"
        f"{_rollback(package)}\n\n"
        "## Human Review Checklist\n\n"
        f"{_checklist(package)}\n\n"
        "## Blocking Reasons\n\n"
        f"{_blocking_reasons(package)}\n\n"
        "## Safety\n\n"
        "- Offline proposal only.\n"
        "- Proposal rendering only.\n"
        "- No Git, GitHub, filesystem, registry, install, deploy, "
        "approval, or runtime action performed.\n"
    )
    return _bounded_text(body, "rendered PR body", MAX_RENDERED_PR_BODY_BYTES)


def render_review_summary(proposal: PRPackageProposal) -> str:
    """Render a compact deterministic review summary for humans."""
    package = _require_package(proposal)
    counts = {}
    for item in package.evidence:
        counts[item.status] = counts.get(item.status, 0) + 1
    evidence_counts = ", ".join(
        f"{status}={counts[status]}" for status in sorted(counts)
    )
    blocking = (
        "None"
        if not package.blocking_reasons
        else str(len(package.blocking_reasons))
    )
    summary = (
        "## Review Summary\n\n"
        f"- Package: `{package.package_id}`\n"
        f"- Readiness: `{package.readiness_status}`\n"
        f"- Target: `{package.target_branch}`\n"
        f"- Proposed branch: `{package.proposed_branch_name}`\n"
        f"- Changed files: {len(package.changed_files)}\n"
        f"- Evidence: {evidence_counts}\n"
        f"- Blocking reasons: {blocking}\n"
        "- Authority: offline-only proposal; no Git or GitHub action.\n"
    )
    return _bounded_text(
        summary,
        "review summary",
        MAX_REVIEW_SUMMARY_BYTES,
    )


@dataclass(frozen=True)
class PRPackageRendering:
    """Immutable rendered Markdown derived from one PR package proposal."""

    proposal: PRPackageProposal
    pr_body: str
    review_summary: str
    schema_version: int = field(default=SCHEMA_VERSION, init=False)
    offline_only: bool = field(default=True, init=False)
    proposal_only: bool = field(default=True, init=False)
    github_action_performed: bool = field(default=False, init=False)
    git_action_performed: bool = field(default=False, init=False)
    human_approval_recorded: bool = field(default=False, init=False)
    runtime_authority: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        package = _require_package(self.proposal)
        expected_body = render_pr_body(package)
        expected_summary = render_review_summary(package)
        if self.pr_body != expected_body:
            raise PRPackageRenderError(
                "rendered PR body does not match the proposal"
            )
        if self.review_summary != expected_summary:
            raise PRPackageRenderError(
                "review summary does not match the proposal"
            )
        object.__setattr__(self, "pr_body", expected_body)
        object.__setattr__(self, "review_summary", expected_summary)

    def to_dict(self) -> dict:
        """Return deterministic inert rendering metadata."""
        return {
            "authority": {
                "git_action_performed": self.git_action_performed,
                "github_action_performed": self.github_action_performed,
                "human_approval_recorded": self.human_approval_recorded,
                "offline_only": self.offline_only,
                "proposal_only": self.proposal_only,
                "runtime_authority": self.runtime_authority,
            },
            "package_id": self.proposal.package_id,
            "pr_body": self.pr_body,
            "readiness_status": self.proposal.readiness_status,
            "review_summary": self.review_summary,
            "schema_version": self.schema_version,
        }

    def summary(self) -> str:
        """Return stable JSON for offline human inspection."""
        return json.dumps(
            self.to_dict(),
            indent=2,
            sort_keys=True,
            ensure_ascii=False,
        ) + "\n"


def render_pr_package(proposal: PRPackageProposal) -> PRPackageRendering:
    """Render both the PR body and review summary for a proposal."""
    package = _require_package(proposal)
    return PRPackageRendering(
        proposal=package,
        pr_body=render_pr_body(package),
        review_summary=render_review_summary(package),
    )
