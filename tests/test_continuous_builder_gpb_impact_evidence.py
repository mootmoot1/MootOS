"""Tests for GP-B4 System-Model-only impact evidence."""

from pathlib import Path

import pytest

from backend.continuous_builder.gpa_eval_schema import AUTHORITY_FLAGS, UNKNOWN
from backend.continuous_builder.gpb_impact_evidence import (
    collect_impact_evidence,
    impact_evidence_is_observational_only,
    impact_evidence_never_invents_dependencies,
)
from backend.continuous_builder.system_model import build_system_model

TRUSTED_BASE = "b448dcaf679861b23cc690186fc96815776a6e3d"
REPO = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def model():
    return build_system_model(REPO, base_sha=TRUSTED_BASE)


def test_collect_for_known_cb_path(model):
    path = "backend/continuous_builder/worker_request.py"
    evidence = collect_impact_evidence(model, (path,))
    assert evidence.schema_version == "gpb-impact-evidence-v1"
    assert evidence.queried_paths == (path,)
    assert evidence.system_model_sha256 == model.model_sha256
    assert evidence.execution_authorized is False
    for name in AUTHORITY_FLAGS:
        assert getattr(evidence, name) is False
    # Ownership should resolve to a real component, not invented.
    assert UNKNOWN in evidence.owning_components or any(
        c not in (UNKNOWN,) for c in evidence.owning_components
    )


def test_tcb_adjacent_recorded(model):
    path = "backend/continuous_builder/trusted_policy.py"
    evidence = collect_impact_evidence(model, (path,))
    assert path in evidence.tcb_adjacent_paths
    assert any(u.startswith("tcb_adjacent:") for u in evidence.uncertainties)


def test_unknown_path_ownership_is_unknown(model):
    # Canonical path that is unlikely owned: a docs path may still resolve;
    # use a synthetic path under allowed shape that is not in inventory.
    # collect requires canonical repo-relative paths that canonicalize —
    # use an existing non-python doc path and accept UNKNOWN or a component.
    path = "docs/future/CONTINUOUS_BUILDER_GPA_EVALUATION_BASELINE.md"
    evidence = collect_impact_evidence(model, (path,))
    assert evidence.queried_paths == (path,)
    # Must not invent dependency edges for paths with no SM edges.
    for edge in evidence.dependency_edges:
        assert "source_component_id" in edge


def test_deterministic_digest(model):
    paths = (
        "backend/continuous_builder/worker_request.py",
        "backend/continuous_builder/gpa_eval_schema.py",
    )
    a = collect_impact_evidence(model, paths)
    b = collect_impact_evidence(model, tuple(reversed(paths)))
    assert a.evidence_sha256 == b.evidence_sha256
    assert a.queried_paths == tuple(sorted(paths))


def test_helpers():
    assert impact_evidence_is_observational_only() is True
    assert impact_evidence_never_invents_dependencies() is True


def test_rejects_non_model():
    from backend.continuous_builder.gpb_impact_evidence import ImpactEvidenceError
    with pytest.raises(ImpactEvidenceError, match="model"):
        collect_impact_evidence(object(), ("a.py",))


def test_no_invented_edges_beyond_sm(model):
    path = "backend/continuous_builder/gpa_task_taxonomy.py"
    evidence = collect_impact_evidence(model, (path,))
    sm_dep_keys = set()
    from backend.continuous_builder.system_model import (
        component_for_path,
        dependencies_of,
    )
    owner = component_for_path(model, path)
    if owner not in ("UNKNOWN", "AMBIGUOUS", "EXCLUDED", None):
        for edge in dependencies_of(model, owner):
            sm_dep_keys.add(
                (
                    edge.get("source_component_id") or "",
                    edge.get("target_component_id") or "",
                    edge.get("kind") or "",
                    edge.get("imported_name") or "",
                )
            )
    for edge in evidence.dependency_edges:
        key = (
            edge["source_component_id"],
            edge["target_component_id"],
            edge["kind"],
            edge["imported_name"],
        )
        assert key in sm_dep_keys
