"""CB-029H adversarial suite items 1–48 for Context Engine v1."""

import dataclasses
import time
from pathlib import Path

import pytest

from backend.continuous_builder.context_engine import (
    AUTHORITY_FLAGS,
    ENGINE_VERSION,
    HARD_MAX_PACKAGE_BUDGET_BYTES,
    MAX_DEP_DEPTH,
    MAX_SUPPLEMENTS_PER_PACKAGE,
    ContextEngineError,
    ContextPackage,
    ContextTaskRequest,
    assemble_context_package,
    classify_secret_path,
    context_engine_is_descriptive_only,
    context_request_grants_write_permission,
    enrich_interface_summary,
    extract_excerpt,
    fulfill_supplement,
    plan_context_selection,
    seal_context_budget,
    seal_context_task_request,
    seal_supplement_request,
    selection_grants_edit_permission,
)
from backend.continuous_builder.system_model import build_system_model
from backend.continuous_builder.trusted_policy import (
    create_mootos_tcb_registry_v1,
    is_tcb_path,
)


BASE = "aa" * 32


def _write(path, text="x\n"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _forge(instance, **changes):
    forged = object.__new__(type(instance))
    for item in dataclasses.fields(instance):
        object.__setattr__(
            forged,
            item.name,
            changes.get(item.name, getattr(instance, item.name)),
        )
    return forged


def _fields(instance):
    return {
        field.name: getattr(instance, field.name)
        for field in dataclasses.fields(instance)
    }


def _tiny(tmp_path):
    root = tmp_path / "repo"
    _write(root / "backend" / "__init__.py", "")
    _write(root / "backend" / "continuous_builder" / "__init__.py", "")
    _write(
        root / "backend" / "continuous_builder" / "mod.py",
        "VALUE = 1\ndef run(x):\n    return x\n",
    )
    _write(root / "tests" / "test_mod.py", "def test_m():\n    assert True\n")
    return root


def test_01_direct_package_construction_fails():
    with pytest.raises(ContextEngineError, match="trusted system construction"):
        ContextPackage(
            engine_version=ENGINE_VERSION,
            request_sha256="a" * 64,
            model_sha256="b" * 64,
            base_sha=BASE,
            completeness="sufficient",
            excerpts=(),
            interfaces=(),
            dependency_summaries=(),
            tests=(),
            architecture=(),
            source_refs=(),
            uncertainties=(),
            tcb_warnings=(),
            bytes_used=0,
            token_estimate=0,
            needs_review=False,
            package_sha256="c" * 64,
        )


def test_02_cannot_set_authority_true_on_request():
    req = seal_context_task_request(
        task_id="adv-2", base_sha=BASE, objective="x"
    )
    forged = _forge(req, publication_authorized=True)
    with pytest.raises(ContextEngineError):
        ContextTaskRequest(**_fields(forged))


def test_03_request_does_not_grant_write():
    req = seal_context_task_request(
        task_id="adv-3",
        base_sha=BASE,
        objective="x",
        allowed_paths=["backend/continuous_builder/mod.py"],
        seed_paths=["backend/continuous_builder/mod.py"],
    )
    assert context_request_grants_write_permission(req) is False


def test_04_symlink_excerpt_unavailable(tmp_path):
    root = _tiny(tmp_path)
    target = root / "backend" / "continuous_builder" / "mod.py"
    link = root / "backend" / "continuous_builder" / "link.py"
    link.symlink_to(target)
    ex = extract_excerpt(root, base_sha=BASE, path="backend/continuous_builder/link.py")
    assert ex.available is False
    assert "VALUE" not in ex.text


def test_05_traversal_unavailable(tmp_path):
    root = _tiny(tmp_path)
    ex = extract_excerpt(root, base_sha=BASE, path="../escape.py")
    assert ex.available is False
    assert ex.text == ""


def test_06_absolute_path_unavailable(tmp_path):
    root = _tiny(tmp_path)
    ex = extract_excerpt(root, base_sha=BASE, path="/etc/passwd")
    assert ex.available is False


def test_07_env_secret_excluded(tmp_path):
    root = _tiny(tmp_path)
    _write(root / ".env", "SECRET_TOKEN=leak-me-now\n")
    ex = extract_excerpt(root, base_sha=BASE, path=".env")
    assert ex.available is False
    assert "leak-me-now" not in ex.text
    assert "leak-me-now" not in str(ex.to_dict())


def test_08_private_key_excluded(tmp_path):
    root = _tiny(tmp_path)
    _write(root / "server.pem", "-----BEGIN " + "PRIVATE KEY-----\nABC\n")
    assert classify_secret_path("server.pem") is not None
    ex = extract_excerpt(root, base_sha=BASE, path="server.pem")
    assert ex.available is False
    assert "ABC" not in ex.text


def test_09_ssh_dir_excluded(tmp_path):
    root = _tiny(tmp_path)
    _write(root / ".ssh" / "id_rsa", "-----BEGIN " + "OPENSSH PRIVATE KEY-----\nZ\n")
    ex = extract_excerpt(root, base_sha=BASE, path=".ssh/id_rsa")
    assert ex.available is False
    assert "Z" not in ex.text


def test_10_authorization_header_content_excluded(tmp_path):
    root = _tiny(tmp_path)
    _write(root / "notes.md", "Authorization: " + "Bearer SECRETJWT\n")
    ex = extract_excerpt(root, base_sha=BASE, path="notes.md")
    assert ex.available is False
    assert "SECRETJWT" not in ex.text


def test_11_git_path_rejected(tmp_path):
    root = _tiny(tmp_path)
    _write(root / ".git" / "config", "[core]\n")
    ex = extract_excerpt(root, base_sha=BASE, path=".git/config")
    assert ex.available is False


def test_12_db_wal_rejected(tmp_path):
    root = _tiny(tmp_path)
    _write(root / "data" / "mootos.db-wal", "walbytes")
    ex = extract_excerpt(root, base_sha=BASE, path="data/mootos.db-wal")
    assert ex.available is False
    assert "walbytes" not in ex.text


def test_13_binary_non_text(tmp_path):
    root = _tiny(tmp_path)
    p = root / "x.bin"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"\x00\xff" * 50)
    ex = extract_excerpt(root, base_sha=BASE, path="x.bin")
    assert ex.available is False
    assert ex.restriction == "non_text"


