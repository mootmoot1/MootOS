"""Bounded inert human decision input for MootOS V0.4C Slice 6."""

import json
import re
import unicodedata
from dataclasses import dataclass, field

from scripts.capability_build.handoff import HUMAN_DECISION_OPTIONS


class PRReviewDecisionError(ValueError):
    """Raised when supplied human decision metadata is malformed."""


SCHEMA_VERSION = 1
MAX_IDENTITY_BYTES = 128
MAX_RATIONALE_BYTES = 4096
MAX_DECISION_INPUT_SUMMARY_BYTES = 16 * 1024
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@-]*$")
_SHA = re.compile(r"^[0-9a-f]{7,64}$")
_SENSITIVE = re.compile(
    r"(?i)(?:sk-[A-Za-z0-9_-]{20,}|(?:api[_-]?key|password|secret)\s*[:=])"
)


def _text(value, name, limit, pattern=None):
    if not isinstance(value, str) or not value.strip():
        raise PRReviewDecisionError(f"{name} must be nonblank text")
    value = unicodedata.normalize("NFC", value.strip())
    if any(unicodedata.category(char) == "Cc" for char in value):
        raise PRReviewDecisionError(f"{name} contains control characters")
    if len(value.encode("utf-8")) > limit:
        raise PRReviewDecisionError(f"{name} exceeds {limit} bytes")
    if _SENSITIVE.search(value):
        raise PRReviewDecisionError(f"{name} contains secret-like material")
    if pattern is not None and pattern.fullmatch(value) is None:
        raise PRReviewDecisionError(f"{name} is malformed")
    return value


@dataclass(frozen=True)
class PRReviewDecisionInput:
    """What a human supplied, without validation or execution authority."""

    decision_id: str
    reviewer_id: str
    decision: str
    rationale: str
    job_id: str
    package_id: str
    proposal_base_sha: str
    schema_version: int = field(default=SCHEMA_VERSION, init=False)
    human_supplied_only: bool = field(default=True, init=False)
    decision_allowed: bool = field(default=False, init=False)
    reviewer_authorized: bool = field(default=False, init=False)
    source_authoritative: bool = field(default=False, init=False)
    publication_authorized: bool = field(default=False, init=False)
    git_action_performed: bool = field(default=False, init=False)
    github_action_performed: bool = field(default=False, init=False)
    runtime_authority: bool = field(default=False, init=False)

    def __post_init__(self):
        for name in ("decision_id", "reviewer_id", "job_id", "package_id"):
            object.__setattr__(
                self,
                name,
                _text(
                    getattr(self, name), name, MAX_IDENTITY_BYTES, _IDENTIFIER
                ),
            )
        if self.decision not in HUMAN_DECISION_OPTIONS:
            raise PRReviewDecisionError(
                f"unsupported human decision: {self.decision!r}"
            )
        object.__setattr__(
            self,
            "rationale",
            _text(self.rationale, "rationale", MAX_RATIONALE_BYTES),
        )
        object.__setattr__(
            self,
            "proposal_base_sha",
            _text(
                self.proposal_base_sha,
                "proposal_base_sha",
                MAX_IDENTITY_BYTES,
                _SHA,
            ),
        )
        if len(self.summary().encode("utf-8")) > (
            MAX_DECISION_INPUT_SUMMARY_BYTES
        ):
            raise PRReviewDecisionError("decision input summary exceeds bound")

    def to_dict(self):
        return {
            "authority": {
                "decision_allowed": self.decision_allowed,
                "github_action_performed": self.github_action_performed,
                "git_action_performed": self.git_action_performed,
                "human_supplied_only": self.human_supplied_only,
                "publication_authorized": self.publication_authorized,
                "reviewer_authorized": self.reviewer_authorized,
                "runtime_authority": self.runtime_authority,
                "source_authoritative": self.source_authoritative,
            },
            "decision": self.decision,
            "decision_id": self.decision_id,
            "job_id": self.job_id,
            "package_id": self.package_id,
            "proposal_base_sha": self.proposal_base_sha,
            "rationale": self.rationale,
            "reviewer_id": self.reviewer_id,
            "schema_version": self.schema_version,
        }

    def summary(self):
        return json.dumps(
            self.to_dict(), indent=2, sort_keys=True, ensure_ascii=False
        ) + "\n"
