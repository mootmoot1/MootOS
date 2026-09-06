"""CB-029F — package assembly, budgets, receipts, completeness."""

from backend.continuous_builder.context_engine import (
    AUTHORITY_FLAGS,
    HARD_MAX_PACKAGE_BUDGET_BYTES,
    assemble_context_package,
    seal_context_budget,
    seal_context_task_request,
)
from backend.continuous_builder.system_model import build_system_model


BASE = "f" * 64


def _repo(tmp_path):
    root = tmp_path / "repo"
    (root / "backend" / "continuous_builder").mkdir(parents=True)
    (root / "backend" / "__init__.py").write_text("", encoding="utf-8")
    (root / "backend" / "continuous_builder" / "__init__.py").write_text(
        "", encoding="utf-8"
    )
    (root / "backend" / "continuous_builder" / "target.py").write_text(
        "VALUE = 1\n\ndef run(x):\n    return x\n",
        encoding="utf-8",
    )
    (root / "backend" / "continuous_builder" / "neighbor.py").write_text(
        "from backend.continuous_builder.target import VALUE\n",
        encoding="utf-8",
    )
    (root / "tests").mkdir()
    (root / "tests" / "test_target.py").write_text(
        "def test_run():\n    assert True\n", encoding="utf-8"
    )
    (root / "docs" / "future" / "architecture").mkdir(parents=True)
    (root / "docs" / "future" / "architecture" / "SYSTEM.md").write_text(
        "# System\n", encoding="utf-8"
    )
    return root


def test_assemble_package_and_receipt(tmp_path):
    root = _repo(tmp_path)
    model = build_system_model(root, base_sha=BASE)
    req = seal_context_task_request(
        task_id="pkg-1",
        base_sha=BASE,
        objective="assemble package",
        acceptance=("unit tests pass",),
        allowed_paths=["backend/continuous_builder/target.py"],
        seed_paths=["backend/continuous_builder/target.py"],
        components=["backend.continuous_builder"],
        non_goals=("no merge",),
    )
    package, receipt = assemble_context_package(root, req, model)
    assert package.request_sha256 == req.request_sha256
    assert package.model_sha256 == model.model_sha256
    assert package.base_sha == BASE
    assert package.completeness in (
        "sufficient",
        "sufficient_with_uncertainty",
        "incomplete",
        "restricted",
        "unknown",
    )
    assert receipt.package_sha256 == package.package_sha256
    assert receipt.excerpt_count == len(package.excerpts)
    assert package.bytes_used <= req.budget.package_budget_bytes
    assert package.bytes_used <= HARD_MAX_PACKAGE_BUDGET_BYTES
    assert package.token_estimate >= 0
    paths = {ex.path for ex in package.excerpts if ex.available}
    assert "backend/continuous_builder/target.py" in paths
    for name in AUTHORITY_FLAGS:
        assert getattr(package, name) is False
        assert getattr(receipt, name) is False


def test_tight_budget_marks_incomplete_not_silent_drop(tmp_path):
    root = _repo(tmp_path)
    model = build_system_model(root, base_sha=BASE)
    req = seal_context_task_request(
        task_id="pkg-2",
        base_sha=BASE,
        objective="tiny budget",
        acceptance=("a",),
        allowed_paths=["backend/continuous_builder/target.py"],
        seed_paths=["backend/continuous_builder/target.py"],
        budget=seal_context_budget(
            package_budget_bytes=2048,
            excerpt_budget_bytes=512,
            max_excerpts=8,
            dep_depth=0,
        ),
    )
    package, receipt = assemble_context_package(root, req, model)
    assert package.bytes_used <= 2048
    # Either fits or incomplete/needs_review — never claims sufficient if critical missing
    if package.completeness == "incomplete":
        assert package.needs_review is True
        assert any(
            u.kind == "critical_missing" for u in package.uncertainties
        ) or "critical_missing" in receipt.flags
    assert package.completeness != "sufficient" or package.excerpts


def test_package_deterministic(tmp_path):
    root = _repo(tmp_path)
    model = build_system_model(root, base_sha=BASE)
    req = seal_context_task_request(
        task_id="pkg-3",
        base_sha=BASE,
        objective="determinism",
        seed_paths=["backend/continuous_builder/target.py"],
        allowed_paths=["backend/continuous_builder/target.py"],
    )
    a, ra = assemble_context_package(root, req, model)
    b, rb = assemble_context_package(root, req, model)
    assert a.package_sha256 == b.package_sha256
    assert ra.receipt_sha256 == rb.receipt_sha256
