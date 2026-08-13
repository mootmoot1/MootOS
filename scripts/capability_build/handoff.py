"""Pure human handoff packages for MootOS V0.4A Slice 6.

This module converts an immutable Slice 5 review bundle into bounded,
deterministic handoff data. A handoff is review-only: it cannot create a PR,
invoke Git or GitHub, execute commands, mutate files, register capabilities,
install anything, or deploy anything.
"""

import json
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Optional

from scripts.capability_build.bundle import (
    READINESS_BLOCKED,
    READINESS_INCOMPLETE,
    READINESS_READY,
    BuildMetadata,
    BuildReviewBundle,
)


class HandoffError(ValueError):
    """Raised when handoff data is missing, unsafe, or inconsistent."""


SCHEMA_VERSION = 1
MAX_HANDOFF_TEXT_BYTES = 4_096
MAX_HANDOFF_SUMMARY_BYTES = 32 * 1024

DECISION_APPROVE_FOR_PR = "approve_for_pr"
DECISION_REQUEST_CHANGES = "request_changes"
DECISION_REJECT = "reject"
HUMAN_DECISION_OPTIONS = (
    DECISION_APPROVE_FOR_PR,
    DECISION_REQUEST_CHANGES,
    DECISION_REJECT,
)

HUMAN_REVIEW_CHECKLIST = (
    "Read the complete Slice 5 review bundle and returned diff.",
    "Confirm touched files match the frozen approved scope.",
    "Review intake findings and warnings in the review bundle.",
    "Review every planned verification and its evidence status.",
    "Confirm this handoff grants no runtime or deployment authority.",
    "Choose approve for PR, request changes, or reject explicitly.",
)

_READINESS_VALUES = (
    READINESS_READY,
    READINESS_BLOCKED,
    READINESS_INCOMPLETE,
)
_EVIDENCE_VALUES = ("passed", "failed", "blocked", "incomplete")
_DECISION_ORDER = {
    option: index for index, option in enumerate(HUMAN_DECISION_OPTIONS)
}
_DECISION_EXPLANATIONS = {
    (DECISION_APPROVE_FOR_PR, True): (
        "Available because every handoff precondition is satisfied."
    ),
    (DECISION_APPROVE_FOR_PR, False): (
        "Unavailable until every handoff precondition passes."
    ),
    (DECISION_REQUEST_CHANGES, True): (
        "Return the package for bounded human-requested changes."
    ),
    (DECISION_REJECT, True): (
        "Reject the package without creating or merging a PR."
    ),
}


def _bounded_text(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise HandoffError(f"{field_name} must be nonblank text")
    normalized = value.strip()
    if any(
        unicodedata.category(character) == "Cc"
        for character in normalized
    ):
        raise HandoffError(f"{field_name} contains control characters")
    if len(normalized.encode("utf-8")) > MAX_HANDOFF_TEXT_BYTES:
        raise HandoffError(
            f"{field_name} exceeds {MAX_HANDOFF_TEXT_BYTES} bytes"
        )
    return normalized


def _ordered_text(values: Any, field_name: str) -> tuple:
    if isinstance(values, (str, bytes)):
        raise HandoffError(f"{field_name} must be a sequence")
    try:
        items = tuple(values)
    except TypeError as error:
        raise HandoffError(f"{field_name} must be a sequence") from error

    normalized = []
    identities = set()
    for item in items:
        value = _bounded_text(item, field_name)
        identity = unicodedata.normalize("NFC", value).casefold()
        if identity in identities:
            raise HandoffError(f"duplicate {field_name}: {value}")
        identities.add(identity)
        normalized.append(value)
    return tuple(
        sorted(
            normalized,
            key=lambda value: (
                unicodedata.normalize("NFC", value).casefold(),
                value,
            ),
        )
    )


@dataclass(frozen=True)
class HandoffDecisionOption:
    """One inert human decision choice and whether it is currently allowed."""

    name: str
    available: bool
    explanation: str

    def __post_init__(self) -> None:
        name = _bounded_text(self.name, "decision name")
        if name not in HUMAN_DECISION_OPTIONS:
            raise HandoffError(f"unsupported human decision: {name!r}")
        if not isinstance(self.available, bool):
            raise HandoffError("decision availability must be a boolean")
        explanation = _bounded_text(
            self.explanation, "decision explanation"
        )
        expected_explanation = _DECISION_EXPLANATIONS.get(
            (name, self.available)
        )
        if expected_explanation is None or explanation != expected_explanation:
            raise HandoffError(
                "decision explanation does not match the fixed option text"
            )
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "explanation", explanation)

    def to_dict(self) -> dict:
        return {
            "available": self.available,
            "explanation": self.explanation,
            "name": self.name,
        }


