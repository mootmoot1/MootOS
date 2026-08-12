"""Tests for V0.4A Slice 1's inert BuildJob state machine."""

import ast
import inspect
import json
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

import scripts.capability_build.job as job_module
from scripts.capability_build.job import (
    BUILD_JOB_STATES,
    FORWARD_STATES,
    MAX_FIX_ROUNDS,
    RETRY_BLOCKING_FINDING,
    RETRY_VERIFICATION_FAILURE,
    STATE_DISPATCHED,
    STATE_DRAFTED,
    STATE_NEEDS_HUMAN,
    STATE_READY_FOR_PR,
    STATE_REVIEWED,
    STATE_VALIDATED,
    STATE_VERIFIED,
    TERMINAL_STATES,
    BuildBudgets,
    BuildJob,
    BuildJobError,
    load_job,
    new_job,
    retry,
    save_job,
    transition,
)


SPEC_SHA256 = "a" * 64
BASE_SHA = "5ef7a63"


def _new_job():
    return new_job(
        "fake.capability",
        SPEC_SHA256,
        BASE_SHA,
        actor="human:tester",
        note="Create the approved build job",
        job_id="job-test-1",
    )


def _advance_to(target):
    job = _new_job()
    for state in FORWARD_STATES[1:]:
        if job.state == target:
            break
        job = transition(
            job,
            state,
            actor="mootos:builder",
            note=f"Advance to {state}",
        )
    return job


def _first_retry():
    job = _advance_to(STATE_VERIFIED)
    return retry(
        job,
        reason=RETRY_VERIFICATION_FAILURE,
        actor="mootos:builder",
        note="Verification failed",
    )


def _second_retry():
    job = _first_retry()
    for state in FORWARD_STATES[2:5]:
        job = transition(
            job,
            state,
            actor="mootos:builder",
            note=f"Advance to {state}",
        )
    return retry(
        job,
        reason=RETRY_VERIFICATION_FAILURE,
        actor="mootos:builder",
        note="Verification failed again",
    )


def test_full_forward_path_succeeds_one_step_at_a_time():
    original = _new_job()
    job = original

    for state in FORWARD_STATES[1:]:
        job = transition(
            job,
            state,
            actor="mootos:builder",
            note=f"Advance to {state}",
        )

    assert original.state == STATE_DRAFTED
    assert job.state == STATE_READY_FOR_PR
    assert len(job.history) == len(FORWARD_STATES)
    assert [event.to_state for event in job.history] == list(
        FORWARD_STATES
    )


@pytest.mark.parametrize(
    "start,target",
    [
        (STATE_DRAFTED, FORWARD_STATES[2]),
        (STATE_DISPATCHED, STATE_DRAFTED),
        (STATE_VERIFIED, STATE_VERIFIED),
        (STATE_REVIEWED, FORWARD_STATES[3]),
        (STATE_READY_FOR_PR, STATE_DRAFTED),
    ],
)
def test_skipped_repeated_and_backward_transitions_raise(start, target):
    job = _advance_to(start)
    with pytest.raises(BuildJobError):
        transition(
            job,
            target,
            actor="human:tester",
            note="Attempt invalid transition",
        )


@pytest.mark.parametrize("escape_state", TERMINAL_STATES)
@pytest.mark.parametrize("start_state", FORWARD_STATES)
def test_every_non_terminal_state_can_enter_an_escape_state(
    start_state, escape_state
):
    job = _advance_to(start_state)
    escaped = transition(
        job,
        escape_state,
        actor="human:tester",
        note="Stop this job",
    )
    assert escaped.state == escape_state
    assert job.state == start_state


@pytest.mark.parametrize("terminal_state", TERMINAL_STATES)
def test_terminal_states_cannot_transition(terminal_state):
    terminal = transition(
        _new_job(),
        terminal_state,
        actor="human:tester",
        note="Stop",
    )
    for target in BUILD_JOB_STATES:
        with pytest.raises(BuildJobError, match="Terminal"):
            transition(
                terminal,
                target,
                actor="human:tester",
                note="Cannot leave terminal",
            )
    with pytest.raises(BuildJobError, match="Terminal"):
        retry(
            terminal,
            reason=RETRY_VERIFICATION_FAILURE,
            actor="human:tester",
            note="Cannot retry terminal",
        )


@pytest.mark.parametrize("actor", ["", "   ", None])
@pytest.mark.parametrize("note", ["", "   ", None])
def test_creation_requires_non_blank_actor_and_note(actor, note):
    with pytest.raises(BuildJobError):
        new_job(
            "fake.capability",
            SPEC_SHA256,
            BASE_SHA,
            actor=actor,
            note=note,
        )


@pytest.mark.parametrize(
    "operation",
    [
        lambda job, actor, note: transition(
            job, STATE_DISPATCHED, actor=actor, note=note
        ),
        lambda job, actor, note: retry(
            _advance_to(STATE_VERIFIED),
            reason=RETRY_VERIFICATION_FAILURE,
            actor=actor,
            note=note,
        ),
    ],
)
@pytest.mark.parametrize("actor,note", [("", "x"), ("x", "  ")])
def test_every_state_change_requires_actor_and_note(operation, actor, note):
    with pytest.raises(BuildJobError):
        operation(_new_job(), actor, note)


def test_jobs_are_frozen_and_transitions_return_new_values():
    job = _new_job()
    advanced = transition(
        job,
        STATE_DISPATCHED,
        actor="human:tester",
        note="Dispatch",
    )

    assert advanced is not job
    assert job.state == STATE_DRAFTED
    with pytest.raises(FrozenInstanceError):
        job.state = STATE_DISPATCHED


