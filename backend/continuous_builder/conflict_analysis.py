"""Pure scope, authority, capability, and budget eligibility analysis."""

import fnmatch
import json
from dataclasses import dataclass

from .dependency_analysis import DependencyAnalysis, DependencyAnalysisError


class ConflictAnalysisError(DependencyAnalysisError):
    """Raised when conflict/authority eligibility input is inconsistent."""


def _values(values, name):
    if isinstance(values, (str, bytes)):
        raise ConflictAnalysisError(f"{name} must be a collection")
    values = tuple(values)
    if len(values) > 128 or any(
        not isinstance(value, str) or not value for value in values
    ):
        raise ConflictAnalysisError(f"{name} is malformed or excessive")
    if len(values) != len(set(values)):
        raise ConflictAnalysisError(f"{name} must be unique")
    return values


@dataclass(frozen=True)
class EligibilityResources:
    available_capabilities: tuple
    available_authority_classes: tuple
    active_slice_scopes: tuple = ()
    resource_available: bool = True
    budget_available: bool = True

    def __post_init__(self):
        object.__setattr__(self, "available_capabilities", _values(
            self.available_capabilities, "available capabilities"
        ))
        object.__setattr__(self, "available_authority_classes", _values(
            self.available_authority_classes, "available authority classes"
        ))
        scopes = tuple(self.active_slice_scopes)
        normalized = []
        for item in scopes:
            if (
                not isinstance(item, tuple) or len(item) != 2
                or not isinstance(item[0], str)
            ):
                raise ConflictAnalysisError("active scope is malformed")
            normalized.append((item[0], _values(item[1], "active paths")))
        if type(self.resource_available) is not bool or type(
            self.budget_available
        ) is not bool:
            raise ConflictAnalysisError("resource flags must be boolean")
        object.__setattr__(self, "active_slice_scopes", tuple(normalized))

    def to_dict(self):
        return {
            "active_slice_scopes": [
                {"paths": list(paths), "slice_id": slice_id}
                for slice_id, paths in self.active_slice_scopes
            ],
            "available_authority_classes": list(
                self.available_authority_classes
            ),
            "available_capabilities": list(self.available_capabilities),
            "budget_available": self.budget_available,
            "resource_available": self.resource_available,
        }


@dataclass(frozen=True)
class SliceConflictResult:
    slice_id: str
    eligible: bool
    blocked_reasons: tuple
    conflicting_slice_ids: tuple

    def to_dict(self):
        return {
            "blocked_reasons": list(self.blocked_reasons),
            "conflicting_slice_ids": list(self.conflicting_slice_ids),
            "eligible": self.eligible,
            "slice_id": self.slice_id,
        }


def _paths_overlap(left, right):
    left_base = left.rstrip("*").rstrip("/")
    right_base = right.rstrip("*").rstrip("/")
    return (
        fnmatch.fnmatch(left, right) or fnmatch.fnmatch(right, left)
        or left_base == right_base
        or left_base.startswith(right_base + "/")
        or right_base.startswith(left_base + "/")
    )


def _derive(dependencies, resources):
    blueprint = dependencies.parsed_blueprint.blueprint
    dependency_by_id = {item.slice_id: item for item in dependencies.results}
    results = []
    for item in sorted(blueprint.slices, key=lambda value: value.slice_id):
        reasons = list(dependency_by_id[item.slice_id].blocked_reasons)
        missing_capabilities = sorted(
            set(item.requested_capabilities)
            - set(resources.available_capabilities)
        )
        missing_authority = sorted(
            set(item.authority_classes)
            - set(resources.available_authority_classes)
        )
        reasons.extend(
            f"capability_unavailable:{value}" for value in missing_capabilities
        )
        reasons.extend(
            f"authority_unavailable:{value}" for value in missing_authority
        )
        if not resources.resource_available:
            reasons.append("resource_unavailable")
        if not resources.budget_available:
            reasons.append("budget_unavailable")
        if any(
            _paths_overlap(allowed, forbidden)
            for allowed in item.allowed_paths
            for forbidden in item.forbidden_paths
        ):
            reasons.append("self_scope_conflict")
        conflicts = tuple(sorted(
            slice_id for slice_id, paths in resources.active_slice_scopes
            if slice_id != item.slice_id and any(
                _paths_overlap(allowed, active)
                for allowed in item.allowed_paths for active in paths
            )
        ))
        reasons.extend(f"active_scope_conflict:{value}" for value in conflicts)
        results.append(SliceConflictResult(
            item.slice_id, not reasons, tuple(reasons), conflicts
        ))
    return tuple(results)


@dataclass(frozen=True)
class ConflictAnalysis:
    dependency_analysis: DependencyAnalysis
    resources: EligibilityResources
    results: tuple
    lease_created: bool = False
    worker_dispatched: bool = False

    def __post_init__(self):
        if not isinstance(self.dependency_analysis, DependencyAnalysis):
            raise ConflictAnalysisError("dependency analysis is invalid")
        if not isinstance(self.resources, EligibilityResources):
            raise ConflictAnalysisError("eligibility resources are invalid")
        results = tuple(self.results)
        if results != _derive(self.dependency_analysis, self.resources):
            raise ConflictAnalysisError("derived conflict result is forged")
        if self.lease_created or self.worker_dispatched:
            raise ConflictAnalysisError("analysis cannot lease or dispatch")
        object.__setattr__(self, "results", results)

    def canonical_bytes(self):
        value = {
            "blueprint_digest": (
                self.dependency_analysis.parsed_blueprint.content_sha256
            ),
            "lease_created": False,
            "resources": self.resources.to_dict(),
            "results": [item.to_dict() for item in self.results],
            "worker_dispatched": False,
        }
        return json.dumps(value, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )


def analyze_conflicts(dependency_analysis, resources):
    return ConflictAnalysis(
        dependency_analysis, resources,
        _derive(dependency_analysis, resources),
    )