def test_14_planner_visibility_not_edit(tmp_path):
    root = _tiny(tmp_path)
    model = build_system_model(root, base_sha=BASE)
    req = seal_context_task_request(
        task_id="adv-14",
        base_sha=BASE,
        objective="vis",
        allowed_paths=["backend/continuous_builder/mod.py"],
        seed_paths=["backend/continuous_builder/mod.py"],
        components=["backend.continuous_builder"],
    )
    plan = plan_context_selection(req, model)
    assert selection_grants_edit_permission(
        plan, "backend/continuous_builder/mod.py"
    ) is False


def test_15_forbidden_not_seedable():
    with pytest.raises(ContextEngineError):
        seal_context_task_request(
            task_id="adv-15",
            base_sha=BASE,
            objective="x",
            forbidden_paths=["a.py"],
            seed_paths=["a.py"],
        )


def test_16_dep_depth_hard_max():
    with pytest.raises(ContextEngineError):
        seal_context_budget(dep_depth=MAX_DEP_DEPTH + 1)


def test_17_package_budget_hard_max():
    with pytest.raises(ContextEngineError):
        seal_context_budget(
            package_budget_bytes=HARD_MAX_PACKAGE_BUDGET_BYTES + 1
        )


def test_18_base_sha_mismatch_assemble(tmp_path):
    root = _tiny(tmp_path)
    model = build_system_model(root, base_sha=BASE)
    req = seal_context_task_request(
        task_id="adv-18",
        base_sha="bb" * 32,
        objective="mismatch",
        seed_paths=["backend/continuous_builder/mod.py"],
    )
    with pytest.raises(ContextEngineError, match="base_sha"):
        assemble_context_package(root, req, model)


