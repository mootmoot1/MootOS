import ast
import dataclasses
import os
from dataclasses import FrozenInstanceError

import pytest

import backend.continuous_builder.worker_artifact as worker_artifact
import backend.continuous_builder.worker_runtime as worker_runtime
from backend.continuous_builder.worker_artifact import (
    ArtifactInventoryEntry,
    WorkerArtifactError,
    intake_worker_artifacts,
)
from tests.test_continuous_builder_worker_runtime import _execute


def _stage(tmp_path, monkeypatch, files=None, *, receipt=None):
    if receipt is None:
        receipt, _ = _execute(tmp_path, monkeypatch)
    intake_root = tmp_path / "artifact-intake"
    monkeypatch.setattr(worker_artifact, "ARTIFACT_INTAKE_ROOT", intake_root)
    root = intake_root / receipt.execution_id
    root.mkdir(parents=True)
    source_files = files or {"result.txt": b"bounded output\n"}
    for name, content in source_files.items():
        path = root.joinpath(*name.split("/"))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    return receipt, root


def _forge(instance, **changes):
    forged = object.__new__(type(instance))
    for field in dataclasses.fields(instance):
        object.__setattr__(
            forged,
            field.name,
            changes.get(field.name, getattr(instance, field.name)),
        )
    return forged


def _runtime_bytes(*parts):
    return b"".join(parts)


def test_clean_artifacts_enter_untrusted_quarantine(tmp_path, monkeypatch):
    receipt, root = _stage(
        tmp_path,
        monkeypatch,
        {"nested/βeta.txt": "deterministic ✓\n".encode("utf-8")},
    )
    result = intake_worker_artifacts(receipt, root)

    assert result.receipt.status == "quarantined_untrusted"
    assert result.receipt.scan_performed is True
    assert result.receipt.scan_passed is True
    assert result.receipt.suspicious_secret_material_detected is False
    assert result.receipt.execution_receipt_digest == receipt.receipt_sha256
    assert result.receipt.attempt_id == receipt.attempt_id
    assert result.receipt.request_digest == receipt.request_digest
    assert result.receipt.execution_id == receipt.execution_id
    assert result.receipt.policy_digest == receipt.policy_digest
    assert result.receipt.materialization_receipt_digest == (
        receipt.materialization_receipt_digest
    )
    assert result.receipt.workspace_identity == (
        receipt.materialization_receipt.workspace_instance_digest
    )
    assert result.quarantine_package.artifact_content_trusted is False
    assert result.quarantine_package.patch_verified is False
    assert result.quarantine_package.result_verified is False
    assert result.quarantine_package.publication_authorized is False
    assert result.quarantine_package.queue_transition_authorized is False
    assert result.quarantine_package.github_authorized is False


def test_inventory_is_deterministic_independent_of_enumeration_order(
    tmp_path, monkeypatch,
):
    receipt, root = _stage(
        tmp_path, monkeypatch, {"z.txt": b"z", "a.txt": b"a"}
    )
    first = intake_worker_artifacts(receipt, root)
    second = intake_worker_artifacts(receipt, root)
    assert first.receipt == second.receipt
    assert first.quarantine_package == second.quarantine_package
    assert [
        entry.relative_path for entry in first.quarantine_package.inventory
    ] == ["a.txt", "z.txt"]


@pytest.mark.parametrize("path", ("../escape", "/absolute", "C:/drive"))
def test_unsafe_inventory_paths_are_rejected(path):
    with pytest.raises(WorkerArtifactError):
        ArtifactInventoryEntry(path, "regular_file", 1, "a" * 64)


def test_excessive_inventory_path_is_rejected():
    with pytest.raises(WorkerArtifactError):
        ArtifactInventoryEntry("a" * 1025, "regular_file", 1, "a" * 64)


def test_symlink_is_rejected(tmp_path, monkeypatch):
    receipt, root = _stage(tmp_path, monkeypatch)
    (root / "link").symlink_to(root / "result.txt")
    with pytest.raises(WorkerArtifactError, match="filesystem type"):
        intake_worker_artifacts(receipt, root)


def test_hard_link_is_rejected(tmp_path, monkeypatch):
    receipt, root = _stage(tmp_path, monkeypatch)
    os.link(root / "result.txt", root / "second.txt")
    with pytest.raises(WorkerArtifactError, match="filesystem type"):
        intake_worker_artifacts(receipt, root)


def test_unsupported_fifo_is_rejected(tmp_path, monkeypatch):
    receipt, root = _stage(tmp_path, monkeypatch)
    os.mkfifo(root / "fifo")
    with pytest.raises(WorkerArtifactError, match="filesystem type"):
        intake_worker_artifacts(receipt, root)


def test_individual_file_size_overflow_is_rejected(tmp_path, monkeypatch):
    monkeypatch.setattr(worker_artifact, "MAX_ARTIFACT_BYTES", 4)
    receipt, root = _stage(tmp_path, monkeypatch, {"large.txt": b"12345"})
    with pytest.raises(WorkerArtifactError, match="individual size"):
        intake_worker_artifacts(receipt, root)


def test_total_artifact_size_overflow_is_rejected(tmp_path, monkeypatch):
    monkeypatch.setattr(worker_artifact, "MAX_TOTAL_ARTIFACT_BYTES", 5)
    receipt, root = _stage(
        tmp_path, monkeypatch, {"one.txt": b"123", "two.txt": b"456"}
    )
    with pytest.raises(WorkerArtifactError, match="total bytes"):
        intake_worker_artifacts(receipt, root)


