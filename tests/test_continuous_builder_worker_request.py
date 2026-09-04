import hashlib
import json
from dataclasses import FrozenInstanceError, replace

import pytest

from backend.continuous_builder.blueprint import (
    BuildBudget, ContinuousBuilderBlueprint, RollbackContract,
    SliceBlueprint, SystemBlueprint,
)
from backend.continuous_builder.blueprint_parser import parse_blueprint
from backend.continuous_builder.worker_request import (
    WorkerRequestError, create_frozen_worker_request,
)
from scripts.capability_build.brief import render_worker_brief
from scripts.capability_build.bundle import BuildMetadata, READINESS_READY
from scripts.capability_build.handoff import (
    HUMAN_REVIEW_CHECKLIST, HandoffDecisionOption, HumanHandoffPackage,
)
from scripts.capability_build.job import new_job
from scripts.capability_build.scope import FrozenScope


BASE = "a" * 40


def _sources(path="backend/widget.py", capability="python"):
    slice_value = SliceBlueprint(
        slice_id="CB-015", version="1", system_id="builder",
        objective="Implement one bounded worker contract.",
        acceptance_criteria=("Focused tests pass.",),
        hard_dependencies=(), soft_dependencies=(),
        requested_capabilities=(capability,), expected_risk="low",
        allowed_paths=(path,), forbidden_paths=("data/**",),
        required_tests=("pytest focused",), required_gates=("lint",),
        budget=BuildBudget(1, 0, 30, 65536),
        rollback=RollbackContract("revert commit", ("tests pass",)),
        human_checkpoints=("dispatch",), non_goals=("no execution",),
        authority_classes=(),
    )
    blueprint = ContinuousBuilderBlueprint(
        "1", "blueprint-3", "1", BASE, "Build safely.",
        (SystemBlueprint("builder", "Builder", "Inert contracts."),),
        (slice_value,),
    )
    parsed = parse_blueprint(blueprint.canonical_bytes())
    slice_digest = hashlib.sha256(json.dumps(
        slice_value.to_dict(), ensure_ascii=False, sort_keys=True,
        separators=(",", ":"),
    ).encode()).hexdigest()
    job = new_job(
        capability, slice_digest, BASE, actor="human:tester", note="draft",
        job_id="worker-job",
    )
    scope = FrozenScope(
        allowed_new_files=(path,), justifications={path: "Approved scope."},
    )
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
    handoff = HumanHandoffPackage(
        READINESS_READY, metadata, (path,), True, False, True, True, True,
        True,
        "passed", True, (), HUMAN_REVIEW_CHECKLIST, options,
    )
    brief = render_worker_brief(job, scope, slice_value.objective)
    return parsed, slice_value, job, scope, handoff, brief


def _request(**changes):
    sources = _sources()
    values = {
        "parsed_blueprint": sources[0], "slice_blueprint": sources[1],
        "job": sources[2], "frozen_scope": sources[3],
        "handoff": sources[4], "worker_brief": sources[5],
        "attempt_id": "attempt-1", "requested_capability": "python",
    }
    values.update(changes)
    return create_frozen_worker_request(**values)


def test_frozen_request_exactly_binds_sources_and_is_deterministic():
    sources = _sources()
    arguments = {
        "parsed_blueprint": sources[0], "slice_blueprint": sources[1],
        "job": sources[2], "frozen_scope": sources[3],
        "handoff": sources[4], "worker_brief": sources[5],
        "attempt_id": "attempt-1", "requested_capability": "python",
    }
    first = create_frozen_worker_request(**arguments)
    second = create_frozen_worker_request(**arguments)
    assert first == second
    assert first.request_digest == second.request_digest
    assert first.blueprint_digest == first.parsed_blueprint.content_sha256
    assert first.job_digest == first.job.content_sha256
    assert first.execution_authorized is False
    assert len(first.canonical_bytes()) < 256 * 1024


def test_request_is_immutable_and_bound_mutations_fail():
    request = _request()
    with pytest.raises(FrozenInstanceError):
        request.attempt_id = "other"
    for name, value in (
        ("blueprint_digest", "0" * 64), ("slice_digest", "0" * 64),
        ("job_digest", "0" * 64), ("scope_digest", "0" * 64),
        ("handoff_digest", "0" * 64), ("brief_digest", "0" * 64),
        ("request_digest", "0" * 64),
    ):
        with pytest.raises(WorkerRequestError):
            replace(request, **{name: value})


def test_stale_base_handoff_and_capability_fail_closed():
    parsed, item, job, scope, handoff, brief = _sources()
    stale_handoff = replace(
        handoff, job=replace(handoff.job, base_sha="b" * 40),
    )
    with pytest.raises(WorkerRequestError, match="handoff"):
        create_frozen_worker_request(
            parsed, item, job, scope, stale_handoff, brief,
            "attempt-1", "python",
        )
    with pytest.raises(WorkerRequestError, match="capability"):
        create_frozen_worker_request(
            parsed, item, job, scope, handoff, brief, "attempt-1", "other",
        )


def test_scope_growth_and_malformed_brief_rejected():
    parsed, item, job, _, handoff, brief = _sources()
    expanded = FrozenScope(
        allowed_new_files=("backend/other.py",),
        justifications={"backend/other.py": "Not in slice."},
    )
    with pytest.raises(WorkerRequestError, match="scope grows"):
        create_frozen_worker_request(
            parsed, item, job, expanded, handoff, brief, "attempt-1", "python",
        )
    with pytest.raises(WorkerRequestError):
        _request(worker_brief="\ud800")


def test_request_serialization_contains_no_credentials_or_commands():
    payload = _request().canonical_bytes().decode()
    assert '"credentials_present":false' in payload
    assert '"shell_authorized":false' in payload
    assert "worker_brief" not in payload
    with pytest.raises(WorkerRequestError):
        replace(_request(), credentials_present=True)
