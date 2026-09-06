"""CB-029G — supplement protocol bounds and denials."""

import pytest

from backend.continuous_builder.context_engine import (
    AUTHORITY_FLAGS,
    MAX_SUPPLEMENTS_PER_PACKAGE,
    assemble_context_package,
    fulfill_supplement,
    seal_context_task_request,
    seal_supplement_request,
)
from backend.continuous_builder.system_model import build_system_model


BASE = "11" * 32


def _setup(tmp_path):
    root = tmp_path / "repo"
    (root / "backend" / "continuous_builder").mkdir(parents=True)
    (root / "backend" / "__init__.py").write_text("", encoding="utf-8")
    (root / "backend" / "continuous_builder" / "__init__.py").write_text(
        "", encoding="utf-8"
    )
    (root / "backend" / "continuous_builder" / "target.py").write_text(
        "VALUE = 1\ndef run():\n    return VALUE\n", encoding="utf-8"
    )
    (root / "backend" / "continuous_builder" / "extra.py").write_text(
        "EXTRA = 2\n", encoding="utf-8"
    )
    (root / ".env").write_text("SECRET=1\n", encoding="utf-8")
    (root / "tests").mkdir()
    (root / "tests" / "test_target.py").write_text(
        "def test_t():\n    assert True\n", encoding="utf-8"
    )
    model = build_system_model(root, base_sha=BASE)
    req = seal_context_task_request(
        task_id="supp-1",
        base_sha=BASE,
        objective="supplement demo",
        allowed_paths=["backend/continuous_builder/target.py"],
        forbidden_paths=["backend/continuous_builder/extra.py"],
        seed_paths=["backend/continuous_builder/target.py"],
        components=["backend.continuous_builder"],
    )
    package, _receipt = assemble_context_package(root, req, model)
    return root, model, req, package


def test_grant_file_excerpt_supplement(tmp_path):
    root, model, req, package = _setup(tmp_path)
    sreq = seal_supplement_request(
        original_request=req,
        package=package,
        worker_id="worker-1",
        subject="backend/continuous_builder/target.py",
        reason="need more lines",
        category="file_excerpt",
    )
    supp = fulfill_supplement(
        root, sreq, original_request=req, package=package, model=model
    )
    assert supp.granted is True
    assert supp.excerpt is not None
    assert supp.excerpt.available is True
    for name in AUTHORITY_FLAGS:
        assert getattr(supp, name) is False


def test_deny_forbidden_and_secret_and_shell(tmp_path):
    root, model, req, package = _setup(tmp_path)
    for subject, category, code in (
        ("backend/continuous_builder/extra.py", "file_excerpt", "forbidden_path"),
        (".env", "file_excerpt", "secret_bypass_denied"),
        ("shell:rm -rf", "file_excerpt", "shell_denied"),
        ("whole-repo", "file_excerpt", "whole_repo_denied"),
    ):
        sreq = seal_supplement_request(
            original_request=req,
            package=package,
            worker_id="worker-1",
            subject=subject,
            reason="probe",
            category=category,
        )
        supp = fulfill_supplement(
            root, sreq, original_request=req, package=package, model=model
        )
        assert supp.granted is False
        assert supp.denial_code == code


def test_deny_replay_wrong_task_or_revision(tmp_path):
    root, model, req, package = _setup(tmp_path)
    other = seal_context_task_request(
        task_id="supp-other",
        base_sha=BASE,
        objective="other",
        seed_paths=["backend/continuous_builder/target.py"],
        allowed_paths=["backend/continuous_builder/target.py"],
    )
    sreq = seal_supplement_request(
        original_request=req,
        package=package,
        worker_id="worker-1",
        subject="backend/continuous_builder/target.py",
        reason="replay",
        category="file_excerpt",
    )
    # Wrong original request identity
    bad = fulfill_supplement(
        root, sreq, original_request=other, package=package, model=model
    )
    assert bad.granted is False
    assert bad.denial_code == "replay_wrong_task"


def test_supplement_cap(tmp_path):
    root, model, req, package = _setup(tmp_path)
    sreq = seal_supplement_request(
        original_request=req,
        package=package,
        worker_id="worker-1",
        subject="backend/continuous_builder/target.py",
        reason="cap",
        category="interface_summary",
    )
    denied = fulfill_supplement(
        root,
        sreq,
        original_request=req,
        package=package,
        model=model,
        prior_supplement_count=MAX_SUPPLEMENTS_PER_PACKAGE,
    )
    assert denied.granted is False
    assert denied.denial_code == "supplement_cap_exceeded"


def test_cannot_enlarge_write_via_supplement(tmp_path):
    root, model, req, package = _setup(tmp_path)
    # Neighbor not in allowed_paths — may be readable as excerpt but does not
    # enlarge write permission (forbidden still denied; allowed unchanged).
    sreq = seal_supplement_request(
        original_request=req,
        package=package,
        worker_id="worker-1",
        subject="backend/continuous_builder/extra.py",
        reason="try enlarge",
        category="file_excerpt",
    )
    supp = fulfill_supplement(
        root, sreq, original_request=req, package=package, model=model
    )
    assert supp.granted is False
    assert "extra.py" not in req.scope.allowed_paths
