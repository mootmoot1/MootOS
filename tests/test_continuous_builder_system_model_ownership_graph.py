"""CB-028C — conservative component ownership and static dependency graph."""

from pathlib import Path

import pytest

from backend.continuous_builder.system_model import (
    build_system_model,
    component_for_path,
    dependencies_of,
    dependents_of,
    files_for_component,
)


BASE = "b" * 64


def _write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _repo(tmp_path):
    root = tmp_path / "repo"
    _write(root / "backend" / "__init__.py", "")
    _write(
        root / "backend" / "continuous_builder" / "__init__.py",
        "",
    )
    _write(
        root / "backend" / "continuous_builder" / "alpha.py",
        "import json\nimport backend.db\n",
    )
    _write(
        root / "backend" / "db.py",
        "import os\n",
    )
    _write(
        root / "tests" / "test_alpha.py",
        "from backend.continuous_builder import alpha\n",
    )
    _write(root / "scripts" / "run.py", "import sys\n")
    _write(root / "README.md", "# r\n")
    return root


def test_package_path_components_deterministic(tmp_path):
    model = build_system_model(_repo(tmp_path), base_sha=BASE)
    ids = [item.component_id for item in model.components]
    assert ids == sorted(set(ids))
    assert "backend.continuous_builder" in ids
    assert "backend" in ids
    assert "tests" in ids
    assert "scripts" in ids
    assert component_for_path(
        model, "backend/continuous_builder/alpha.py"
    ) == "backend.continuous_builder"
    assert component_for_path(model, "backend/db.py") == "backend"
    assert component_for_path(model, "tests/test_alpha.py") == "tests"


def test_files_for_component_sorted(tmp_path):
    model = build_system_model(_repo(tmp_path), base_sha=BASE)
    files = files_for_component(model, "backend.continuous_builder")
    assert files == tuple(sorted(files))
    assert "backend/continuous_builder/alpha.py" in files


def test_static_imports_internal_external_unresolved(tmp_path):
    model = build_system_model(_repo(tmp_path), base_sha=BASE)
    edges = dependencies_of(model, "backend.continuous_builder")
    kinds = {edge["kind"] for edge in edges}
    imported = {edge["imported_name"]: edge for edge in edges}
    assert "json" in imported
    assert imported["json"]["kind"] == "external_import"
    assert imported["json"]["target_component_id"] is None
    # backend.db should resolve to backend component
    assert "backend.db" in imported
    assert imported["backend.db"]["kind"] == "internal_import"
    assert imported["backend.db"]["target_component_id"] == "backend"
    # Never invent certainty for relative-only weirdness elsewhere
    assert "ambiguous_import" in kinds or "external_import" in kinds


def test_dependents_of_internal_edge(tmp_path):
    model = build_system_model(_repo(tmp_path), base_sha=BASE)
    deps = dependents_of(model, "backend.continuous_builder")
    # tests import backend.continuous_builder as an internal edge
    assert any(
        edge["source_component_id"] == "tests"
        and edge["kind"] == "internal_import"
        and edge["target_component_id"] == "backend.continuous_builder"
        for edge in deps
    )
    # Also prove the reverse query from the importer side.
    from_tests = dependencies_of(model, "tests")
    assert any(
        edge["imported_name"] == "backend.continuous_builder"
        and edge["kind"] == "internal_import"
        for edge in from_tests
    )


def test_relative_import_stays_unresolved_or_ambiguous(tmp_path):
    root = tmp_path / "repo"
    _write(root / "backend" / "continuous_builder" / "__init__.py", "")
    _write(
        root / "backend" / "continuous_builder" / "rel.py",
        "from . import alpha\nfrom .alpha import x\n",
    )
    model = build_system_model(root, base_sha=BASE)
    edges = dependencies_of(model, "backend.continuous_builder")
    rel_edges = [
        edge for edge in edges
        if edge["imported_name"].startswith(".")
    ]
    assert rel_edges
    assert all(
        edge["kind"] in ("unresolved_import", "ambiguous_import")
        and edge["target_component_id"] is None
        for edge in rel_edges
    )
    assert any(
        item.kind in ("unresolved_import", "ambiguous_import")
        for item in model.uncertainties
    )


def test_ownership_records_cover_inventory_files(tmp_path):
    model = build_system_model(_repo(tmp_path), base_sha=BASE)
    owned_paths = {item.path for item in model.ownership}
    inv_paths = {item.path for item in model.inventory.files}
    assert inv_paths <= owned_paths
    for item in model.ownership:
        if item.state == "owned":
            assert item.component_id is not None
        if item.state in ("unowned", "excluded", "unknown", "ambiguous"):
            assert item.component_id is None


def test_unknown_path_query_not_invented(tmp_path):
    model = build_system_model(_repo(tmp_path), base_sha=BASE)
    assert component_for_path(model, "no/such/file.py") == "UNKNOWN"


def test_graph_small_and_inspectable(tmp_path):
    model = build_system_model(_repo(tmp_path), base_sha=BASE)
    assert len(model.dependency_edges) < 100
    for edge in model.dependency_edges:
        assert edge.kind in (
            "internal_import",
            "external_import",
            "unresolved_import",
            "ambiguous_import",
        )
        body = edge.to_dict()
        assert "edge_sha256" in body
