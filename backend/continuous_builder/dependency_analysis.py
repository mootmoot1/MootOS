"""Deterministic dependency graph and eligibility analysis."""

import json
from dataclasses import dataclass

from .blueprint_parser import ParsedBlueprint
from .queue_proposal import CandidateSliceProposal, QueueProposalError

MAX_ANALYSIS_BYTES = 256 * 1024
MAX_RECEIPT_IDENTITY_BYTES = 256


class DependencyAnalysisError(QueueProposalError):
    """Raised when dependency facts cannot prove eligibility."""


@dataclass(frozen=True)
class DependencyReceipt:
    receipt_id: str
    slice_id: str
    slice_version: str
    passed: bool
    authoritative: bool

    def __post_init__(self):
        if any(
            not isinstance(value, str) or not value
            or len(value.encode("utf-8")) > MAX_RECEIPT_IDENTITY_BYTES
            for value in (
                self.receipt_id, self.slice_id, self.slice_version,
            )
        ):
            raise DependencyAnalysisError("receipt identity is malformed")
        if (
            type(self.passed) is not bool
            or type(self.authoritative) is not bool
        ):
            raise DependencyAnalysisError("receipt flags must be boolean")

    def to_dict(self):
        return {
            "authoritative": self.authoritative,
            "passed": self.passed,
            "receipt_id": self.receipt_id,
            "slice_id": self.slice_id,
            "slice_version": self.slice_version,
        }


@dataclass(frozen=True)
class SliceDependencyResult:
    slice_id: str
    eligible: bool
    blocked_reasons: tuple
    hard_dependency_receipts: tuple
    soft_dependencies_satisfied: tuple

    def to_dict(self):
        return {
            "blocked_reasons": list(self.blocked_reasons),
            "eligible": self.eligible,
            "hard_dependency_receipts": list(
                self.hard_dependency_receipts
            ),
            "slice_id": self.slice_id,
            "soft_dependencies_satisfied": list(
                self.soft_dependencies_satisfied
            ),
        }


def _check_graph(slices):
    by_id = {item.slice_id: item for item in slices}
    for item in slices:
        dependencies = item.hard_dependencies + item.soft_dependencies
        missing = set(dependencies) - set(by_id)
        if missing:
            raise DependencyAnalysisError(
                f"{item.slice_id} has missing dependencies: {sorted(missing)}"
            )
    visiting = set()
    visited = set()

    def visit(slice_id):
        if slice_id in visiting:
            raise DependencyAnalysisError("dependency graph contains a cycle")
        if slice_id in visited:
            return
        visiting.add(slice_id)
        item = by_id[slice_id]
        for dependency in item.hard_dependencies + item.soft_dependencies:
            visit(dependency)
        visiting.remove(slice_id)
        visited.add(slice_id)

    for slice_id in sorted(by_id):
        visit(slice_id)
    return by_id


def _derive(parsed, candidates, receipts):
    by_id = _check_graph(parsed.blueprint.slices)
    candidate_by_id = {item.slice_id: item for item in candidates}
    if set(candidate_by_id) != set(by_id) or len(candidate_by_id) != len(
        candidates
    ):
        raise DependencyAnalysisError(
            "candidates do not match blueprint slices"
        )
    for item in candidates:
        expected = by_id[item.slice_id]
        if item.blueprint_digest != parsed.content_sha256 or (
            item.slice_version != expected.version
        ):
            raise DependencyAnalysisError("candidate source binding mismatch")
    receipt_by_slice = {}
    for receipt in receipts:
        if not isinstance(receipt, DependencyReceipt):
            raise DependencyAnalysisError("dependency receipt is invalid")
        if receipt.slice_id in receipt_by_slice:
            raise DependencyAnalysisError("duplicate dependency receipt")
        receipt_by_slice[receipt.slice_id] = receipt
    results = []
    for slice_id in sorted(by_id):
        item = by_id[slice_id]
        reasons = []
        bound_receipts = []
        for dependency_id in item.hard_dependencies:
            dependency = by_id[dependency_id]
            receipt = receipt_by_slice.get(dependency_id)
            if receipt is None:
                reasons.append(f"missing_receipt:{dependency_id}")
            elif receipt.slice_version != dependency.version:
                reasons.append(f"version_mismatch:{dependency_id}")
            elif not receipt.authoritative:
                reasons.append(f"not_authoritative:{dependency_id}")
            elif not receipt.passed:
                reasons.append(f"dependency_failed:{dependency_id}")
            else:
                bound_receipts.append(receipt.receipt_id)
        soft = tuple(
            dependency_id for dependency_id in item.soft_dependencies
            if dependency_id in receipt_by_slice
            and receipt_by_slice[dependency_id].passed
            and receipt_by_slice[dependency_id].authoritative
            and receipt_by_slice[dependency_id].slice_version
            == by_id[dependency_id].version
        )
        results.append(SliceDependencyResult(
            slice_id=slice_id, eligible=not reasons,
            blocked_reasons=tuple(reasons),
            hard_dependency_receipts=tuple(bound_receipts),
            soft_dependencies_satisfied=soft,
        ))
    return tuple(results)


@dataclass(frozen=True)
class DependencyAnalysis:
    parsed_blueprint: ParsedBlueprint
    candidates: tuple
    receipts: tuple
    results: tuple
    dispatch_authorized: bool = False

    def __post_init__(self):
        if not isinstance(self.parsed_blueprint, ParsedBlueprint):
            raise DependencyAnalysisError("parsed blueprint is invalid")
        candidates = tuple(self.candidates)
        receipts = tuple(self.receipts)
        results = tuple(self.results)
        if any(not isinstance(item, CandidateSliceProposal)
               for item in candidates):
            raise DependencyAnalysisError("candidate is invalid")
        expected = _derive(self.parsed_blueprint, candidates, receipts)
        if results != expected:
            raise DependencyAnalysisError(
                "derived dependency result is forged"
            )
        if self.dispatch_authorized:
            raise DependencyAnalysisError("analysis cannot authorize dispatch")
        object.__setattr__(self, "candidates", candidates)
        object.__setattr__(self, "receipts", receipts)
        object.__setattr__(self, "results", results)

    def canonical_bytes(self):
        value = {
            "blueprint_digest": self.parsed_blueprint.content_sha256,
            "dispatch_authorized": False,
            "results": [item.to_dict() for item in self.results],
        }
        encoded = json.dumps(
            value, sort_keys=True, separators=(",", ":")
        ).encode(
            "utf-8"
        )
        if len(encoded) > MAX_ANALYSIS_BYTES:
            raise DependencyAnalysisError("dependency analysis exceeds bound")
        return encoded


def analyze_dependencies(parsed, candidates, receipts=()):
    candidates = tuple(candidates)
    receipts = tuple(receipts)
    return DependencyAnalysis(
        parsed, candidates, receipts, _derive(parsed, candidates, receipts)
    )
