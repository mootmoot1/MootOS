"""Advisory review records for the manual capability-build pipeline (V0.3E).

Three distinct roles, matching this task's requirement and
``docs/CAPABILITY_ARCHITECTURE.md`` Sec7-8:

1. ``ROLE_CORRECTNESS`` -- correctness and test quality
2. ``ROLE_SECURITY``    -- security and permissions
3. ``ROLE_ARCHITECTURE`` -- architecture and duplication

An ``AdvisoryReview`` is inert data: a role, a reviewer identity, findings,
and a verdict. **Nothing about it can merge, approve installation, or
change a `CapabilityRecord`'s lifecycle state** -- see
``scripts/capability_pipeline/lifecycle.py``'s ``attach_review``, which
appends a review and returns the state completely unchanged. The verdict
values below are deliberately not named "approved"/"rejected" -- they are
observations for a human to read, not a decision.
"""

from dataclasses import dataclass
from typing import Any, Mapping


class AdvisoryReviewError(ValueError):
    """Raised when a review record is malformed."""


ROLE_CORRECTNESS = "correctness_and_test_quality"
ROLE_SECURITY = "security_and_permissions"
ROLE_ARCHITECTURE = "architecture_and_duplication"
VALID_ROLES = {ROLE_CORRECTNESS, ROLE_SECURITY, ROLE_ARCHITECTURE}

# Deliberately not "approved"/"rejected"/"merged" -- those words imply an
# authority this record does not have. "no_concerns" still means only
# "this reviewer found nothing to flag", not "this is approved".
VERDICT_NO_CONCERNS = "no_concerns"
VERDICT_CONCERNS_NOTED = "concerns_noted"
VERDICT_BLOCKING_CONCERN = "blocking_concern"
VALID_VERDICTS = {VERDICT_NO_CONCERNS, VERDICT_CONCERNS_NOTED, VERDICT_BLOCKING_CONCERN}


@dataclass(frozen=True)
class AdvisoryReview:
    """One advisory review from one distinct role.

    ``reviewer`` is a free-text identity (e.g. "Claude", "Grok",
    "ChatGPT", or a human name) -- this module does not care who performs
    a role, only that the three roles are distinct and their findings are
    recorded, per ADR-032 ("distinct roles", never "one voice reused
    three times").
    """

    role: str
    reviewer: str
    summary: str
    findings: tuple
    verdict: str

    def __post_init__(self) -> None:
        if self.role not in VALID_ROLES:
            raise AdvisoryReviewError(f"'role' must be one of {sorted(VALID_ROLES)} (got {self.role!r})")
        if not isinstance(self.reviewer, str) or not self.reviewer.strip():
            raise AdvisoryReviewError("'reviewer' must be a non-empty string")
        if not isinstance(self.summary, str) or not self.summary.strip():
            raise AdvisoryReviewError("'summary' must be a non-empty string")
        if not isinstance(self.findings, (tuple, list)):
            raise AdvisoryReviewError("'findings' must be a list/tuple of strings")
        findings = tuple(self.findings)
        if any(not isinstance(item, str) or not item.strip() for item in findings):
            raise AdvisoryReviewError("'findings' entries must be non-empty strings")
        object.__setattr__(self, "findings", findings)
        if self.verdict not in VALID_VERDICTS:
            raise AdvisoryReviewError(
                f"'verdict' must be one of {sorted(VALID_VERDICTS)} (got {self.verdict!r})"
            )

    def to_dict(self) -> dict:
        return {
            "role": self.role,
            "reviewer": self.reviewer,
            "summary": self.summary,
            "findings": list(self.findings),
            "verdict": self.verdict,
        }

    @staticmethod
    def from_dict(data: Mapping[str, Any]) -> "AdvisoryReview":
        if not isinstance(data, Mapping):
            raise AdvisoryReviewError("A review record must be a JSON/YAML object")
        unknown = set(data.keys()) - {"role", "reviewer", "summary", "findings", "verdict"}
        if unknown:
            raise AdvisoryReviewError(f"Unknown review field(s): {', '.join(sorted(unknown))}")
        try:
            return AdvisoryReview(
                role=data["role"],
                reviewer=data["reviewer"],
                summary=data["summary"],
                findings=tuple(data.get("findings", ())),
                verdict=data["verdict"],
            )
        except KeyError as error:
            raise AdvisoryReviewError(f"Missing required review field: {error}") from error
