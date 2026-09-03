"""Tests for V0.4D mission audit receipts."""

import ast
from dataclasses import FrozenInstanceError, replace
from pathlib import Path

import pytest

from backend.composition_receipt import (
    STATUS_COMPLETED,
    STATUS_REJECTED,
    CompositionReceiptError,
    create_composition_mission_receipt,
)
from backend.composition_runtime import (
    STATUS_APPROVAL_PENDING,
    run_composition_mission,
)
from backend.db import DATABASE_PATH
from backend.memory import init_db
from backend.tool_operations import approve_operation, reject_operation
from backend.tool_registry import reset_tool_registry
from backend.tasks import list_tasks
from v04d_composition_helpers import build_fake_registry, build_plan


@pytest.fixture
def clean_db():
    if DATABASE_PATH.exists():
        DATABASE_PATH.unlink()
    init_db()
    reset_tool_registry()
    yield
    reset_tool_registry()
    if DATABASE_PATH.exists():
        DATABASE_PATH.unlink()


def _runtime():
    registry = build_fake_registry()
    return run_composition_mission(build_plan(registry), registry)


def test_pending_receipt_binds_reads_budget_data_flow_and_operation(clean_db):
    runtime = _runtime()
    receipt = create_composition_mission_receipt(runtime)

    assert receipt.status == STATUS_APPROVAL_PENDING
    assert receipt.operation_id == runtime.pending_operation_id
    assert receipt.operation_status == "pending"
    assert len(receipt.read_run_ids) == 4
    assert receipt.runtime.processed_requests == 5
    assert receipt.runtime.executed_requests == 4
    assert receipt.write_executed is False
    assert receipt.automatic_approval_performed is False
    assert receipt.mission_persisted is False


def test_receipt_observes_independently_approved_frozen_write(clean_db):
    runtime = _runtime()
    assert list_tasks(status="open", project="MootOS") == []

    operation = approve_operation(runtime.pending_operation_id)
    receipt = create_composition_mission_receipt(runtime)

    assert operation["status"] == "succeeded"
    assert receipt.status == STATUS_COMPLETED
    assert receipt.write_executed is True
    assert receipt.terminal_write_run_id == operation["result_run_id"]
    assert receipt.terminal_result_reference == operation["result_reference"]
    assert len(list_tasks(status="open", project="MootOS")) == 1
    assert receipt.automatic_approval_performed is False


def test_receipt_observes_independent_rejection_without_execution(clean_db):
    runtime = _runtime()
    operation = reject_operation(runtime.pending_operation_id)
    receipt = create_composition_mission_receipt(runtime)

    assert operation["status"] == "rejected"
    assert receipt.status == STATUS_REJECTED
    assert receipt.write_executed is False
    assert receipt.terminal_write_run_id == ""
    assert list_tasks(status="open", project="MootOS") == []


def test_missing_or_mismatched_operation_fails_closed(clean_db, monkeypatch):
    runtime = _runtime()
    monkeypatch.setattr(
        "backend.composition_receipt.get_operation", lambda identifier: None
    )
    with pytest.raises(CompositionReceiptError, match="missing"):
        create_composition_mission_receipt(runtime)

    monkeypatch.setattr(
        "backend.composition_receipt.get_operation",
        lambda identifier: {
            "id": identifier,
            "tool_name": "tasks.create",
            "tool_version": "1",
            "arguments": {"title": "forged"},
            "project": "MootOS",
            "status": "pending",
        },
    )
    with pytest.raises(CompositionReceiptError, match="differs"):
        create_composition_mission_receipt(runtime)


def test_missing_or_mismatched_read_run_fails_closed(clean_db, monkeypatch):
    runtime = _runtime()
    monkeypatch.setattr(
        "backend.composition_receipt.get_run", lambda identifier: None
    )
    with pytest.raises(CompositionReceiptError, match="Run is missing"):
        create_composition_mission_receipt(runtime)


def test_receipt_is_immutable_bounded_deterministic_and_sanitized(clean_db):
    runtime = _runtime()
    first = create_composition_mission_receipt(runtime)
    second = create_composition_mission_receipt(runtime)
    serialized = first.summary()

    assert first == second
    assert serialized == second.summary()
    assert len(serialized.encode("utf-8")) <= 128 * 1024
    assert "Existing" not in serialized
    assert "password" not in serialized.lower()
    with pytest.raises(FrozenInstanceError):
        first.status = STATUS_COMPLETED
    with pytest.raises(CompositionReceiptError, match="plan binding"):
        replace(first, plan_sha256="0" * 64)


def test_receipt_module_has_read_only_audit_authority():
    path = Path(__file__).parents[1] / "backend/composition_receipt.py"
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    calls = {
        getattr(node.func, "id", getattr(node.func, "attr", ""))
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
    }
    assert "approve_operation" not in source
    assert "reject_operation" not in source
    assert "execute_tool" not in source
    assert "create_pending_operation" not in source
    assert not calls & {"open", "run", "Popen", "request", "post"}
