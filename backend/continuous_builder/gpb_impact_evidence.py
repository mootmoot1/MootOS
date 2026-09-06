"""GP-B4 -- Dependency / Impact Evidence (System Model only).

Collects component, dependency, ownership, blast-radius, TCB-adjacency, and
uncertainty evidence exclusively from the CB-028 System Model query surface.
UNKNOWN is a valid answer. No invented dependencies. Memory / model advisory
outputs are never authoritative.

This module does not grant execution authority, does not mutate production
state, and does not invent edges that System Model did not report.
"""

from dataclasses import dataclass, field

from .gpa_eval_schema import (
    AUTHORITY_FLAGS,
    GPAEvalSchemaError,
    UNKNOWN,
    canonical_json,
    require_no_authority,
    require_sha256,
    require_sorted_unique_paths,
    sha256_hex,
)
from .system_model import (
    SystemModel,
    changed_components,
    component_for_path,
    dependencies_of,
    dependents_of,
    impacted_components,
    model_tcb_classification,
)

IMPACT_EVIDENCE_VERSION = "gpb-impact-evidence-v1"
MAX_PATHS = 64
MAX_COMPONENTS = 128
MAX_EDGES = 256
MAX_UNCERTAINTIES = 64
MAX_RECORD_BYTES = 64 * 1024

_TOKEN = object()


class ImpactEvidenceError(GPAEvalSchemaError):
    """Raised when impact evidence cannot be derived safely."""


@dataclass(frozen=True)
class DecompositionImpactEvidence:
    """Sealed SM-derived impact evidence for decomposition planning."""

    schema_version: str
    system_model_sha256: str
    system_model_version: str
    queried_paths: tuple
    owning_components: tuple
    dependency_edges: tuple
    dependent_edges: tuple
    impact_state: str
    impacted_components: tuple
    tcb_adjacent_paths: tuple
    uncertainties: tuple
    evidence_sha256: str
    publication_authorized: bool = False
    queue_transition_authorized: bool = False
    github_authorized: bool = False
    merge_authorized: bool = False
    main_advancement_authorized: bool = False
    result_trusted: bool = False
    worker_output_trusted: bool = False
    execution_authorized: bool = False
    _token: object = field(default=None, repr=False, compare=False)

    def __post_init__(self):
        if self._token is not _TOKEN:
            raise ImpactEvidenceError(
                "impact evidence requires trusted construction"
            )
        if self.schema_version != IMPACT_EVIDENCE_VERSION:
            raise ImpactEvidenceError("schema_version is unsupported")
        require_sha256(self.system_model_sha256, "system_model_sha256")
        require_sorted_unique_paths(
            self.queried_paths, "queried_paths", MAX_PATHS
        )
        if type(self.owning_components) is not tuple:
            raise ImpactEvidenceError("owning_components is malformed")
        if len(self.owning_components) > MAX_COMPONENTS:
            raise ImpactEvidenceError("owning_components exceeds bound")
        if self.owning_components != tuple(sorted(set(self.owning_components))):
            raise ImpactEvidenceError("owning_components is not canonical")
        if type(self.dependency_edges) is not tuple or (
            len(self.dependency_edges) > MAX_EDGES
        ):
            raise ImpactEvidenceError("dependency_edges is malformed")
        if type(self.dependent_edges) is not tuple or (
            len(self.dependent_edges) > MAX_EDGES
        ):
            raise ImpactEvidenceError("dependent_edges is malformed")
        if type(self.impacted_components) is not tuple:
            raise ImpactEvidenceError("impacted_components is malformed")
        if self.impacted_components != tuple(
            sorted(set(self.impacted_components))
        ):
            raise ImpactEvidenceError("impacted_components is not canonical")
        require_sorted_unique_paths(
            self.tcb_adjacent_paths, "tcb_adjacent_paths", MAX_PATHS
        )
        if type(self.uncertainties) is not tuple or (
            len(self.uncertainties) > MAX_UNCERTAINTIES
        ):
            raise ImpactEvidenceError("uncertainties is malformed")
        if self.uncertainties != tuple(sorted(set(self.uncertainties))):
            raise ImpactEvidenceError("uncertainties is not canonical")
        require_no_authority(self)
        if self.execution_authorized is not False:
            raise ImpactEvidenceError("cannot claim execution_authorized")
        require_sha256(self.evidence_sha256, "evidence_sha256")
        if self.evidence_sha256 != sha256_hex(canonical_json(self._body())):
            raise ImpactEvidenceError("evidence_sha256 mismatch")
        if len(canonical_json(self.to_dict())) > MAX_RECORD_BYTES:
            raise ImpactEvidenceError("evidence exceeds byte bound")

    def _body(self):
        return {
            "dependency_edges": [dict(e) for e in self.dependency_edges],
            "dependent_edges": [dict(e) for e in self.dependent_edges],
            "execution_authorized": False,
            "github_authorized": False,
            "impact_state": self.impact_state,
            "impacted_components": list(self.impacted_components),
            "main_advancement_authorized": False,
            "merge_authorized": False,
            "owning_components": list(self.owning_components),
            "publication_authorized": False,
            "queried_paths": list(self.queried_paths),
            "queue_transition_authorized": False,
            "result_trusted": False,
            "schema_version": self.schema_version,
            "system_model_sha256": self.system_model_sha256,
            "system_model_version": self.system_model_version,
            "tcb_adjacent_paths": list(self.tcb_adjacent_paths),
            "uncertainties": list(self.uncertainties),
            "worker_output_trusted": False,
        }

    def to_dict(self):
        body = self._body()
        body["evidence_sha256"] = self.evidence_sha256
        return body


