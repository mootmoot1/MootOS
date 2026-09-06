"""CB-028E — read-only query and conservative impact interface."""

from pathlib import Path

import pytest

from backend.continuous_builder.system_model import (
    AUTHORITY_FLAGS,
    SystemModelError,
    build_system_model,
    changed_components,
    component_for_path,
    dependencies_of,
    dependents_of,
    files_for_component,
    impacted_components,
    model_tcb_classification,
)


BASE = "d" * 64


def _write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _repo(tmp_path):
    root = tmp_path / "repo"
    _write(root / "backend" / "__init__.py", "")
    _write(root / "backend" / "continuous_builder" / "__init__.py", "")
    _write(
        root / "backend" / "continuous_builder" / "alpha.py",
        "import json\nimport backend.db\n",
    )
    _write(root / "backend" / "db.py", "import os\n")
    _write(
        root / "tests" / "test_alpha.py",
        "from backend.continuous_builder import alpha\n",
    )
    _write(root / "README.md", "# r\n")
    return root


def test_component_for_path_and_files(tmp_path):
    model = build_system_model(_repo(tmp_path), base_sha=BASE)
    assert component_for_path(
        model, "backend/continuous_builder/alpha.py"
    ) == "backend.continuous_builder"
    files = files_for_component(model, "backend.continuous_builder")
    assert "backend/continuous_builder/alpha.py" in files
    assert component_for_path(model, "missing/x.py") == "UNKNOWN"


def test_dependencies_and_dependents(tmp_path):
    model = build_system_model(_repo(tmp_path), base_sha=BASE)
    deps = dependencies_of(model, "backend.continuous_builder")
    assert any(edge["imported_name"] == "json" for edge in deps)
    assert any(
        edge["imported_name"] == "backend.db"
        and edge["target_component_id"] == "backend"
        for edge in deps
    )
    dependents = dependents_of(model, "backend")
    assert any(
        edge["source_component_id"] == "backend.continuous_builder"
        for edge in dependents
    )


def test_tcb_classification_via_model_evidence(tmp_path):
    root = _repo(tmp_path)
    _write(root / "backend" / "continuous_builder" / "verifier_core.py", "x\n")
    model = build_system_model(root, base_sha=BASE)
    hit = model_tcb_classification(
        model, "backend/continuous_builder/verifier_core.py"
    )
    assert hit["is_tcb"] is True
    miss = model_tcb_classification(model, "backend/db.py")
    assert miss["is_tcb"] is False


def test_changed_components(tmp_path):
    model = build_system_model(_repo(tmp_path), base_sha=BASE)
    changed = changed_components(
        model,
        (
            "backend/continuous_builder/alpha.py",
            "backend/db.py",
            "nope.py",
        ),
    )
    assert "backend.continuous_builder" in changed
    assert "backend" in changed
    assert "UNKNOWN" in changed


def test_impacted_components_conservative(tmp_path):
    model = build_system_model(_repo(tmp_path), base_sha=BASE)
    # Changing backend should impact dependents (continuous_builder).
    assessment = impacted_components(model, ("backend/db.py",))
    assert "backend" in assessment.changed_components
    assert "backend" in assessment.impacted_components
    assert "backend.continuous_builder" in assessment.impacted_components
    assert assessment.impact_state in ("impacted", "possible_impact")
    for name in AUTHORITY_FLAGS:
        assert getattr(assessment, name) is False


def test_impact_unknown_when_paths_unknown(tmp_path):
    model = build_system_model(_repo(tmp_path), base_sha=BASE)
    assessment = impacted_components(model, ("ghost/file.py",))
    assert assessment.impact_state in ("unknown", "possible_impact")
    assert "UNKNOWN" in assessment.changed_components
    assert assessment.impacted_components == tuple()


def test_impact_malformed_path_possible_or_unknown(tmp_path):
    model = build_system_model(_repo(tmp_path), base_sha=BASE)
    assessment = impacted_components(model, ("../escape.py",))
    assert assessment.impact_state == "unknown"
    assert assessment.uncertain_subjects


def test_query_path_bound(tmp_path):
    model = build_system_model(_repo(tmp_path), base_sha=BASE)
    with pytest.raises(SystemModelError, match="exceed bound"):
        changed_components(model, tuple(f"p{i}.py" for i in range(300)))


def test_no_codegen_queue_dispatch_approval_surface(tmp_path):
    model = build_system_model(_repo(tmp_path), base_sha=BASE)
    # Query API returns evidence only — no authorize_* helpers on model.
    assert not hasattr(model, "authorize_queue")
    assert not hasattr(model, "authorize_publication")
    assert not hasattr(model, "dispatch")
    assert not hasattr(model, "approve")
    for name in AUTHORITY_FLAGS:
        assert getattr(model, name) is False
