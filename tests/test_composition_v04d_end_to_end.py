"""End-to-end proof of the real ADR-040 composition mission."""

from dataclasses import replace

import pytest

from backend.composition_feasibility import bind_composition_feasibility
from backend.composition_receipt import (
    STATUS_COMPLETED,
    STATUS_REJECTED,
    create_composition_mission_receipt,
)
from backend.composition_runtime import (
    STATUS_APPROVAL_PENDING,
    STATUS_FAILED,
    run_composition_mission,
)
from backend.db import DATABASE_PATH
from backend.memory import create_memory, init_db
from backend.tasks import create_task, list_tasks
from backend.tool_operations import approve_operation, reject_operation
from backend.tool_registry import build_default_registry, reset_tool_registry
from v04d_composition_helpers import (
    build_fake_registry,
    build_plan,
    build_proposal,
)


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


def _seed_real_mission_state():
    create_task("Review architecture", project="MootOS")
    create_task("Check release gates", project="MootOS")
    create_task("Prepare session", project="Studio")
    create_memory(
        "MootOS release context and architecture notes.",
        project="MootOS",
    )


def _run_real_mission():
    registry = build_default_registry()
    proposal = build_proposal("mission-v04d-real-proof")
    plan = bind_composition_feasibility(proposal, registry)
    return run_composition_mission(plan, registry)


def test_real_chain_composes_four_reads_into_one_frozen_write(clean_db):
    _seed_real_mission_state()
    before = list_tasks(status="open", project="MootOS")

    runtime = _run_real_mission()
    receipt = create_composition_mission_receipt(runtime)
    after = list_tasks(status="open", project="MootOS")

    assert runtime.status == STATUS_APPROVAL_PENDING
    assert receipt.status == STATUS_APPROVAL_PENDING
    assert runtime.selected_project == "MootOS"
    assert runtime.open_task_count == len(before) == 2
    assert runtime.listed_open_task_count == len(before)
    assert runtime.memory_match_count == 1
    assert runtime.processed_requests == 5
    assert runtime.executed_requests == 4
    assert len(runtime.request_signatures) == 5
    assert len(receipt.read_run_ids) == 4
    assert receipt.operation_id == runtime.pending_operation_id
    assert after == before
    assert runtime.write_executed is False
    assert receipt.write_executed is False
    assert receipt.automatic_approval_performed is False


def test_exact_frozen_write_executes_only_after_independent_approval(clean_db):
    _seed_real_mission_state()
    runtime = _run_real_mission()
    assert len(list_tasks(status="open", project="MootOS")) == 2

    operation = approve_operation(runtime.pending_operation_id)
    receipt = create_composition_mission_receipt(runtime)
    tasks = list_tasks(status="open", project="MootOS")

    assert operation["status"] == "succeeded"
    assert receipt.status == STATUS_COMPLETED
    assert receipt.write_executed is True
    assert receipt.terminal_write_run_id == operation["result_run_id"]
    assert len(tasks) == 3
    assert tasks[0]["title"] == (
        "Follow up on MootOS: review 2 open tasks"
    )
    assert receipt.automatic_approval_performed is False
    assert receipt.generalized_resume_supported is False


def test_independent_rejection_never_executes_the_frozen_write(clean_db):
    _seed_real_mission_state()
    runtime = _run_real_mission()

    operation = reject_operation(runtime.pending_operation_id)
    receipt = create_composition_mission_receipt(runtime)

    assert operation["status"] == "rejected"
    assert receipt.status == STATUS_REJECTED
    assert receipt.write_executed is False
    assert len(list_tasks(status="open", project="MootOS")) == 2


def test_material_summary_list_disagreement_terminates_before_write(clean_db):
    registry = build_fake_registry(summary_count=3, listed_count=2)
    runtime = run_composition_mission(build_plan(registry), registry)

    assert runtime.status == STATUS_FAILED
    assert runtime.processed_requests == 3
    assert runtime.executed_requests == 3
    assert runtime.pending_operation_id == ""
    assert runtime.step_runs[2].status == "failed"
    assert all(
        step.status == "not_attempted" for step in runtime.step_runs[3:]
    )


def test_changed_registry_snapshot_blocks_without_replanning(clean_db):
    registry = build_fake_registry()
    plan = build_plan(registry)
    definition = registry.get("tasks.status_summary")
    registry._tools[definition.name] = replace(definition, version="2")

    runtime = run_composition_mission(plan, registry)

    assert runtime.processed_requests == 0
    assert runtime.executed_requests == 0
    assert runtime.pending_operation_id == ""
    assert runtime.failure_class == "RegistryMismatch"
