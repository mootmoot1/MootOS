"""CB-029E — deterministic ADR/arch/docs/tests retrieval."""

from backend.continuous_builder.context_engine import (
    classify_test_relation,
    retrieve_architecture_evidence,
    retrieve_related_tests,
    seal_dependency_summary,
)
from backend.continuous_builder.system_model import build_system_model


BASE = "e" * 64


def _repo(tmp_path):
    root = tmp_path / "repo"
    (root / "backend" / "continuous_builder").mkdir(parents=True)
    (root / "backend" / "__init__.py").write_text("", encoding="utf-8")
    (root / "backend" / "continuous_builder" / "__init__.py").write_text(
        "", encoding="utf-8"
    )
    (root / "backend" / "continuous_builder" / "context_engine.py").write_text(
        "X=1\n", encoding="utf-8"
    )
    (root / "tests").mkdir()
    (root / "tests" / "test_context_engine.py").write_text(
        "def test_x():\n    assert True\n", encoding="utf-8"
    )
    (root / "tests" / "test_other.py").write_text(
        "def test_y():\n    assert True\n", encoding="utf-8"
    )
    (root / "docs" / "future" / "architecture").mkdir(parents=True)
    (root / "docs" / "future" / "architecture" / "SYSTEM_INTELLIGENCE.md").write_text(
        "# System Intelligence\ncontext engine\n", encoding="utf-8"
    )
    (root / "docs" / "future" / "adr").mkdir(parents=True)
    (root / "docs" / "future" / "adr" / "ADR001.md").write_text(
        "# ADR001\n", encoding="utf-8"
    )
    (root / "docs" / "README.md").write_text("misc\n", encoding="utf-8")
    return root


def test_architecture_docs_retrieved_with_digest(tmp_path):
    root = _repo(tmp_path)
    model = build_system_model(root, base_sha=BASE)
    evidence = retrieve_architecture_evidence(
        root,
        model,
        base_sha=BASE,
        seed_paths=["backend/continuous_builder/context_engine.py"],
    )
    paths = {item.path for item in evidence}
    assert "docs/future/architecture/SYSTEM_INTELLIGENCE.md" in paths
    assert "docs/future/adr/ADR001.md" in paths
    assert "docs/README.md" not in paths
    for item in evidence:
        assert item.available is True
        assert len(item.file_sha256) == 64
        assert item.end_line >= 1


def test_related_tests_classification(tmp_path):
    root = _repo(tmp_path)
    model = build_system_model(root, base_sha=BASE)
    seed = ("backend/continuous_builder/context_engine.py",)
    assert classify_test_relation(seed, "tests/test_context_engine.py") == (
        "required"
    )
    related = retrieve_related_tests(model, seed_paths=seed)
    by_path = {item["path"]: item for item in related}
    assert by_path["tests/test_context_engine.py"]["relation"] == "required"
    assert len(by_path["tests/test_context_engine.py"]["digest"]) == 64


def test_dependency_summary_from_model(tmp_path):
    root = _repo(tmp_path)
    (root / "backend" / "continuous_builder" / "other.py").write_text(
        "from backend.continuous_builder.context_engine import X\n",
        encoding="utf-8",
    )
    model = build_system_model(root, base_sha=BASE)
    summary = seal_dependency_summary(model, "backend.continuous_builder")
    assert summary.component_id == "backend.continuous_builder"
    assert isinstance(summary.dependencies, tuple)
    assert summary.summary_sha256
