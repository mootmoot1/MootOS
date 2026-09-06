"""CB-029A — Context Engine frozen contracts and seal identity."""

import dataclasses
import hashlib
import json

import pytest

from backend.continuous_builder.context_engine import (
    AUTHORITY_FLAGS,
    ENGINE_VERSION,
    ContextBudget,
    ContextEngineError,
    ContextScope,
    ContextTaskRequest,
    ContextUncertainty,
    SourceRef,
    context_engine_is_descriptive_only,
    context_request_grants_write_permission,
    seal_context_budget,
    seal_context_scope,
    seal_context_task_request,
    seal_source_ref,
    seal_uncertainty,
)


def _digest(value):
    if isinstance(value, str):
        value = value.encode("utf-8")
    return hashlib.sha256(value).hexdigest()


def _canonical(value):
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")


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


def _base():
    return "a" * 64


def test_engine_version_constant():
    assert ENGINE_VERSION == "cb-context-engine-v1"


def test_direct_construction_without_token_fails():
    with pytest.raises(ContextEngineError, match="trusted system construction"):
        ContextBudget(
            package_budget_bytes=1024,
            excerpt_budget_bytes=256,
            max_excerpts=1,
            max_components=1,
            max_seed_paths=1,
            dep_depth=0,
            budget_sha256="a" * 64,
        )
    with pytest.raises(ContextEngineError, match="trusted system construction"):
        ContextScope(
            allowed_paths=(),
            forbidden_paths=(),
            seed_paths=(),
            components=(),
            scope_sha256="a" * 64,
        )
    with pytest.raises(ContextEngineError, match="trusted system construction"):
        ContextUncertainty(
            kind="unknown",
            subject="x",
            detail_code="y",
            uncertainty_sha256="a" * 64,
        )


def test_seal_budget_deterministic_and_zero_authority():
    a = seal_context_budget()
    b = seal_context_budget()
    assert a.budget_sha256 == b.budget_sha256
    assert a.package_budget_bytes == 256 * 1024
    for name in AUTHORITY_FLAGS:
        assert getattr(a, name) is False


def test_seal_scope_canonicalizes_and_rejects_conflict():
    scope = seal_context_scope(
        allowed_paths=["b/a.py", "./b/a.py", "a/z.py"],
        forbidden_paths=["secret/x.py"],
        seed_paths=["b/a.py"],
        components=["backend.continuous_builder", "tests"],
    )
    assert scope.allowed_paths == ("a/z.py", "b/a.py")
    assert scope.seed_paths == ("b/a.py",)
    with pytest.raises(ContextEngineError, match="conflict"):
        seal_context_scope(
            allowed_paths=["a.py"],
            forbidden_paths=["a.py"],
        )
    with pytest.raises(ContextEngineError, match="forbidden"):
        seal_context_scope(
            forbidden_paths=["a.py"],
            seed_paths=["a.py"],
        )


def test_seal_request_binds_identity_no_timestamp():
    req = seal_context_task_request(
        task_id="cb029-demo-1",
        base_sha=_base(),
        objective="Assemble bounded context for a slice",
        acceptance=("tests pass", "zero authority"),
        allowed_paths=["backend/continuous_builder/context_engine.py"],
        forbidden_paths=[".env"],
        seed_paths=["backend/continuous_builder/context_engine.py"],
        components=["backend.continuous_builder"],
        non_goals=("no merge", "no github write"),
    )
    assert req.engine_version == ENGINE_VERSION
    assert req.request_sha256 == _digest(req._payload())
    again = seal_context_task_request(
        task_id="cb029-demo-1",
        base_sha=_base(),
        objective="Assemble bounded context for a slice",
        acceptance=("tests pass", "zero authority"),
        allowed_paths=["backend/continuous_builder/context_engine.py"],
        forbidden_paths=[".env"],
        seed_paths=["backend/continuous_builder/context_engine.py"],
        components=["backend.continuous_builder"],
        non_goals=("no merge", "no github write"),
    )
    assert again.request_sha256 == req.request_sha256
    raw = req.canonical_bytes()
    assert b"timestamp" not in raw
    assert b"created_at" not in raw
    for name in AUTHORITY_FLAGS:
        assert getattr(req, name) is False


def test_request_rejects_path_escape_and_absolute():
    with pytest.raises(ContextEngineError):
        seal_context_task_request(
            task_id="t1",
            base_sha=_base(),
            objective="x",
            seed_paths=["../escape.py"],
        )
    with pytest.raises(ContextEngineError):
        seal_context_task_request(
            task_id="t1",
            base_sha=_base(),
            objective="x",
            allowed_paths=["/etc/passwd"],
        )


def test_request_is_intent_not_permission():
    req = seal_context_task_request(
        task_id="t-intent",
        base_sha=_base(),
        objective="intent only",
        allowed_paths=["backend/continuous_builder/context_engine.py"],
        seed_paths=["backend/continuous_builder/context_engine.py"],
    )
    assert context_request_grants_write_permission(req) is False
    assert context_engine_is_descriptive_only() is True


def test_forged_request_digest_mismatch():
    req = seal_context_task_request(
        task_id="t-forge",
        base_sha=_base(),
        objective="orig",
    )
    forged = _forge(req, objective="tampered")
    with pytest.raises(ContextEngineError, match="digest mismatch"):
        ContextTaskRequest(**_fields(forged))


def test_source_ref_and_uncertainty_seal():
    src = seal_source_ref(
        kind="file_excerpt",
        path="backend/continuous_builder/context_engine.py",
        selection_tag="REQUIRED",
        digest="b" * 64,
        region=(1, 10),
    )
    assert src.source_sha256 == _digest(src._payload())
    unc = seal_uncertainty(
        kind="missing_source",
        subject="missing.py",
        detail_code="not_found",
    )
    assert unc.kind == "missing_source"
    for name in AUTHORITY_FLAGS:
        assert getattr(src, name) is False
        assert getattr(unc, name) is False


def test_malformed_base_sha_and_task_id():
    with pytest.raises(ContextEngineError, match="base_sha"):
        seal_context_task_request(
            task_id="t1",
            base_sha="not-a-sha",
            objective="x",
        )
    with pytest.raises(ContextEngineError, match="task_id"):
        seal_context_task_request(
            task_id="../evil",
            base_sha=_base(),
            objective="x",
        )


def test_budget_bounds():
    with pytest.raises(ContextEngineError):
        seal_context_budget(dep_depth=3)
    with pytest.raises(ContextEngineError):
        seal_context_budget(package_budget_bytes=100)
    with pytest.raises(ContextEngineError):
        seal_context_budget(max_seed_paths=0)
