"""Deterministic, model-independent Continuous Builder priority policy."""

import json
import unicodedata
from dataclasses import dataclass

from .conflict_analysis import ConflictAnalysis, ConflictAnalysisError


class PriorityPolicyError(ConflictAnalysisError):
    """Raised when priority inputs or derived rankings are inconsistent."""


POLICY_VERSION = "adr-043-v1"
_PRIORITY = {"critical": 0, "high": 1, "normal": 2, "low": 3}


def normalize_slice_id(value):
    return unicodedata.normalize("NFKC", value).casefold()


@dataclass(frozen=True)
class PriorityEntry:
    slice_id: str
    eligible: bool
    priority_class: str
    dependency_unblocking_value: int
    eligibility_sequence: int
    normalized_slice_id: str
    rank: int

    @property
    def sort_key(self):
        return (
            _PRIORITY[self.priority_class],
            -self.dependency_unblocking_value,
            self.eligibility_sequence,
            self.normalized_slice_id,
        )

    def to_dict(self):
        return {
            "dependency_unblocking_value": self.dependency_unblocking_value,
            "eligibility_sequence": self.eligibility_sequence,
            "eligible": self.eligible,
            "normalized_slice_id": self.normalized_slice_id,
            "priority_class": self.priority_class,
            "rank": self.rank,
            "slice_id": self.slice_id,
        }


def _descendant_counts(slices):
    children = {item.slice_id: set() for item in slices}
    for item in slices:
        for dependency in item.hard_dependencies:
            children[dependency].add(item.slice_id)

    def descendants(slice_id):
        found = set()
        pending = list(children[slice_id])
        while pending:
            child = pending.pop()
            if child not in found:
                found.add(child)
                pending.extend(children[child])
        return len(found)

    return {slice_id: descendants(slice_id) for slice_id in children}


def _derive(analysis):
    blueprint = analysis.dependency_analysis.parsed_blueprint.blueprint
    by_id = {item.slice_id: item for item in blueprint.slices}
    candidate_by_id = {
        item.slice_id: item
        for item in analysis.dependency_analysis.candidates
    }
    conflict_by_id = {item.slice_id: item for item in analysis.results}
    descendants = _descendant_counts(blueprint.slices)
    provisional = []
    for slice_id in sorted(by_id):
        item = by_id[slice_id]
        eligible = conflict_by_id[slice_id].eligible
        provisional.append(PriorityEntry(
            slice_id=slice_id, eligible=eligible,
            priority_class=item.priority_class,
            dependency_unblocking_value=descendants[slice_id],
            eligibility_sequence=(
                candidate_by_id[slice_id]
                .readiness_input.durable_eligibility_sequence
            ),
            normalized_slice_id=normalize_slice_id(slice_id), rank=0,
        ))
    eligible_order = sorted(
        (item for item in provisional if item.eligible),
        key=lambda item: item.sort_key,
    )
    ranks = {item.slice_id: index + 1
             for index, item in enumerate(eligible_order)}
    return tuple(
        PriorityEntry(
            item.slice_id, item.eligible, item.priority_class,
            item.dependency_unblocking_value, item.eligibility_sequence,
            item.normalized_slice_id, ranks.get(item.slice_id, 0),
        )
        for item in sorted(provisional, key=lambda value: value.slice_id)
    )


@dataclass(frozen=True)
class PriorityAnalysis:
    conflict_analysis: ConflictAnalysis
    policy_version: str
    entries: tuple
    advisory_metadata: tuple = ()
    model_advice_applied: bool = False

    def __post_init__(self):
        if not isinstance(self.conflict_analysis, ConflictAnalysis):
            raise PriorityPolicyError("conflict analysis is invalid")
        if self.policy_version != POLICY_VERSION:
            raise PriorityPolicyError("unsupported priority policy version")
        entries = tuple(self.entries)
        if entries != _derive(self.conflict_analysis):
            raise PriorityPolicyError("derived priority ranking is forged")
        advisory = tuple(self.advisory_metadata)
        if len(advisory) > 16 or any(
            not isinstance(item, str) or len(item.encode("utf-8")) > 512
            for item in advisory
        ):
            raise PriorityPolicyError("advisory metadata is malformed")
        if self.model_advice_applied:
            raise PriorityPolicyError("model advice cannot alter priority")
        object.__setattr__(self, "entries", entries)
        object.__setattr__(self, "advisory_metadata", advisory)

    @property
    def ranked_slice_ids(self):
        return tuple(
            item.slice_id for item in sorted(
                (entry for entry in self.entries if entry.eligible),
                key=lambda entry: entry.rank,
            )
        )

    def canonical_bytes(self):
        value = {
            "advisory_metadata": list(self.advisory_metadata),
            "blueprint_digest": (
                self.conflict_analysis.dependency_analysis
                .parsed_blueprint.content_sha256
            ),
            "entries": [item.to_dict() for item in self.entries],
            "model_advice_applied": False,
            "policy_version": self.policy_version,
            "ranked_slice_ids": list(self.ranked_slice_ids),
        }
        return json.dumps(value, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )


def rank_eligible_slices(analysis, advisory_metadata=()):
    return PriorityAnalysis(
        analysis, POLICY_VERSION, _derive(analysis), tuple(advisory_metadata)
    )