def test_19_ast_no_default_eval(tmp_path):
    root = _tiny(tmp_path)
    _write(
        root / "backend" / "continuous_builder" / "defs.py",
        "def f(a=open('/etc/passwd')):\n    return a\n",
    )
    summary = enrich_interface_summary(
        root, base_sha=BASE, path="backend/continuous_builder/defs.py"
    )
    assert summary.available is True
    assert "open" not in summary.functions[0]
    assert "/etc/passwd" not in str(summary.to_dict())


def test_20_parse_failure_restricted(tmp_path):
    root = _tiny(tmp_path)
    _write(root / "backend" / "continuous_builder" / "bad.py", "def (\n")
    summary = enrich_interface_summary(
        root, base_sha=BASE, path="backend/continuous_builder/bad.py"
    )
    assert summary.available is False
    assert summary.restriction == "parse_failure"


def test_21_supplement_cannot_remove_forbidden(tmp_path):
    root = _tiny(tmp_path)
    _write(root / "backend" / "continuous_builder" / "nope.py", "N=1\n")
    model = build_system_model(root, base_sha=BASE)
    req = seal_context_task_request(
        task_id="adv-21",
        base_sha=BASE,
        objective="x",
        allowed_paths=["backend/continuous_builder/mod.py"],
        forbidden_paths=["backend/continuous_builder/nope.py"],
        seed_paths=["backend/continuous_builder/mod.py"],
    )
    package, _ = assemble_context_package(root, req, model)
    sreq = seal_supplement_request(
        original_request=req,
        package=package,
        worker_id="w1",
        subject="backend/continuous_builder/nope.py",
        reason="bypass",
        category="file_excerpt",
    )
    supp = fulfill_supplement(
        root, sreq, original_request=req, package=package, model=model
    )
    assert supp.granted is False


def test_22_supplement_secret_bypass_denied(tmp_path):
    root = _tiny(tmp_path)
    _write(root / ".env", "S=1\n")
    model = build_system_model(root, base_sha=BASE)
    req = seal_context_task_request(
        task_id="adv-22",
        base_sha=BASE,
        objective="x",
        seed_paths=["backend/continuous_builder/mod.py"],
        allowed_paths=["backend/continuous_builder/mod.py"],
    )
    package, _ = assemble_context_package(root, req, model)
    sreq = seal_supplement_request(
        original_request=req,
        package=package,
        worker_id="w1",
        subject=".env",
        reason="need secret",
        category="file_excerpt",
    )
    supp = fulfill_supplement(
        root, sreq, original_request=req, package=package, model=model
    )
    assert supp.granted is False
    assert supp.denial_code == "secret_bypass_denied"


def test_23_supplement_cap_hard(tmp_path):
    root = _tiny(tmp_path)
    model = build_system_model(root, base_sha=BASE)
    req = seal_context_task_request(
        task_id="adv-23",
        base_sha=BASE,
        objective="x",
        seed_paths=["backend/continuous_builder/mod.py"],
        allowed_paths=["backend/continuous_builder/mod.py"],
    )
    package, _ = assemble_context_package(root, req, model)
    sreq = seal_supplement_request(
        original_request=req,
        package=package,
        worker_id="w1",
        subject="backend/continuous_builder/mod.py",
        reason="cap",
        category="file_excerpt",
    )
    supp = fulfill_supplement(
        root,
        sreq,
        original_request=req,
        package=package,
        model=model,
        prior_supplement_count=MAX_SUPPLEMENTS_PER_PACKAGE,
    )
    assert supp.granted is False
    assert supp.denial_code == "supplement_cap_exceeded"