def _approval_blockers(
    *,
    bundle_readiness_status: str,
    bundle_review_only: bool,
    bundle_runtime_authority: bool,
    intake_accepted: bool,
    verification_plan_present: bool,
    evidence_present: bool,
    evidence_accepted: Optional[bool],
    evidence_status: Optional[str],
) -> tuple:
    reasons = []
    if bundle_readiness_status == READINESS_BLOCKED:
        reasons.append("The Slice 5 review bundle is blocked.")
    elif bundle_readiness_status == READINESS_INCOMPLETE:
        reasons.append("The Slice 5 review bundle is incomplete.")
    if bundle_review_only is not True:
        reasons.append("The Slice 5 bundle is not marked review-only.")
    if bundle_runtime_authority is not False:
        reasons.append("The Slice 5 bundle claims runtime authority.")
    if intake_accepted is not True:
        reasons.append("Returned-worker intake was not accepted.")
    if verification_plan_present is not True:
        reasons.append("The verification plan is missing.")
    if evidence_present is not True:
        reasons.append("Verification evidence is missing.")
    else:
        if evidence_status != "passed":
            reasons.append(
                "Verification evidence status is "
                f"{evidence_status or 'unknown'}."
            )
        if evidence_accepted is not True:
            reasons.append("Verification evidence was not accepted.")
    return _ordered_text(reasons, "approval blocker")


def _decision_options(approvable: bool) -> tuple:
    options = (
        HandoffDecisionOption(
            name=DECISION_APPROVE_FOR_PR,
            available=approvable,
            explanation=_DECISION_EXPLANATIONS[
                (DECISION_APPROVE_FOR_PR, approvable)
            ],
        ),
        HandoffDecisionOption(
            name=DECISION_REQUEST_CHANGES,
            available=True,
            explanation=_DECISION_EXPLANATIONS[
                (DECISION_REQUEST_CHANGES, True)
            ],
        ),
        HandoffDecisionOption(
            name=DECISION_REJECT,
            available=True,
            explanation=_DECISION_EXPLANATIONS[
                (DECISION_REJECT, True)
            ],
        ),
    )
    return options