@pytest.mark.parametrize(
    "state,reason",
    [
        (STATE_VERIFIED, RETRY_VERIFICATION_FAILURE),
        (STATE_REVIEWED, RETRY_BLOCKING_FINDING),
    ],
)
def test_only_qualifying_retry_edges_increment_fix_round(state, reason):
    job = _advance_to(state)
    retried = retry(
        job,
        reason=reason,
        actor="mootos:builder",
        note="Return for a bounded fix",
    )

    assert retried.state == STATE_DISPATCHED
    assert retried.fix_round == job.fix_round + 1 == 1
    assert retried.history[-1].retry_reason == reason
    assert all(event.fix_round == 0 for event in job.history)


def test_wrong_state_or_reason_cannot_use_the_retry_edge():
    with pytest.raises(BuildJobError):
        retry(
            _new_job(),
            reason=RETRY_VERIFICATION_FAILURE,
            actor="mootos:builder",
            note="Not verified",
        )
    with pytest.raises(BuildJobError):
        retry(
            _advance_to(STATE_VERIFIED),
            reason=RETRY_BLOCKING_FINDING,
            actor="mootos:builder",
            note="Wrong reason",
        )
    with pytest.raises(BuildJobError):
        transition(
            _advance_to(STATE_VERIFIED),
            STATE_DISPATCHED,
            actor="mootos:builder",
            note="Cannot bypass retry",
        )


def test_third_fix_round_is_impossible_and_needs_human_remains_available():
    job = _second_retry()
    assert job.fix_round == MAX_FIX_ROUNDS == 2
    for state in FORWARD_STATES[2:5]:
        job = transition(
            job,
            state,
            actor="mootos:builder",
            note=f"Advance to {state}",
        )

    with pytest.raises(BuildJobError, match="needs_human"):
        retry(
            job,
            reason=RETRY_VERIFICATION_FAILURE,
            actor="mootos:builder",
            note="Forbidden third fix round",
        )
    escalated = transition(
        job,
        STATE_NEEDS_HUMAN,
        actor="mootos:builder",
        note="Fix-round limit reached",
    )
    assert escalated.fix_round == 2
    assert escalated.state == STATE_NEEDS_HUMAN
    with pytest.raises(BuildJobError, match="fixed at 2"):
        BuildBudgets(max_fix_rounds=3)


def test_direct_impossible_verified_job_with_empty_history_fails():
    with pytest.raises(BuildJobError, match="history cannot be empty"):
        BuildJob(
            job_id="forged-job",
            capability_id="fake.capability",
            spec_sha256=SPEC_SHA256,
            base_sha=BASE_SHA,
            state=STATE_VERIFIED,
            history=(),
        )


def test_json_save_load_round_trip_and_content_hash_are_stable(tmp_path):
    job = _advance_to(STATE_VALIDATED)
    original_hash = job.content_sha256
    path = save_job(job, tmp_path / "build_jobs")
    loaded = load_job(job.job_id, tmp_path / "build_jobs")

    assert path == tmp_path / "build_jobs" / job.job_id / "job.json"
    assert loaded == job
    assert loaded.content_sha256 == original_hash
    assert json.loads(path.read_text(encoding="utf-8"))[
        "content_sha256"
    ] == original_hash
    save_job(loaded, tmp_path / "build_jobs")
    assert load_job(job.job_id, tmp_path / "build_jobs") == job


def test_corrupted_json_and_hash_mismatch_fail_to_load(tmp_path):
    root = tmp_path / "build_jobs"
    job = _new_job()
    path = save_job(job, root)
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(BuildJobError, match="cannot load BuildJob"):
        load_job(job.job_id, root)

    save_job(job, root)
    data = json.loads(path.read_text(encoding="utf-8"))
    data["state"] = STATE_DISPATCHED
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(BuildJobError, match="content hash mismatch"):
        load_job(job.job_id, root)


def test_job_module_has_no_backend_imports_or_authority_operations():
    source_path = (
        Path(__file__).parents[1]
        / "scripts"
        / "capability_build"
        / "job.py"
    )
    tree = ast.parse(source_path.read_text(encoding="utf-8"))

    imports = []
    calls = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imports.append(node.module or "")
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                calls.append(node.func.id)
            elif isinstance(node.func, ast.Attribute):
                calls.append(node.func.attr)

    assert not any(
        name == "backend" or name.startswith("backend.")
        for name in imports
    )
    process_calls = {"run", "Popen", "check_call", "check_output", "system"}
    assert not process_calls & set(calls)


def test_public_state_helpers_require_explicit_actor_and_note():
    source = inspect.getsource(job_module)
    tree = ast.parse(source)
    state_helpers = set()
    for function in tree.body:
        if not isinstance(function, ast.FunctionDef):
            continue
        direct_calls = {
            node.func.id
            for node in ast.walk(function)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
        }
        if {"BuildJobEvent", "_with_event"} & direct_calls:
            assert not function.name.startswith("_")
            state_helpers.add(function.name)

    assert state_helpers == {"new_job", "transition", "retry"}
    for name in state_helpers:
        helper = getattr(job_module, name)
        signature = inspect.signature(helper)
        assert "actor" in signature.parameters
        assert "note" in signature.parameters
        assert signature.parameters["actor"].default is inspect.Parameter.empty
        assert signature.parameters["note"].default is inspect.Parameter.empty