def test_24_replay_wrong_package(tmp_path):
    root = _tiny(tmp_path)
    model = build_system_model(root, base_sha=BASE)
    req = seal_context_task_request(
        task_id="adv-24",
        base_sha=BASE,
        objective="x",
        seed_paths=["backend/continuous_builder/mod.py"],
        allowed_paths=["backend/continuous_builder/mod.py"],
    )
    package, _ = assemble_context_package(root, req, model)
    req2 = seal_context_task_request(
        task_id="adv-24b",
        base_sha=BASE,
        objective="y",
        seed_paths=["backend/continuous_builder/mod.py"],
        allowed_paths=["backend/continuous_builder/mod.py"],
    )
    package2, _ = assemble_context_package(root, req2, model)
    sreq = seal_supplement_request(
        original_request=req,
        package=package,
        worker_id="w1",
        subject="backend/continuous_builder/mod.py",
        reason="replay",
        category="file_excerpt",
    )
    # Use package2 with req → identity fail inside fulfill when package digest
    # does not match sealed request binding... seal binds package digest;
    # fulfill checks package.sha == supp_req.package_sha256.
    # Manually call fulfill with wrong package:
    bad = fulfill_supplement(
        root, sreq, original_request=req, package=package2, model=model
    )
    assert bad.granted is False
    assert bad.denial_code == "replay_wrong_package"


def test_25_zero_authority_on_assembled_package(tmp_path):
    root = _tiny(tmp_path)
    model = build_system_model(root, base_sha=BASE)
    req = seal_context_task_request(
        task_id="adv-25",
        base_sha=BASE,
        objective="x",
        seed_paths=["backend/continuous_builder/mod.py"],
        allowed_paths=["backend/continuous_builder/mod.py"],
    )
    package, receipt = assemble_context_package(root, req, model)
    for name in AUTHORITY_FLAGS:
        assert getattr(package, name) is False
        assert getattr(receipt, name) is False


def test_26_missing_does_not_claim_sufficient_without_seeds(tmp_path):
    root = _tiny(tmp_path)
    model = build_system_model(root, base_sha=BASE)
    req = seal_context_task_request(
        task_id="adv-26",
        base_sha=BASE,
        objective="empty seeds",
    )
    package, _ = assemble_context_package(root, req, model)
    assert package.completeness in (
        "unknown",
        "sufficient_with_uncertainty",
        "incomplete",
        "restricted",
    )


def test_27_ambiguity_not_certainty(tmp_path):
    root = _tiny(tmp_path)
    model = build_system_model(root, base_sha=BASE)
    req = seal_context_task_request(
        task_id="adv-27",
        base_sha=BASE,
        objective="x",
        seed_paths=["backend/continuous_builder/mod.py"],
        allowed_paths=["backend/continuous_builder/mod.py"],
    )
    plan = plan_context_selection(req, model)
    # UNKNOWN tags remain UNKNOWN — never rewritten to REQUIRED silently for missing
    for item in plan.items:
        if item.selection_tag == "UNKNOWN":
            assert item.editable is False


def test_28_engine_outside_tcb_descriptive():
    assert context_engine_is_descriptive_only() is True
    assert is_tcb_path("backend/continuous_builder/context_engine.py") is False
    registry = create_mootos_tcb_registry_v1()
    assert "backend/continuous_builder/context_engine.py" not in (
        registry.protected_paths
    )
    assert len(registry.protected_paths) == 13


def test_29_ordering_stable_identity(tmp_path):
    root = _tiny(tmp_path)
    model = build_system_model(root, base_sha=BASE)
    req = seal_context_task_request(
        task_id="adv-29",
        base_sha=BASE,
        objective="stable",
        seed_paths=["backend/continuous_builder/mod.py"],
        allowed_paths=["backend/continuous_builder/mod.py"],
    )
    a, _ = assemble_context_package(root, req, model)
    b, _ = assemble_context_package(root, req, model)
    assert a.package_sha256 == b.package_sha256


def test_30_tampered_package_digest_rejected(tmp_path):
    root = _tiny(tmp_path)
    model = build_system_model(root, base_sha=BASE)
    req = seal_context_task_request(
        task_id="adv-30",
        base_sha=BASE,
        objective="x",
        seed_paths=["backend/continuous_builder/mod.py"],
        allowed_paths=["backend/continuous_builder/mod.py"],
    )
    package, _ = assemble_context_package(root, req, model)
    forged = _forge(package, completeness="sufficient")
    # Force wrong digest
    forged2 = _forge(package, package_sha256="0" * 64)
    with pytest.raises(ContextEngineError):
        ContextPackage(**_fields(forged2))


