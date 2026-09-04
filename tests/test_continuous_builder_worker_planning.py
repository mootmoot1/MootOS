import ast
import hashlib
import json
import sqlite3
from dataclasses import FrozenInstanceError, replace
from pathlib import Path

import pytest

from backend.continuous_builder.blueprint import (
    BuildBudget, ContinuousBuilderBlueprint, RollbackContract,
    SliceBlueprint, SystemBlueprint,
)
from backend.continuous_builder.blueprint_parser import parse_blueprint
from backend.continuous_builder.blueprint_store import store_blueprint
from backend.continuous_builder.chief_builder import (
    BlueprintApprovalEvidence, create_planning_receipt,
)
from backend.continuous_builder.conflict_analysis import (
    EligibilityResources, analyze_conflicts,
)
from backend.continuous_builder.dependency_analysis import analyze_dependencies
from backend.continuous_builder.leases import acquire_lease, create_attempt
from backend.continuous_builder.priority_policy import rank_eligible_slices
from backend.continuous_builder.queue_proposal import propose_candidates
from backend.continuous_builder.queue_store import (
    PRIMARY, QueueEventInput, append_event, dependency_snapshot_digest,
)
from backend.continuous_builder.readiness_bridge import (
    derive_dependency_receipts,
)
from backend.continuous_builder.worker_authorization import (
    DispatchAuthorizationInput,
)
from backend.continuous_builder.worker_planning import (
    WorkerPlanningError, plan_inert_worker_action,
)
from backend.continuous_builder.worker_provider import WorkerDescriptor
from backend.migrations import run_migrations
from scripts.capability_build.brief import render_worker_brief
from scripts.capability_build.bundle import BuildMetadata, READINESS_READY
from scripts.capability_build.handoff import (
    HUMAN_REVIEW_CHECKLIST, HandoffDecisionOption, HumanHandoffPackage,
)
from scripts.capability_build.job import new_job
from scripts.capability_build.scope import FrozenScope


T0 = "2026-01-01T00:00:00+00:00"
T1 = "2026-01-01T01:00:00+00:00"
OBSERVED = "2026-01-01T00:30:00+00:00"
BASE = "a" * 40


def _slice(slice_id, **changes):
    values = {
        "slice_id": slice_id, "version": "1", "system_id": "builder",
        "objective": "Implement bounded inert worker contracts.",
        "acceptance_criteria": ("Focused tests pass.",),
        "hard_dependencies": (), "soft_dependencies": (),
        "requested_capabilities": ("python",), "expected_risk": "low",
        "allowed_paths": ("backend/continuous_builder/worker_planning.py",),
        "forbidden_paths": ("data/**",),
        "required_tests": ("pytest worker planning",),
        "required_gates": ("protected paths",),
        "budget": BuildBudget(1, 0, 30, 65536),
        "rollback": RollbackContract("revert commit", ("tests pass",)),
        "human_checkpoints": ("before launch",),
        "non_goals": ("no worker execution",),
        "priority_class": "critical" if slice_id == "CB-018" else "low",
        "authority_classes": (),
    }
    values.update(changes)
    return SliceBlueprint(**values)


def _append_states(path, parsed, item, states):
    sequence, digest = 0, None
    for index, state in enumerate(states):
        connection = sqlite3.connect(path)
        connection.row_factory = sqlite3.Row
        dependency_digest = dependency_snapshot_digest(
            connection, parsed.blueprint.blueprint_id,
            parsed.blueprint.blueprint_version, item.slice_id,
        )
        connection.close()
        event = QueueEventInput(
            f"event-{item.slice_id}-{index}", parsed.blueprint.blueprint_id,
            parsed.blueprint.blueprint_version, parsed.content_sha256,
            item.slice_id, item.version, state, "advance fixture",
            "human:tester", False, dependency_digest, "adr-043-v1", T0,
        )
        sequence, digest = append_event(path, event, sequence, digest)


def _handoff(job, item, scope):
    metadata = BuildMetadata(
        job.job_id, job.capability_id, job.state, job.fix_round,
        job.base_sha, job.spec_sha256,
    )
    options = (
        HandoffDecisionOption(
            "approve_for_pr", True,
            "Available because every handoff precondition is satisfied.",
        ),
        HandoffDecisionOption(
            "request_changes", True,
            "Return the package for bounded human-requested changes.",
        ),
        HandoffDecisionOption(
            "reject", True,
            "Reject the package without creating or merging a PR.",
        ),
    )
    return HumanHandoffPackage(
        READINESS_READY, metadata, scope.allowed_new_files, True, False,
        True, True, True, True, "passed", True, (),
        HUMAN_REVIEW_CHECKLIST, options,
    )


