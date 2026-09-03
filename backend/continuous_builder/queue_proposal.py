"""Pure in-memory candidate and queue transition proposal models."""

import json
import re
from dataclasses import dataclass

from .blueprint import BlueprintError, ContinuousBuilderBlueprint
from .blueprint_parser import ParsedBlueprint


class QueueProposalError(BlueprintError):
    """Raised when inert queue proposal metadata is inconsistent."""


CANDIDATE_STATES = ("proposed", "blocked", "ready")
LIFECYCLE_INTENTS = ("evaluate", "hold_for_human")
TRANSITION_INTENTS = ("propose_ready", "propose_blocked", "no_change")
MAX_REASONS = 64
MAX_SERIALIZED_BYTES = 128 * 1024
MAX_METADATA_BYTES = 256
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _string_tuple(values, name, limit=MAX_REASONS):
    if isinstance(values, (str, bytes)):
        raise QueueProposalError(f"{name} must be a collection")
    values = tuple(values)
    if len(values) > limit or any(
        not isinstance(value, str) or not value.strip()
        or len(value.encode("utf-8")) > MAX_METADATA_BYTES
        for value in values
    ):
        raise QueueProposalError(f"{name} is malformed or excessive")
    if len(values) != len(set(values)):
        raise QueueProposalError(f"{name} must be unique")
    return values


@dataclass(frozen=True)
class ReadinessInput:
    dependency_receipt_ids: tuple = ()
    available_capabilities: tuple = ()
    available_authority_classes: tuple = ()
    resource_budget_available: bool = False
    conflict_free: bool = False
    durable_eligibility_sequence: int = 0

    def __post_init__(self):
        for name in (
            "dependency_receipt_ids", "available_capabilities",
            "available_authority_classes",
        ):
            object.__setattr__(
                self, name, _string_tuple(getattr(self, name), name)
            )
        if type(self.resource_budget_available) is not bool:
            raise QueueProposalError("resource budget flag must be boolean")
        if type(self.conflict_free) is not bool:
            raise QueueProposalError("conflict flag must be boolean")
        if type(self.durable_eligibility_sequence) is not int or not (
            0 <= self.durable_eligibility_sequence <= 2**63 - 1
        ):
            raise QueueProposalError("eligibility sequence is invalid")

    def to_dict(self):
        return {
            "available_authority_classes": list(
                self.available_authority_classes
            ),
            "available_capabilities": list(self.available_capabilities),
            "conflict_free": self.conflict_free,
            "dependency_receipt_ids": list(self.dependency_receipt_ids),
            "durable_eligibility_sequence": (
                self.durable_eligibility_sequence
            ),
            "resource_budget_available": self.resource_budget_available,
        }


@dataclass(frozen=True)
class CandidateSliceProposal:
    blueprint_digest: str
    slice_id: str
    slice_version: str
    lifecycle_intent: str
    declared_state: str
    readiness_input: ReadinessInput

    def __post_init__(self):
        if self.lifecycle_intent not in LIFECYCLE_INTENTS:
            raise QueueProposalError("unsupported lifecycle intent")
        if self.declared_state not in CANDIDATE_STATES:
            raise QueueProposalError("unsupported candidate state")
        if not isinstance(self.readiness_input, ReadinessInput):
            raise QueueProposalError("readiness input is invalid")
        for value, name in (
            (self.blueprint_digest, "blueprint digest"),
            (self.slice_id, "slice ID"),
            (self.slice_version, "slice version"),
        ):
            if (
                not isinstance(value, str) or not value
                or len(value.encode("utf-8")) > MAX_METADATA_BYTES
            ):
                raise QueueProposalError(f"{name} is invalid")
        if _SHA256.fullmatch(self.blueprint_digest) is None:
            raise QueueProposalError("blueprint digest is malformed")

    def to_dict(self):
        return {
            "blueprint_digest": self.blueprint_digest,
            "declared_state": self.declared_state,
            "lifecycle_intent": self.lifecycle_intent,
            "readiness_input": self.readiness_input.to_dict(),
            "slice_id": self.slice_id,
            "slice_version": self.slice_version,
        }


@dataclass(frozen=True)
class TransitionProposal:
    candidate: CandidateSliceProposal
    intent: str
    reason_codes: tuple
    queue_state_changed: bool = False
    persisted: bool = False

    def __post_init__(self):
        if not isinstance(self.candidate, CandidateSliceProposal):
            raise QueueProposalError("candidate is invalid")
        if self.intent not in TRANSITION_INTENTS:
            raise QueueProposalError("unsupported transition intent")
        object.__setattr__(
            self, "reason_codes", _string_tuple(self.reason_codes, "reasons")
        )
        if self.queue_state_changed or self.persisted:
            raise QueueProposalError("proposal cannot mutate or persist state")

    def to_dict(self):
        return {
            "candidate": self.candidate.to_dict(),
            "intent": self.intent,
            "persisted": False,
            "queue_state_changed": False,
            "reason_codes": list(self.reason_codes),
        }

    def canonical_bytes(self):
        encoded = json.dumps(
            self.to_dict(), sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        if len(encoded) > MAX_SERIALIZED_BYTES:
            raise QueueProposalError("transition proposal exceeds byte bound")
        return encoded


def propose_candidates(parsed, readiness_by_slice=None):
    """Create inert candidates without trusting declared readiness."""
    if not isinstance(parsed, ParsedBlueprint):
        raise QueueProposalError("authoritative parsed blueprint is required")
    blueprint = parsed.blueprint
    if not isinstance(blueprint, ContinuousBuilderBlueprint):
        raise QueueProposalError("parsed blueprint binding is invalid")
    readiness_by_slice = readiness_by_slice or {}
    known_slice_ids = {item.slice_id for item in blueprint.slices}
    if set(readiness_by_slice) - known_slice_ids:
        raise QueueProposalError("readiness references an unknown slice")
    candidates = []
    for item in blueprint.slices:
        readiness = readiness_by_slice.get(item.slice_id, ReadinessInput())
        if not isinstance(readiness, ReadinessInput):
            raise QueueProposalError("readiness value is invalid")
        candidates.append(CandidateSliceProposal(
            blueprint_digest=parsed.content_sha256,
            slice_id=item.slice_id,
            slice_version=item.version,
            lifecycle_intent="evaluate",
            declared_state="proposed",
            readiness_input=readiness,
        ))
    return tuple(candidates)