def test_31_whole_repo_supplement_denied(tmp_path):
    root = _tiny(tmp_path)
    model = build_system_model(root, base_sha=BASE)
    req = seal_context_task_request(
        task_id="adv-31",
        base_sha=BASE,
        objective="x",
        seed_paths=["backend/continuous_builder/mod.py"],
        allowed_paths=["backend/continuous_builder/mod.py"],
    )
    package, _ = assemble_context_package(root, req, model)
    sreq = seal_supplement_request(
        original_request=req,
        package=package,
        worker_id="w1",
        subject="*",
        reason="all",
        category="file_excerpt",
    )
    supp = fulfill_supplement(
        root, sreq, original_request=req, package=package, model=model
    )
    assert supp.granted is False


def test_32_credentials_json_excluded(tmp_path):
    root = _tiny(tmp_path)
    _write(root / "credentials.json", '{"password":"p"}\n')
    ex = extract_excerpt(root, base_sha=BASE, path="credentials.json")
    assert ex.available is False
    assert "password" not in ex.text


def test_33_api_key_filename_excluded(tmp_path):
    root = _tiny(tmp_path)
    _write(root / "svc_api_key.txt", "KEY=1\n")
    assert classify_secret_path("svc_api_key.txt") is not None


def test_34_cookie_file_excluded(tmp_path):
    root = _tiny(tmp_path)
    _write(root / "cookies.txt", "cookie\n")
    ex = extract_excerpt(root, base_sha=BASE, path="cookies.txt")
    assert ex.available is False


def test_35_home_path_rejected():
    with pytest.raises(ContextEngineError):
        seal_context_task_request(
            task_id="adv-35",
            base_sha=BASE,
            objective="x",
            seed_paths=["~/secret"],
        )


def test_36_seed_bound(tmp_path):
    paths = [f"f{i}.py" for i in range(65)]
    with pytest.raises(ContextEngineError):
        seal_context_task_request(
            task_id="adv-36",
            base_sha=BASE,
            objective="x",
            seed_paths=paths,
        )


def test_37_unsupported_supplement_category(tmp_path):
    root = _tiny(tmp_path)
    model = build_system_model(root, base_sha=BASE)
    req = seal_context_task_request(
        task_id="adv-37",
        base_sha=BASE,
        objective="x",
        seed_paths=["backend/continuous_builder/mod.py"],
        allowed_paths=["backend/continuous_builder/mod.py"],
    )
    package, _ = assemble_context_package(root, req, model)
    with pytest.raises(ContextEngineError):
        seal_supplement_request(
            original_request=req,
            package=package,
            worker_id="w1",
            subject="backend/continuous_builder/mod.py",
            reason="x",
            category="shell_exec",
        )


def test_38_tcb_visible_not_downgraded(tmp_path):
    # On tiny repo TCB paths may be missing; classification still fail-closed.
    root = _tiny(tmp_path)
    model = build_system_model(root, base_sha=BASE)
    req = seal_context_task_request(
        task_id="adv-38",
        base_sha=BASE,
        objective="x",
        seed_paths=["backend/continuous_builder/mod.py"],
        allowed_paths=["backend/continuous_builder/mod.py"],
    )
    package, _ = assemble_context_package(root, req, model)
    sreq = seal_supplement_request(
        original_request=req,
        package=package,
        worker_id="w1",
        subject="backend/continuous_builder/verifier_core.py",
        reason="tcb",
        category="tcb_classification",
    )
    supp = fulfill_supplement(
        root, sreq, original_request=req, package=package, model=model
    )
    assert supp.granted is True
    assert supp.tcb_classification is not None


def test_39_no_network_imports_in_engine_module():
    text = Path("backend/continuous_builder/context_engine.py").read_text(
        encoding="utf-8"
    )
    for banned in ("import socket", "import urllib", "import requests", "import http"):
        assert banned not in text


