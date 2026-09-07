"""CB-029H real MootOS integration Cases A–O + performance measurements."""

import time
from pathlib import Path

import pytest

from backend.continuous_builder.context_engine import (
    AUTHORITY_FLAGS,
    ENGINE_VERSION,
    assemble_context_package,
    context_engine_is_descriptive_only,
    context_request_grants_write_permission,
    enrich_interface_summary,
    extract_excerpt,
    fulfill_supplement,
    plan_context_selection,
    retrieve_architecture_evidence,
    retrieve_related_tests,
    seal_context_budget,
    seal_context_task_request,
    seal_supplement_request,
    selection_grants_edit_permission,
)
from backend.continuous_builder.system_model import (
    MODEL_VERSION,
    build_system_model,
    model_tcb_classification,
)
from backend.continuous_builder.trusted_policy import (
    create_mootos_tcb_registry_v1,
    is_tcb_path,
)


# Worktree HEAD base binding for evidence — use trusted main SHA used for branch.
TRUSTED_BASE = "ccd6bbe9e6a20939d2b7978286a5a618fa9c06cf"


def _repo_root():
    return Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def real_model():
    root = _repo_root()
    assert (root / "backend" / "continuous_builder" / "context_engine.py").is_file()
    return build_system_model(root, base_sha=TRUSTED_BASE)


@pytest.fixture(scope="module")
def real_package(real_model):
    root = _repo_root()
    req = seal_context_task_request(
        task_id="cb029-case-pack",
        base_sha=TRUSTED_BASE,
        objective="Build context for Context Engine maintenance",
        acceptance=("tests pass", "zero authority"),
        allowed_paths=["backend/continuous_builder/context_engine.py"],
        forbidden_paths=[],
        seed_paths=["backend/continuous_builder/context_engine.py"],
        components=["backend.continuous_builder"],
        non_goals=("no merge", "no github write", "no credential access"),
        budget=seal_context_budget(
            dep_depth=1,
            max_excerpts=64,
            package_budget_bytes=512 * 1024,
        ),
    )
    package, receipt = assemble_context_package(root, req, real_model)
    return root, req, package, receipt


def test_case_a_real_model_builds(real_model):
    assert real_model.model_version == MODEL_VERSION
    assert real_model.inventory.file_count > 50


def test_case_b_context_engine_file_excerpt(real_package):
    root, req, package, receipt = real_package
    ex = extract_excerpt(
        root,
        base_sha=TRUSTED_BASE,
        path="backend/continuous_builder/context_engine.py",
        region=(1, 40),
    )
    assert ex.available is True
    assert "Context Engine" in ex.text or "context" in ex.text.lower()
    assert ex.base_sha == TRUSTED_BASE


def test_case_c_plan_selects_cb_neighborhood(real_model):
    req = seal_context_task_request(
        task_id="case-c",
        base_sha=TRUSTED_BASE,
        objective="plan",
        seed_paths=["backend/continuous_builder/context_engine.py"],
        allowed_paths=["backend/continuous_builder/context_engine.py"],
        components=["backend.continuous_builder"],
    )
    plan = plan_context_selection(req, real_model)
    paths = {item.path for item in plan.items if item.path}
    assert "backend/continuous_builder/context_engine.py" in paths
    assert any(
        p and p.startswith("backend/continuous_builder/") for p in paths
    )


def test_case_d_visibility_not_write(real_package):
    _root, req, package, _receipt = real_package
    assert context_request_grants_write_permission(req) is False
    plan = plan_context_selection(req, build_system_model(_repo_root(), base_sha=TRUSTED_BASE))
    assert selection_grants_edit_permission(
        plan, "backend/continuous_builder/context_engine.py"
    ) is False


def test_case_e_interface_summary_real(real_package):
    root, _req, _package, _receipt = real_package
    summary = enrich_interface_summary(
        root,
        base_sha=TRUSTED_BASE,
        path="backend/continuous_builder/context_engine.py",
    )
    assert summary.available is True
    assert any("seal_context_task_request" in f for f in summary.functions)
    assert "assemble_context_package" in " ".join(summary.functions)


def test_case_f_related_tests_found(real_model):
    related = retrieve_related_tests(
        real_model,
        seed_paths=["backend/continuous_builder/context_engine.py"],
    )
    paths = {item["path"] for item in related}
    assert any("context_engine" in p for p in paths)


