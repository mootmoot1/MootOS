import ast
from dataclasses import FrozenInstanceError, replace
from pathlib import Path

import pytest

from backend.continuous_builder.repository_materialization import (
    RepositoryMaterializationError,
    VERIFICATION_REQUIREMENTS,
    create_planned_materialization_receipt,
    create_repository_materialization_contract,
)
from tests.test_continuous_builder_sandbox_repository import (
    _entry,
    _plan,
    _source,
)


def _contract(plan=None):
    return create_repository_materialization_contract(
        plan or _plan(), "materialization-attempt-1"
    )


def test_materialization_contract_binds_exact_reconstruction_evidence():
    request_plan = _plan(
        source=_source(entries=(_entry("a.py"), _entry("b.py")))
    )
    contract = _contract(request_plan)
    assert contract.repository_id == request_plan.source_evidence.repository_id
    assert contract.worker_request_digest == (
        request_plan.worker_request.request_digest
    )
    assert contract.attempt_id == request_plan.worker_request.attempt_id
    assert contract.pinned_base_sha == request_plan.pinned_base_sha
    assert contract.expected_file_count == 2
    assert contract.expected_total_bytes == 200
    assert contract.content_manifest_digest == (
        request_plan.source_evidence.manifest_sha256
    )
    assert contract.verification_requirements == VERIFICATION_REQUIREMENTS
    assert len(contract.canonical_bytes()) < 64 * 1024


def test_pre_execution_receipt_is_planned_but_never_verified_or_performed():
    receipt = create_planned_materialization_receipt(_contract())
    assert receipt.status == "planned_unverified"
    assert receipt.materialization_planned is True
    assert receipt.materialization_verified is False
    assert receipt.materialization_performed is False
    assert receipt.evidence_collected is False
    assert receipt.launch_authorized is False
    assert len(receipt.canonical_bytes()) < 64 * 1024


@pytest.mark.parametrize(
    "field,value",
    (
        ("worker_request_digest", "0" * 64),
        ("blueprint_digest", "0" * 64),
        ("slice_digest", "0" * 64),
        ("attempt_id", "wrong-attempt"),
        ("pinned_base_sha", "b" * 40),
        ("source_manifest_digest", "0" * 64),
        ("disposable_workspace_id", "disposable-other"),
        ("reconstruction_plan_digest", "0" * 64),
        ("materialization_mode", "verified_source_archive"),
        ("expected_file_count", 2),
        ("expected_total_bytes", 101),
        ("content_manifest_digest", "0" * 64),
        ("contract_sha256", "0" * 64),
    ),
)
def test_stale_or_forged_materialization_binding_rejected(field, value):
    with pytest.raises(RepositoryMaterializationError):
        replace(_contract(), **{field: value})


@pytest.mark.parametrize(
    "field",
    (
        "materialization_verified",
        "materialization_performed",
        "symlinks_allowed",
        "git_directory_allowed",
        "git_hooks_allowed",
        "inherited_git_config_allowed",
        "host_repository_reused",
        "host_workspace_reused",
        "launch_authorized",
    ),
)
def test_contract_cannot_claim_materialization_or_weaken_boundaries(field):
    with pytest.raises(
        RepositoryMaterializationError, match="overstates authority"
    ):
        replace(_contract(), **{field: True})


def test_caller_cannot_manufacture_verified_receipt():
    receipt = create_planned_materialization_receipt(_contract())
    for field in (
        "materialization_verified",
        "materialization_performed",
        "evidence_collected",
        "launch_authorized",
    ):
        with pytest.raises(
            RepositoryMaterializationError, match="fabricates"
        ):
            replace(receipt, **{field: True})
    with pytest.raises(RepositoryMaterializationError):
        replace(receipt, status="verified")


def test_verification_requirements_are_closed_and_immutable():
    contract = _contract()
    with pytest.raises(RepositoryMaterializationError, match="forged"):
        replace(
            contract,
            verification_requirements=("caller_says_verified",),
        )
    with pytest.raises(FrozenInstanceError):
        contract.materialization_verified = True


def test_manifest_order_produces_stable_materialization_identity():
    request = _plan().worker_request
    first = _contract(_plan(request=request, source=_source(request, entries=(
        _entry("z.py"), _entry("a.py"),
    ))))
    second = _contract(_plan(request=request, source=_source(request, entries=(
        _entry("a.py"), _entry("z.py"),
    ))))
    assert first.canonical_bytes() == second.canonical_bytes()
    assert first.contract_sha256 == second.contract_sha256


def test_module_has_no_materialization_execution_or_network_facility():
    source = Path(
        "backend/continuous_builder/repository_materialization.py"
    ).read_text(encoding="utf-8")
    tree = ast.parse(source)
    imports = {
        alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {
        node.module.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }
    assert not imports & {
        "subprocess", "socket", "requests", "httpx", "urllib", "docker",
        "podman", "kubernetes", "paramiko", "fabric", "pexpect", "os",
        "pathlib", "shutil", "git", "tarfile", "zipfile", "keyring",
    }