def test_40_no_subprocess_shell_in_engine_module():
    text = Path("backend/continuous_builder/context_engine.py").read_text(
        encoding="utf-8"
    )
    for banned in ("subprocess", "os.system", "pty.", "importlib"):
        assert banned not in text


def test_41_completeness_descriptive_only(tmp_path):
    root = _tiny(tmp_path)
    model = build_system_model(root, base_sha=BASE)
    req = seal_context_task_request(
        task_id="adv-41",
        base_sha=BASE,
        objective="x",
        seed_paths=["backend/continuous_builder/mod.py"],
        allowed_paths=["backend/continuous_builder/mod.py"],
    )
    package, _ = assemble_context_package(root, req, model)
    assert not hasattr(package, "approve")
    assert not hasattr(package, "merge")
    assert not hasattr(package, "execute")


def test_42_plan_omits_secret_seed(tmp_path):
    root = _tiny(tmp_path)
    _write(root / ".env", "S=1\n")
    model = build_system_model(root, base_sha=BASE)
    req = seal_context_task_request(
        task_id="adv-42",
        base_sha=BASE,
        objective="x",
        seed_paths=["backend/continuous_builder/mod.py", ".env"],
        allowed_paths=["backend/continuous_builder/mod.py"],
    )
    plan = plan_context_selection(req, model)
    env_items = [i for i in plan.items if i.path == ".env"]
    assert env_items
    assert env_items[0].selection_tag == "OMITTED"


def test_43_receipt_binds_digests(tmp_path):
    root = _tiny(tmp_path)
    model = build_system_model(root, base_sha=BASE)
    req = seal_context_task_request(
        task_id="adv-43",
        base_sha=BASE,
        objective="x",
        seed_paths=["backend/continuous_builder/mod.py"],
        allowed_paths=["backend/continuous_builder/mod.py"],
    )
    package, receipt = assemble_context_package(root, req, model)
    assert receipt.package_sha256 == package.package_sha256
    assert receipt.request_sha256 == req.request_sha256
    assert receipt.model_sha256 == model.model_sha256
    assert receipt.base_sha == BASE


def test_44_excerpt_digest_changes_with_content(tmp_path):
    root = _tiny(tmp_path)
    a = extract_excerpt(
        root, base_sha=BASE, path="backend/continuous_builder/mod.py"
    )
    _write(
        root / "backend" / "continuous_builder" / "mod.py",
        "VALUE = 2\ndef run(x):\n    return x\n",
    )
    b = extract_excerpt(
        root, base_sha=BASE, path="backend/continuous_builder/mod.py"
    )
    assert a.excerpt_sha256 != b.excerpt_sha256


def test_45_allowed_forbidden_conflict_rejected():
    with pytest.raises(ContextEngineError):
        seal_context_task_request(
            task_id="adv-45",
            base_sha=BASE,
            objective="x",
            allowed_paths=["a.py"],
            forbidden_paths=["a.py"],
        )


def test_46_engine_does_not_expand_tcb_registry():
    before = create_mootos_tcb_registry_v1().registry_sha256
    assert before == create_mootos_tcb_registry_v1().registry_sha256
    assert len(create_mootos_tcb_registry_v1().protected_paths) == 13


def test_47_supplement_cannot_change_objective_identity(tmp_path):
    root = _tiny(tmp_path)
    model = build_system_model(root, base_sha=BASE)
    req = seal_context_task_request(
        task_id="adv-47",
        base_sha=BASE,
        objective="original-objective",
        seed_paths=["backend/continuous_builder/mod.py"],
        allowed_paths=["backend/continuous_builder/mod.py"],
    )
    package, _ = assemble_context_package(root, req, model)
    sreq = seal_supplement_request(
        original_request=req,
        package=package,
        worker_id="w1",
        subject="backend/continuous_builder/mod.py",
        reason="x",
        category="file_excerpt",
    )
    assert sreq.original_request_sha256 == req.request_sha256
    # No field exists to rewrite objective via supplement.
    assert not hasattr(sreq, "objective")


def test_48_context_engine_not_authority():
    assert context_engine_is_descriptive_only() is True
