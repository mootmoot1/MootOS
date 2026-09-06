"""CB-029C — deterministic System Model planner."""

from pathlib import Path

from backend.continuous_builder.context_engine import (
    AUTHORITY_FLAGS,
    plan_context_selection,
    seal_context_budget,
    seal_context_task_request,
    selection_grants_edit_permission,
)
from backend.continuous_builder.system_model import build_system_model


BASE = "c" * 64


def _repo(tmp_path):
    root = tmp_path / "repo"
    (root / "backend" / "continuous_builder").mkdir(parents=True)
    (root / "backend" / "__init__.py").write_text("# pkg\n", encoding="utf-8")
    (root / "backend" / "continuous_builder" / "__init__.py").write_text(
        "# cb\n", encoding="utf-8"
    )
    (root / "backend" / "continuous_builder" / "alpha.py").write_text(
        "from backend.continuous_builder import beta\nX = 1\n",
        encoding="utf-8",
    )
    (root / "backend" / "continuous_builder" / "beta.py").write_text(
        "Y = 2\n",
        encoding="utf-8",
    )
    (root / "tests").mkdir()
    (root / "tests" / "test_alpha.py").write_text(
        "def test_a():\n    assert True\n",
        encoding="utf-8",
    )
    (root / "docs" / "future" / "architecture").mkdir(parents=True)
    (root / "docs" / "future" / "architecture" / "SYSTEM.md").write_text(
        "# arch\n",
        encoding="utf-8",
    )
    # Install minimal TCB stubs so model builds (registry expects real paths
    # only as flags — missing protected yields uncertainties, OK).
    return root


def test_plan_tags_seed_required_and_neighborhood(tmp_path):
    root = _repo(tmp_path)
    model = build_system_model(root, base_sha=BASE)
    req = seal_context_task_request(
        task_id="plan-1",
        base_sha=BASE,
        objective="plan neighborhood",
        allowed_paths=["backend/continuous_builder/alpha.py"],
        seed_paths=["backend/continuous_builder/alpha.py"],
        components=["backend.continuous_builder"],
        budget=seal_context_budget(dep_depth=1, max_excerpts=64),
    )
    plan = plan_context_selection(req, model)
    assert plan.request_sha256 == req.request_sha256
    assert plan.model_sha256 == model.model_sha256
    by_path = {item.path: item for item in plan.items if item.path}
    assert by_path["backend/continuous_builder/alpha.py"].selection_tag == (
        "REQUIRED"
    )
    assert by_path["backend/continuous_builder/alpha.py"].editable is True
    # Neighbor beta visible as SUPPORTING/POSSIBLE but NOT editable
    if "backend/continuous_builder/beta.py" in by_path:
        beta = by_path["backend/continuous_builder/beta.py"]
        assert beta.selection_tag in ("SUPPORTING", "POSSIBLE", "REQUIRED")
        assert beta.editable is False
    for name in AUTHORITY_FLAGS:
        assert getattr(plan, name) is False


def test_visibility_is_not_edit_permission(tmp_path):
    root = _repo(tmp_path)
    model = build_system_model(root, base_sha=BASE)
    req = seal_context_task_request(
        task_id="plan-2",
        base_sha=BASE,
        objective="visibility check",
        allowed_paths=["backend/continuous_builder/alpha.py"],
        seed_paths=["backend/continuous_builder/alpha.py"],
    )
    plan = plan_context_selection(req, model)
    assert selection_grants_edit_permission(
        plan, "backend/continuous_builder/alpha.py"
    ) is False
    assert selection_grants_edit_permission(
        plan, "backend/continuous_builder/beta.py"
    ) is False


def test_forbidden_and_secret_omitted(tmp_path):
    root = _repo(tmp_path)
    (root / ".env").write_text("SECRET=1\n", encoding="utf-8")
    (root / "backend" / "continuous_builder" / "skip.py").write_text(
        "Z=3\n", encoding="utf-8"
    )
    model = build_system_model(root, base_sha=BASE)
    # Seed cannot be forbidden at seal time; forbidden applies to neighborhood.
    req = seal_context_task_request(
        task_id="plan-3",
        base_sha=BASE,
        objective="omit forbidden",
        allowed_paths=["backend/continuous_builder/alpha.py"],
        forbidden_paths=["backend/continuous_builder/skip.py"],
        seed_paths=["backend/continuous_builder/alpha.py", ".env"],
        components=["backend.continuous_builder"],
        budget=seal_context_budget(dep_depth=1, max_excerpts=64),
    )
    plan = plan_context_selection(req, model)
    by_path = {item.path: item for item in plan.items if item.path}
    assert by_path[".env"].selection_tag == "OMITTED"
    assert by_path[".env"].editable is False
    if "backend/continuous_builder/skip.py" in by_path:
        assert by_path["backend/continuous_builder/skip.py"].selection_tag == (
            "OMITTED"
        )
        assert by_path["backend/continuous_builder/skip.py"].editable is False


def test_depth_bound_no_unbounded_recursion(tmp_path):
    root = _repo(tmp_path)
    model = build_system_model(root, base_sha=BASE)
    req = seal_context_task_request(
        task_id="plan-4",
        base_sha=BASE,
        objective="depth bound",
        seed_paths=["backend/continuous_builder/alpha.py"],
        components=["backend.continuous_builder"],
        budget=seal_context_budget(dep_depth=0, max_components=8, max_excerpts=16),
    )
    plan = plan_context_selection(req, model)
    assert len(plan.items) <= 64
    # depth 0: still has seeds; neighborhood expansion skipped
    assert plan.plan_sha256


def test_plan_deterministic(tmp_path):
    root = _repo(tmp_path)
    model = build_system_model(root, base_sha=BASE)
    req = seal_context_task_request(
        task_id="plan-5",
        base_sha=BASE,
        objective="determinism",
        seed_paths=["backend/continuous_builder/alpha.py"],
        allowed_paths=["backend/continuous_builder/alpha.py"],
    )
    a = plan_context_selection(req, model)
    b = plan_context_selection(req, model)
    assert a.plan_sha256 == b.plan_sha256