def test_case_g_architecture_docs(real_model, real_package):
    root, _req, _package, _receipt = real_package
    evidence = retrieve_architecture_evidence(
        root,
        real_model,
        base_sha=TRUSTED_BASE,
        seed_paths=["backend/continuous_builder/context_engine.py"],
    )
    paths = {item.path for item in evidence}
    assert any("architecture" in p.lower() or "continuous_builder" in p.lower() or p.upper().startswith("ADR") or "ARCHITECTURE" in p.upper() for p in paths)


def test_case_h_package_zero_authority(real_package):
    _root, _req, package, receipt = real_package
    for name in AUTHORITY_FLAGS:
        assert getattr(package, name) is False
        assert getattr(receipt, name) is False
    assert package.engine_version == ENGINE_VERSION


def test_case_i_tcb_paths_not_downgraded(real_model):
    registry = create_mootos_tcb_registry_v1()
    for path in registry.protected_paths:
        hit = model_tcb_classification(real_model, path)
        assert hit["is_tcb"] is True
    assert is_tcb_path("backend/continuous_builder/context_engine.py") is False
    assert context_engine_is_descriptive_only() is True


def test_case_j_system_model_still_outside_tcb(real_model):
    assert is_tcb_path("backend/continuous_builder/system_model.py") is False
    assert len(create_mootos_tcb_registry_v1().protected_paths) == 17


def test_case_k_supplement_interface(real_package, real_model):
    root, req, package, _receipt = real_package
    sreq = seal_supplement_request(
        original_request=req,
        package=package,
        worker_id="integration-worker",
        subject="backend/continuous_builder/system_model.py",
        reason="neighbor interface",
        category="interface_summary",
    )
    supp = fulfill_supplement(
        root, sreq, original_request=req, package=package, model=real_model
    )
    assert supp.granted is True
    assert supp.interface is not None
    assert supp.interface.available is True


def test_case_l_supplement_denies_env(real_package, real_model):
    root, req, package, _receipt = real_package
    sreq = seal_supplement_request(
        original_request=req,
        package=package,
        worker_id="integration-worker",
        subject=".env",
        reason="no",
        category="file_excerpt",
    )
    supp = fulfill_supplement(
        root, sreq, original_request=req, package=package, model=real_model
    )
    assert supp.granted is False


def test_case_m_package_under_budget(real_package):
    _root, req, package, receipt = real_package
    assert package.bytes_used <= req.budget.package_budget_bytes
    assert receipt.bytes_used == package.bytes_used
    assert package.completeness in (
        "sufficient",
        "sufficient_with_uncertainty",
        "incomplete",
        "restricted",
        "conflicting",
        "unknown",
    )


def test_case_n_cb028_query_reuse(real_model):
    # Context engine imports and uses model queries — smoke via plan.
    req = seal_context_task_request(
        task_id="case-n",
        base_sha=TRUSTED_BASE,
        objective="reuse",
        seed_paths=["backend/continuous_builder/system_model.py"],
        components=["backend.continuous_builder"],
    )
    plan = plan_context_selection(req, real_model)
    assert plan.model_sha256 == real_model.model_sha256


def test_case_o_determinism_on_real_tree(real_package, real_model):
    root, req, package, receipt = real_package
    package2, receipt2 = assemble_context_package(root, req, real_model)
    assert package.package_sha256 == package2.package_sha256
    assert receipt.receipt_sha256 == receipt2.receipt_sha256


def test_performance_measurements(real_model, real_package):
    root, req, package, receipt = real_package
    plan = plan_context_selection(req, real_model)
    considered = len(real_model.inventory.files)
    selected = len([i for i in plan.items if i.path])
    t0 = time.perf_counter()
    package2, receipt2 = assemble_context_package(root, req, real_model)
    elapsed_ms = (time.perf_counter() - t0) * 1000.0
    metrics = {
        "files_considered": considered,
        "files_selected": selected,
        "excerpt_count": receipt2.excerpt_count,
        "package_bytes": package2.bytes_used,
        "token_estimate": package2.token_estimate,
        "wall_clock_ms": round(elapsed_ms, 3),
        "dep_expansion_components": len(
            {i.component_id for i in plan.items if i.component_id}
        ),
    }
    # Persist for closure doc consumption.
    out = _repo_root() / "docs" / "future" / "_cb029_perf_metrics.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    import json
    out.write_text(json.dumps(metrics, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    assert metrics["files_considered"] > 50
    assert metrics["package_bytes"] > 0
    assert metrics["package_bytes"] <= req.budget.package_budget_bytes
    assert metrics["wall_clock_ms"] < 120_000