def _prepared(tmp_path, forged_receipt=False):
    path = tmp_path / "phase3.db"
    run_migrations(path)
    dependency = _slice("CB-013", priority_class="low")
    selected = _slice("CB-018", hard_dependencies=("CB-013",))
    blueprint = ContinuousBuilderBlueprint(
        "1", "continuous-builder", "phase-3", BASE,
        "Prepare one inert worker action.",
        (SystemBlueprint("builder", "Builder", "Offline Phase 3."),),
        (dependency, selected),
    )
    parsed = parse_blueprint(blueprint.canonical_bytes())
    approval = BlueprintApprovalEvidence(
        "approval-3", parsed.content_sha256, "human:architect", True,
    )
    store_blueprint(path, parsed, approval, T0)
    _append_states(path, parsed, dependency, PRIMARY)
    _append_states(path, parsed, selected, PRIMARY[:5])
    durable_receipts = derive_dependency_receipts(
        path, blueprint.blueprint_id, blueprint.blueprint_version,
        selected.slice_id,
    )
    receipts = durable_receipts
    if forged_receipt:
        receipts = (replace(durable_receipts[0], receipt_id="forged"),)
    candidates = propose_candidates(parsed)
    dependencies = analyze_dependencies(parsed, candidates, receipts)
    conflicts = analyze_conflicts(
        dependencies, EligibilityResources(("python",), ()),
    )
    planning = create_planning_receipt(
        rank_eligible_slices(conflicts), approval,
    )
    create_attempt(
        path, "attempt-3", blueprint.blueprint_id,
        blueprint.blueprint_version, selected.slice_id, selected.version,
        "worker-1", T0,
    )
    acquire_lease(
        path, "lease-3", "attempt-3", selected.slice_id, "worker-1", T0, T1,
    )
    slice_digest = hashlib.sha256(json.dumps(
        selected.to_dict(), ensure_ascii=False, sort_keys=True,
        separators=(",", ":"),
    ).encode()).hexdigest()
    job = new_job(
        "python", slice_digest, BASE, actor="human:tester", note="draft",
        job_id="phase3-worker-job",
    )
    allowed = selected.allowed_paths[0]
    scope = FrozenScope(
        allowed_new_files=(allowed,), justifications={allowed: "Frozen."},
    )
    handoff = _handoff(job, selected, scope)
    brief = render_worker_brief(job, scope, selected.objective)
    worker = WorkerDescriptor(
        "provider-1", "worker-1", "model-neutral",
        ("bounded_code_change",), ("python",), 65536, 65536, "available",
    )
    authorization = DispatchAuthorizationInput(
        "authorization-3", "human:dispatcher", True, "e" * 64, True,
    )
    return {
        "database_path": path, "planning_receipt": planning,
        "selected_slice_id": "CB-018", "lease_id": "lease-3",
        "observed_at": OBSERVED, "descriptors": (worker,), "job": job,
        "frozen_scope": scope, "handoff": handoff,
        "worker_brief": brief, "authorization_input": authorization,
    }


def test_offline_chain_prepares_inert_action_without_queue_change(tmp_path):
    inputs = _prepared(tmp_path)
    before = inputs["planning_receipt"].canonical_bytes()
    connection = sqlite3.connect(inputs["database_path"])
    event_count = connection.execute(
        "SELECT COUNT(*) FROM builder_events"
    ).fetchone()[0]
    connection.close()
    result = plan_inert_worker_action(**inputs)
    assert result.worker_match.status == "matched"
    assert result.worker_request.attempt_id == "attempt-3"
    assert result.dispatch_authorization.authorized is True
    assert result.launch_action.action_prepared is True
    assert result.launch_action.executed is False
    assert result.worker_launched is False
    assert result.queue_transition_performed is False
    assert result.planning_receipt.canonical_bytes() == before
    connection = sqlite3.connect(inputs["database_path"])
    assert connection.execute(
        "SELECT COUNT(*) FROM builder_events"
    ).fetchone()[0] == event_count
    connection.close()


def test_bare_authoritative_receipt_cannot_replace_durable_evidence(tmp_path):
    inputs = _prepared(tmp_path, forged_receipt=True)
    with pytest.raises(WorkerPlanningError, match="not durable"):
        plan_inert_worker_action(**inputs)


def test_stale_lease_attempt_plan_or_worker_fails_closed(tmp_path):
    inputs = _prepared(tmp_path)
    for changes in (
        {"lease_id": "missing"},
        {"observed_at": "2026-01-01T02:00:00+00:00"},
        {"descriptors": (replace(
            inputs["descriptors"][0], worker_id="worker-other"
        ),)},
    ):
        with pytest.raises(Exception):
            plan_inert_worker_action(**{**inputs, **changes})


def test_planning_result_rejects_forgery_and_is_immutable(tmp_path):
    result = plan_inert_worker_action(**_prepared(tmp_path))
    with pytest.raises(FrozenInstanceError):
        result.worker_launched = True
    for name, value in (
        ("result_digest", "0" * 64), ("execution_performed", True),
        ("queue_transition_performed", True),
    ):
        with pytest.raises(WorkerPlanningError):
            replace(result, **{name: value})


def test_adapter_has_no_process_network_github_or_credential_facility():
    source = Path(
        "backend/continuous_builder/worker_planning.py"
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
        "subprocess", "socket", "requests", "httpx", "github", "git",
        "docker", "os", "shutil",
    }
    assert "credential" not in source.casefold()
