"""Immutable advisory Chief Builder planning receipts."""

import hashlib
import json
from dataclasses import dataclass

from .priority_policy import PriorityAnalysis, PriorityPolicyError


class ChiefBuilderError(PriorityPolicyError):
    """Raised when a planning receipt cannot be proven from its sources."""


MAX_RECEIPT_BYTES = 256 * 1024


@dataclass(frozen=True)
class BlueprintApprovalEvidence:
    approval_id: str
    blueprint_digest: str
    supplied_approver_identity: str
    approved: bool
    approver_authenticated: bool = False

    def __post_init__(self):
        for value, name in (
            (self.approval_id, "approval ID"),
            (self.blueprint_digest, "blueprint digest"),
            (self.supplied_approver_identity, "approver identity"),
        ):
            if (
                not isinstance(value, str) or not value.strip()
                or len(value.encode("utf-8")) > 256
            ):
                raise ChiefBuilderError(f"{name} is malformed")
        if self.approved is not True:
            raise ChiefBuilderError("explicit blueprint approval is required")
        if self.approver_authenticated:
            raise ChiefBuilderError(
                "external approver authentication is absent"
            )

    def to_dict(self):
        return {
            "approval_id": self.approval_id,
            "approved": True,
            "approver_authenticated": False,
            "blueprint_digest": self.blueprint_digest,
            "supplied_approver_identity": self.supplied_approver_identity,
        }


@dataclass(frozen=True)
class PlannedSlice:
    slice_id: str
    eligible: bool
    blocked_reasons: tuple
    dependency_receipt_ids: tuple
    conflicting_slice_ids: tuple
    rank: int
    authority_requirements: tuple
    human_stops: tuple

    def to_dict(self):
        return {
            "authority_requirements": list(self.authority_requirements),
            "blocked_reasons": list(self.blocked_reasons),
            "conflicting_slice_ids": list(self.conflicting_slice_ids),
            "dependency_receipt_ids": list(self.dependency_receipt_ids),
            "eligible": self.eligible,
            "human_stops": list(self.human_stops),
            "rank": self.rank,
            "slice_id": self.slice_id,
        }


def _derive(priority):
    conflicts = priority.conflict_analysis
    dependencies = conflicts.dependency_analysis
    blueprint = dependencies.parsed_blueprint.blueprint
    dependency_by_id = {item.slice_id: item for item in dependencies.results}
    conflict_by_id = {item.slice_id: item for item in conflicts.results}
    priority_by_id = {item.slice_id: item for item in priority.entries}
    results = []
    for item in sorted(blueprint.slices, key=lambda value: value.slice_id):
        dependency = dependency_by_id[item.slice_id]
        conflict = conflict_by_id[item.slice_id]
        rank = priority_by_id[item.slice_id]
        results.append(PlannedSlice(
            slice_id=item.slice_id, eligible=conflict.eligible,
            blocked_reasons=conflict.blocked_reasons,
            dependency_receipt_ids=dependency.hard_dependency_receipts,
            conflicting_slice_ids=conflict.conflicting_slice_ids,
            rank=rank.rank,
            authority_requirements=item.authority_classes,
            human_stops=item.human_checkpoints,
        ))
    return tuple(results)


@dataclass(frozen=True)
class ChiefBuilderPlanningReceipt:
    approval: BlueprintApprovalEvidence
    priority_analysis: PriorityAnalysis
    planned_slices: tuple
    recommended_slice_ids: tuple
    receipt_sha256: str
    advisory_only: bool = True
    queue_state_changed: bool = False
    dispatch_authorized: bool = False
    worker_dispatched: bool = False

    def __post_init__(self):
        if not isinstance(self.approval, BlueprintApprovalEvidence):
            raise ChiefBuilderError("approval evidence is invalid")
        if not isinstance(self.priority_analysis, PriorityAnalysis):
            raise ChiefBuilderError("priority analysis is invalid")
        parsed = (
            self.priority_analysis.conflict_analysis.dependency_analysis
            .parsed_blueprint
        )
        if self.approval.blueprint_digest != parsed.content_sha256:
            raise ChiefBuilderError("approval does not bind blueprint")
        planned = tuple(self.planned_slices)
        expected = _derive(self.priority_analysis)
        if planned != expected:
            raise ChiefBuilderError("derived planning result is forged")
        recommendations = tuple(
            item.slice_id for item in sorted(
                (value for value in expected if value.eligible),
                key=lambda value: value.rank,
            )[:1]
        )
        if tuple(self.recommended_slice_ids) != recommendations:
            raise ChiefBuilderError("recommendation is forged")
        if not self.advisory_only or self.queue_state_changed or (
            self.dispatch_authorized or self.worker_dispatched
        ):
            raise ChiefBuilderError(
                "planning receipt claims runtime authority"
            )
        object.__setattr__(self, "planned_slices", planned)
        object.__setattr__(self, "recommended_slice_ids", recommendations)
        expected_digest = hashlib.sha256(self._payload()).hexdigest()
        if self.receipt_sha256 != expected_digest:
            raise ChiefBuilderError("planning receipt digest is forged")
        if len(self.canonical_bytes()) > MAX_RECEIPT_BYTES:
            raise ChiefBuilderError("planning receipt exceeds byte bound")

    def _body(self):
        parsed = (
            self.priority_analysis.conflict_analysis.dependency_analysis
            .parsed_blueprint
        )
        return {
            "advisory_only": True,
            "approval": self.approval.to_dict(),
            "blueprint_id": parsed.blueprint.blueprint_id,
            "blueprint_version": parsed.blueprint.blueprint_version,
            "dispatch_authorized": False,
            "planned_slices": [item.to_dict() for item in self.planned_slices],
            "policy_version": self.priority_analysis.policy_version,
            "queue_state_changed": False,
            "recommended_slice_ids": list(self.recommended_slice_ids),
            "worker_dispatched": False,
        }

    def _payload(self):
        return json.dumps(
            self._body(), ensure_ascii=False, sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")

    def canonical_bytes(self):
        value = self._body()
        value["receipt_sha256"] = self.receipt_sha256
        return json.dumps(
            value, ensure_ascii=False, sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")


def create_planning_receipt(priority_analysis, approval):
    if not isinstance(priority_analysis, PriorityAnalysis):
        raise ChiefBuilderError("priority analysis is invalid")
    planned = _derive(priority_analysis)
    recommendations = tuple(
        item.slice_id for item in sorted(
            (value for value in planned if value.eligible),
            key=lambda value: value.rank,
        )[:1]
    )
    provisional = object.__new__(ChiefBuilderPlanningReceipt)
    object.__setattr__(provisional, "approval", approval)
    object.__setattr__(provisional, "priority_analysis", priority_analysis)
    object.__setattr__(provisional, "planned_slices", planned)
    object.__setattr__(provisional, "recommended_slice_ids", recommendations)
    object.__setattr__(provisional, "advisory_only", True)
    object.__setattr__(provisional, "queue_state_changed", False)
    object.__setattr__(provisional, "dispatch_authorized", False)
    object.__setattr__(provisional, "worker_dispatched", False)
    digest = hashlib.sha256(provisional._payload()).hexdigest()
    return ChiefBuilderPlanningReceipt(
        approval, priority_analysis, planned, recommendations, digest
    )