def test_artifact_count_overflow_is_rejected(tmp_path, monkeypatch):
    monkeypatch.setattr(worker_artifact, "MAX_ARTIFACTS", 1)
    receipt, root = _stage(
        tmp_path, monkeypatch, {"one.txt": b"1", "two.txt": b"2"}
    )
    with pytest.raises(WorkerArtifactError, match="count"):
        intake_worker_artifacts(receipt, root)


def test_artifact_root_outside_supervisor_authority_is_rejected(
    tmp_path, monkeypatch,
):
    receipt, _ = _stage(tmp_path, monkeypatch)
    outside = tmp_path / "data" / "mootos.db-wal"
    outside.parent.mkdir()
    outside.write_bytes(b"do not inspect")
    with pytest.raises(WorkerArtifactError, match="outside intake authority"):
        intake_worker_artifacts(receipt, outside)


@pytest.mark.parametrize(
    "field,value",
    (
        ("attempt_id", "attempt-other"),
        ("request_digest", "a" * 64),
        ("receipt_sha256", "b" * 64),
    ),
)
def test_stale_or_mismatched_execution_binding_is_rejected(
    tmp_path, monkeypatch, field, value,
):
    receipt, root = _stage(tmp_path, monkeypatch)
    forged = _forge(receipt, **{field: value})
    with pytest.raises(WorkerArtifactError):
        intake_worker_artifacts(forged, root)


def test_worker_cannot_fabricate_trusted_quarantine_receipt(
    tmp_path, monkeypatch,
):
    receipt, root = _stage(tmp_path, monkeypatch)
    result = intake_worker_artifacts(receipt, root)
    package = result.quarantine_package
    with pytest.raises(WorkerArtifactError, match="trusted observed evidence"):
        dataclasses.replace(package, _scan_token=None)
    with pytest.raises(WorkerArtifactError, match="promotes authority"):
        dataclasses.replace(package, artifact_content_trusted=True)
    with pytest.raises(WorkerArtifactError, match="payload binding"):
        dataclasses.replace(
            result, _artifact_payloads=(("result.txt", b"forged"),)
        )


@pytest.mark.parametrize(
    "content,category",
    (
        (
            _runtime_bytes(
                b"-----BEGIN ", b"PRIVATE", b" KEY-----\nnot-a-real-key\n"
            ),
            "private_key_material",
        ),
        (b"api_key=abcdefghijk12345\n", "credential_assignment"),
        (b"token=ghp_abcdefghijklmnopqrstuvwxyz\n", "github_token"),
        (
            _runtime_bytes(
                b"aws_", b"access_key_id=", b"AK", b"IAABCDEFGHIJKLMNOP\n"
            ),
            "aws_access_key",
        ),
        (b"Authorization: Bearer abcdefghijklmnop\n", "authorization_bearer"),
    ),
)
def test_secret_material_is_rejected_without_leaking_value(
    tmp_path, monkeypatch, content, category,
):
    receipt, root = _stage(
        tmp_path, monkeypatch, {"worker-output.txt": content}
    )
    result = intake_worker_artifacts(receipt, root)
    serialized = result.receipt.canonical_bytes()

    assert result.receipt.status == "rejected_secret_material"
    assert result.receipt.scan_passed is False
    assert result.receipt.suspicious_secret_material_detected is True
    assert result.quarantine_package is None
    assert result._artifact_payloads == ()
    assert category in {
        finding.category for finding in result.receipt.findings
    }
    assert content.strip() not in serialized


def test_sensitive_filename_is_rejected(tmp_path, monkeypatch):
    receipt, root = _stage(
        tmp_path, monkeypatch, {"config/credentials.json": b"{}"}
    )
    result = intake_worker_artifacts(receipt, root)
    assert result.receipt.scan_passed is False
    assert result.receipt.findings[0].category == "sensitive_filename"


def test_quarantine_and_receipts_are_immutable_and_bounded(
    tmp_path, monkeypatch,
):
    receipt, root = _stage(tmp_path, monkeypatch)
    result = intake_worker_artifacts(receipt, root)
    with pytest.raises(FrozenInstanceError):
        result.receipt.status = "trusted"
    with pytest.raises(FrozenInstanceError):
        result.quarantine_package.inventory = ()
    assert len(result.receipt.canonical_bytes()) <= (
        worker_artifact.MAX_RECEIPT_BYTES
    )
    assert len(result.quarantine_package.canonical_bytes()) <= (
        worker_artifact.MAX_RECEIPT_BYTES
    )


def test_uncertain_cleanup_remains_explicit(tmp_path, monkeypatch):
    original = worker_runtime._remove_workspace

    def remove_but_report_uncertain(path):
        original(path)
        return False

    monkeypatch.setattr(
        worker_runtime, "_remove_workspace", remove_but_report_uncertain
    )
    receipt, _ = _execute(tmp_path, monkeypatch)
    assert receipt.cleanup_confirmed is False
    receipt, root = _stage(tmp_path, monkeypatch, receipt=receipt)
    result = intake_worker_artifacts(receipt, root)
    assert result.receipt.teardown_uncertain is True
    assert result.receipt.worker_container_cleanup_confirmed is False
    assert result.receipt.execution_workspace_cleanup_confirmed is False


def test_changed_module_has_no_execution_network_or_persistence_facility():
    tree = ast.parse(
        open(worker_artifact.__file__, encoding="utf-8").read()
    )
    imported = {
        node.names[0].name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom)) and node.names
    }
    assert imported.isdisjoint({
        "subprocess", "socket", "requests", "httpx", "urllib", "docker",
        "podman", "kubernetes", "paramiko", "fabric", "pexpect",
        "sqlite3",
    })
    source = open(worker_artifact.__file__, encoding="utf-8").read()
    assert "os.system" not in source
    assert "shell=True" not in source