@dataclass(frozen=True)
class HumanHandoffPackage:
    """Immutable PR-readiness information with no PR or runtime authority."""

    bundle_readiness_status: str
    job: BuildMetadata
    touched_files: tuple
    bundle_review_only: bool
    bundle_runtime_authority: bool
    intake_accepted: bool
    verification_plan_present: bool
    evidence_present: bool
    evidence_accepted: Optional[bool]
    evidence_status: Optional[str]
    approvable: bool
    blocking_reasons: tuple
    checklist: tuple
    decision_options: tuple
    schema_version: int = field(default=SCHEMA_VERSION, init=False)
    handoff_only: bool = field(default=True, init=False)
    runtime_authority: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        if self.bundle_readiness_status not in _READINESS_VALUES:
            raise HandoffError(
                "unsupported bundle readiness status: "
                f"{self.bundle_readiness_status!r}"
            )
        if not isinstance(self.job, BuildMetadata):
            raise HandoffError("job metadata is required")
        touched_files = _ordered_text(self.touched_files, "touched file")
        for field_name in (
            "bundle_review_only",
            "bundle_runtime_authority",
            "intake_accepted",
            "verification_plan_present",
            "evidence_present",
            "approvable",
        ):
            if not isinstance(getattr(self, field_name), bool):
                raise HandoffError(f"{field_name} must be a boolean")
        if self.evidence_accepted is not None and not isinstance(
            self.evidence_accepted, bool
        ):
            raise HandoffError("evidence_accepted must be a boolean or None")
        if self.evidence_status is not None and (
            self.evidence_status not in _EVIDENCE_VALUES
        ):
            raise HandoffError(
                f"unsupported evidence status: {self.evidence_status!r}"
            )
        if self.evidence_present != (
            self.evidence_accepted is not None
            and self.evidence_status is not None
        ):
            raise HandoffError(
                "evidence presence does not match its acceptance and status"
            )
        if self.evidence_present and self.evidence_accepted != (
            self.evidence_status == "passed"
        ):
            raise HandoffError(
                "evidence acceptance does not match its status"
            )

        expected_blockers = _approval_blockers(
            bundle_readiness_status=self.bundle_readiness_status,
            bundle_review_only=self.bundle_review_only,
            bundle_runtime_authority=self.bundle_runtime_authority,
            intake_accepted=self.intake_accepted,
            verification_plan_present=self.verification_plan_present,
            evidence_present=self.evidence_present,
            evidence_accepted=self.evidence_accepted,
            evidence_status=self.evidence_status,
        )
        blockers = _ordered_text(self.blocking_reasons, "approval blocker")
        if blockers != expected_blockers:
            raise HandoffError(
                "blocking reasons do not match handoff preconditions"
            )
        expected_approvable = not expected_blockers
        if self.approvable != expected_approvable:
            raise HandoffError(
                "approvable does not match handoff preconditions"
            )

        try:
            checklist = tuple(self.checklist)
        except TypeError as error:
            raise HandoffError("checklist must be a sequence") from error
        if checklist != HUMAN_REVIEW_CHECKLIST:
            raise HandoffError(
                "human review checklist must use the fixed order"
            )

        try:
            options = tuple(self.decision_options)
        except TypeError as error:
            raise HandoffError(
                "decision_options must be a sequence"
            ) from error
        if any(
            not isinstance(option, HandoffDecisionOption)
            for option in options
        ):
            raise HandoffError(
                "decision_options must contain HandoffDecisionOption values"
            )
        if {option.name for option in options} != set(HUMAN_DECISION_OPTIONS):
            raise HandoffError("every fixed human decision option is required")
        stable_options = tuple(
            sorted(options, key=lambda option: _DECISION_ORDER[option.name])
        )
        approve_option = stable_options[0]
        if approve_option.available != self.approvable:
            raise HandoffError(
                "approve_for_pr availability does not match approvable"
            )
        if any(not option.available for option in stable_options[1:]):
            raise HandoffError(
                "request_changes and reject must remain available"
            )

        object.__setattr__(self, "touched_files", touched_files)
        object.__setattr__(self, "blocking_reasons", blockers)
        object.__setattr__(self, "checklist", checklist)
        object.__setattr__(self, "decision_options", stable_options)

        if len(self.summary().encode("utf-8")) > MAX_HANDOFF_SUMMARY_BYTES:
            raise HandoffError(
                "handoff summary exceeds "
                f"{MAX_HANDOFF_SUMMARY_BYTES} bytes"
            )

    def to_dict(self) -> dict:
        """Return deterministic, bounded data for a human handoff only."""
        return {
            "approval": {
                "approvable": self.approvable,
                "blocking_reasons": list(self.blocking_reasons),
                "decision_options": [
                    option.to_dict() for option in self.decision_options
                ],
            },
            "authority": {
                "handoff_only": self.handoff_only,
                "runtime_authority": self.runtime_authority,
            },
            "bundle": {
                "readiness_status": self.bundle_readiness_status,
                "review_only": self.bundle_review_only,
                "runtime_authority": self.bundle_runtime_authority,
            },
            "checklist": list(self.checklist),
            "job": self.job.to_dict(),
            "preconditions": {
                "evidence_accepted": self.evidence_accepted,
                "evidence_present": self.evidence_present,
                "evidence_status": self.evidence_status,
                "intake_accepted": self.intake_accepted,
                "verification_plan_present": (
                    self.verification_plan_present
                ),
            },
            "schema_version": self.schema_version,
            "touched_files": list(self.touched_files),
        }

    def summary(self) -> str:
        """Return a stable JSON handoff containing no raw build artifacts."""
        return json.dumps(
            self.to_dict(),
            indent=2,
            sort_keys=True,
            ensure_ascii=False,
        ) + "\n"


def build_human_handoff(bundle: BuildReviewBundle) -> HumanHandoffPackage:
    """Convert one sanitized review bundle into an inert human handoff."""
    if not isinstance(bundle, BuildReviewBundle):
        raise HandoffError("bundle must be a BuildReviewBundle")

    plan_present = bundle.verification_plan is not None
    evidence_present = bundle.evidence is not None
    evidence_accepted = (
        None if bundle.evidence is None else bundle.evidence.accepted
    )
    evidence_status = (
        None if bundle.evidence is None else bundle.evidence.status
    )
    blockers = _approval_blockers(
        bundle_readiness_status=bundle.readiness_status,
        bundle_review_only=bundle.review_only,
        bundle_runtime_authority=bundle.runtime_authority,
        intake_accepted=bundle.intake.accepted,
        verification_plan_present=plan_present,
        evidence_present=evidence_present,
        evidence_accepted=evidence_accepted,
        evidence_status=evidence_status,
    )
    approvable = not blockers
    return HumanHandoffPackage(
        bundle_readiness_status=bundle.readiness_status,
        job=bundle.job,
        touched_files=bundle.intake.touched_files,
        bundle_review_only=bundle.review_only,
        bundle_runtime_authority=bundle.runtime_authority,
        intake_accepted=bundle.intake.accepted,
        verification_plan_present=plan_present,
        evidence_present=evidence_present,
        evidence_accepted=evidence_accepted,
        evidence_status=evidence_status,
        approvable=approvable,
        blocking_reasons=blockers,
        checklist=HUMAN_REVIEW_CHECKLIST,
        decision_options=_decision_options(approvable),
    )