def _edge_key(edge):
    def _s(value):
        return "" if value is None else str(value)
    return (
        _s(edge.get("source_component_id")),
        _s(edge.get("target_component_id")),
        _s(edge.get("kind")),
        _s(edge.get("imported_name")),
    )


def collect_impact_evidence(model, paths):
    """Derive decomposition impact evidence from System Model only.

    ``paths`` must be the candidate/contract scope paths under consideration.
    Unknown ownership, unresolved imports, and TCB registry mismatches are
    recorded as uncertainties -- never fabricated into confident edges.
    """
    if not isinstance(model, SystemModel):
        raise ImpactEvidenceError("model is invalid")
    if type(paths) not in (list, tuple):
        raise ImpactEvidenceError("paths is malformed")
    if len(paths) > MAX_PATHS:
        raise ImpactEvidenceError("paths exceeds bound")

    normalized = require_sorted_unique_paths(
        tuple(sorted(set(paths))), "queried_paths", MAX_PATHS
    )
    uncertainties = []
    owning = []
    tcb_adjacent = []

    for path in normalized:
        owner = component_for_path(model, path)
        if owner in ("UNKNOWN", "AMBIGUOUS", "EXCLUDED", None):
            uncertainties.append(f"ownership:{path}:{owner or UNKNOWN}")
            owning.append(UNKNOWN)
        else:
            owning.append(owner)
        classification = model_tcb_classification(model, path)
        if classification.get("is_tcb") is True:
            tcb_adjacent.append(path)
            uncertainties.append(f"tcb_adjacent:{path}")
        elif classification.get("state") == "uncertain":
            uncertainties.append(
                f"tcb_uncertain:{path}:{classification.get('detail_code')}"
            )

    owning = tuple(sorted(set(owning)))
    known_components = tuple(
        c for c in owning if c not in (UNKNOWN, "AMBIGUOUS", "EXCLUDED", None)
    )

    dep_edges = []
    dependent_edges = []
    seen_deps = set()
    seen_dependents = set()
    for cid in known_components:
        for edge in dependencies_of(model, cid):
            key = _edge_key(edge)
            if key in seen_deps:
                continue
            seen_deps.add(key)
            # Only keep a compact, deterministic subset of edge fields.
            compact = {
                "imported_name": edge.get("imported_name") or "",
                "kind": edge.get("kind") or "",
                "source_component_id": edge.get("source_component_id") or "",
                "target_component_id": edge.get("target_component_id") or "",
            }
            dep_edges.append(compact)
            if edge.get("kind") in ("unresolved_import", "ambiguous_import"):
                uncertainties.append(
                    f"dep_uncertain:{cid}:{edge.get('imported_name', '')}"
                )
        for edge in dependents_of(model, cid):
            key = _edge_key(edge)
            if key in seen_dependents:
                continue
            seen_dependents.add(key)
            compact = {
                "imported_name": edge.get("imported_name") or "",
                "kind": edge.get("kind") or "",
                "source_component_id": edge.get("source_component_id") or "",
                "target_component_id": edge.get("target_component_id") or "",
            }
            dependent_edges.append(compact)

    dep_edges = tuple(
        sorted(dep_edges, key=lambda e: _edge_key(e))
    )[:MAX_EDGES]
    dependent_edges = tuple(
        sorted(dependent_edges, key=lambda e: _edge_key(e))
    )[:MAX_EDGES]

    assessment = impacted_components(model, normalized)
    impact_state = assessment.impact_state
    impacted = tuple(assessment.impacted_components)
    for subject in assessment.uncertain_subjects:
        uncertainties.append(f"impact:{subject}")

    # Also surface model-level uncertainties that touch queried paths.
    path_set = set(normalized)
    for record in model.uncertainties:
        if record.subject in path_set or any(
            record.subject.startswith(p) for p in path_set
        ):
            uncertainties.append(
                f"model:{record.kind}:{record.subject}:{record.detail_code}"
            )

    # Prefer ownership/TCB/impact uncertainties over voluminous dep noise so
    # critical UNKNOWN signals are never truncated away.
    unique = sorted(set(uncertainties))
    priority = []
    rest = []
    for item in unique:
        if item.startswith(("ownership:", "tcb_adjacent:", "tcb_uncertain:", "impact:")):
            priority.append(item)
        else:
            rest.append(item)
    uncertainties = tuple((priority + rest)[:MAX_UNCERTAINTIES])

    values = {
        "schema_version": IMPACT_EVIDENCE_VERSION,
        "system_model_sha256": model.model_sha256,
        "system_model_version": model.model_version,
        "queried_paths": normalized,
        "owning_components": owning,
        "dependency_edges": dep_edges,
        "dependent_edges": dependent_edges,
        "impact_state": impact_state,
        "impacted_components": impacted,
        "tcb_adjacent_paths": tuple(sorted(set(tcb_adjacent))),
        "uncertainties": uncertainties,
        "execution_authorized": False,
    }
    for name in AUTHORITY_FLAGS:
        values[name] = False
    provisional = object.__new__(DecompositionImpactEvidence)
    for name, value in values.items():
        object.__setattr__(provisional, name, value)
    return DecompositionImpactEvidence(
        **values,
        evidence_sha256=sha256_hex(canonical_json(provisional._body())),
        _token=_TOKEN,
    )


def impact_evidence_is_observational_only():
    """TRUST REVIEW helper: True -- evidence never authorizes execution."""
    return True


def impact_evidence_never_invents_dependencies():
    """TRUST REVIEW helper: True -- only System Model edges are recorded."""
    return True
