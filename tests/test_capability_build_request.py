"""Focused tests for V0.4B Slice 2 offline build requests."""

import ast
import json
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from scripts.capability_build.request import (
    MAX_BEHAVIOR_SUMMARY_BYTES,
    MAX_CAPABILITY_NAME_BYTES,
    MAX_LIST_ITEM_BYTES,
    MAX_REQUEST_ID_BYTES,
    MAX_REQUEST_SUMMARY_BYTES,
    MAX_USER_GOAL_BYTES,
    STATUS_BLOCKED,
    STATUS_DRAFT,
    STATUS_READY_FOR_WORKFLOW,
    CapabilityBuildRequest,
)


def _request(**overrides):
    values = {
        "request_id": "request-001",
        "capability_name": "Project insight",
        "user_goal": "Summarize project activity offline.",
    }
    values.update(overrides)
    return CapabilityBuildRequest(**values)


def test_valid_minimal_request_is_ready_for_workflow():
    request = _request()

    assert request.schema_version == 1
    assert request.status == STATUS_READY_FOR_WORKFLOW
    assert request.ready_to_start_workflow is True
    assert request.blocking_reasons == ()
    assert request.requested_behavior_summary == ""
    assert request.constraints == ()
    assert request.non_goals == ()
    assert request.risk_notes == ()
    assert request.offline_only is True
    assert request.autonomous is False
    assert request.runtime_authority is False


@pytest.mark.parametrize(
    "field,reason",
    [
        ("request_id", "request_id is required"),
        ("capability_name", "capability_name is required"),
        ("user_goal", "user_goal is required"),
    ],
)
@pytest.mark.parametrize("missing", [None, "", "  \n\t  "])
def test_missing_required_fields_block(field, reason, missing):
    request = _request(**{field: missing})

    assert request.status == STATUS_BLOCKED
    assert request.ready_to_start_workflow is False
    assert any(reason in item for item in request.blocking_reasons)


@pytest.mark.parametrize(
    "field,maximum",
    [
        ("request_id", MAX_REQUEST_ID_BYTES),
        ("capability_name", MAX_CAPABILITY_NAME_BYTES),
        ("user_goal", MAX_USER_GOAL_BYTES),
        ("requested_behavior_summary", MAX_BEHAVIOR_SUMMARY_BYTES),
    ],
)
def test_overlong_fields_block_and_are_not_retained(field, maximum):
    request = _request(**{field: "x" * (maximum + 1)})

    assert request.status == STATUS_BLOCKED
    assert getattr(request, field) == ""
    assert any("exceeds" in item for item in request.blocking_reasons)
    assert "x" * (maximum + 1) not in request.summary()


def test_overlong_list_item_blocks_and_is_not_retained():
    request = _request(
        constraints=("x" * (MAX_LIST_ITEM_BYTES + 1),)
    )

    assert request.status == STATUS_BLOCKED
    assert request.constraints == ()
    assert "exceeds" in request.blocking_reasons[0]


def test_unicode_is_nfc_normalized_and_whitespace_is_collapsed():
    request = _request(
        capability_name="  Cafe\u0301   summary  ",
        user_goal="  Review\tproject\nactivity   offline.  ",
    )

    assert request.capability_name == "Café summary"
    assert request.user_goal == "Review project activity offline."
    assert request.status == STATUS_READY_FOR_WORKFLOW


def test_control_characters_are_removed_from_human_text():
    request = _request(
        user_goal="Review\x00project\x07activity\u0085offline."
    )

    assert request.user_goal == "Review project activity offline."
    assert all(
        ord(character) >= 32 for character in request.user_goal
    )


def test_to_dict_and_summary_are_deterministic():
    first = _request(
        constraints=("Keep offline.", "Use bounded data."),
        non_goals=("No deployment.", "No registry writes."),
        risk_notes=("Human review required.", "Generated code risk."),
    )
    second = _request(
        constraints=("Use bounded data.", "Keep offline."),
        non_goals=("No registry writes.", "No deployment."),
        risk_notes=("Generated code risk.", "Human review required."),
    )

    assert first == second
    assert first.to_dict() == second.to_dict()
    assert first.summary() == second.summary()
    assert json.loads(first.summary()) == first.to_dict()


def test_request_is_immutable():
    request = _request()

    with pytest.raises(FrozenInstanceError):
        request.status = STATUS_BLOCKED
    with pytest.raises(FrozenInstanceError):
        request.user_goal = "Changed"


def test_requester_decision_keeps_safe_request_in_draft():
    request = _request(requester_decision_required=True)

    assert request.status == STATUS_DRAFT
    assert request.ready_to_start_workflow is False
    assert request.blocking_reasons == ()


def test_constraints_non_goals_and_risk_notes_are_stable_tuples():
    request = _request(
        constraints=["Zulu", "alpha", "Zulu"],
        non_goals=["No merge", "No deploy"],
        risk_notes=["Review", "Audit"],
    )

    assert request.constraints == ("alpha", "Zulu")
    assert request.non_goals == ("No deploy", "No merge")
    assert request.risk_notes == ("Audit", "Review")


@pytest.mark.parametrize(
    "unsafe,expected_reason",
    [
        (
            "Perform autonomous deployment after tests.",
            "autonomous deployment authority",
        ),
        (
            "Write directly to registry at runtime.",
            "direct registry or runtime writes",
        ),
        (
            "Request direct registry/runtime writes.",
            "direct registry or runtime writes",
        ),
        ("Let the capability install itself.", "self-installation"),
        ("Grant arbitrary shell access.", "shell or root access"),
        ("Grant arbitrary shell/root access.", "shell or root access"),
        ("Exfiltrate secrets to the worker.", "secret exfiltration"),
        ("Bypass human approval.", "bypass human approval"),
        (
            "Use direct GitHub merge automation.",
            "direct GitHub PR or merge automation",
        ),
    ],
)
def test_unsafe_authority_requests_are_blocked_with_stable_reasons(
    unsafe, expected_reason
):
    first = _request(requested_behavior_summary=unsafe)
    second = _request(requested_behavior_summary=unsafe)

    assert first.status == STATUS_BLOCKED
    assert first.ready_to_start_workflow is False
    assert first.blocking_reasons == second.blocking_reasons
    assert any(
        expected_reason in reason for reason in first.blocking_reasons
    )


def test_negated_non_goals_do_not_request_unsafe_authority():
    request = _request(
        constraints=("Do not bypass human approval.",),
        non_goals=(
            "No autonomous deployment.",
            "Never exfiltrate secrets.",
        ),
    )

    assert request.status == STATUS_READY_FOR_WORKFLOW
    assert request.blocking_reasons == ()


def test_secret_like_material_is_blocked_and_omitted():
    fake_key = "sk-" + "abcdefghijklmnopqrstuv"
    request = _request(risk_notes=("Observed " + fake_key,))

    assert request.status == STATUS_BLOCKED
    assert request.risk_notes == ()
    assert fake_key not in request.summary()
    assert any("secret-like" in item for item in request.blocking_reasons)


def test_named_long_credential_is_blocked_without_literal_fixture():
    credential = "correct-horse-" + "battery-staple"
    request = _request(
        risk_notes=("password = " + credential,)
    )

    assert request.status == STATUS_BLOCKED
    assert request.risk_notes == ()
    assert credential not in request.summary()


def test_summary_is_bounded_and_has_no_raw_operational_fields():
    request = _request(
        requested_behavior_summary="Return a bounded project rollup.",
        constraints=("Offline only.",),
    )
    summary = request.summary()
    payload = json.loads(summary)

    assert len(summary.encode("utf-8")) <= MAX_REQUEST_SUMMARY_BYTES
    assert payload["authority"] == {
        "autonomous": False,
        "offline_only": True,
        "runtime_authority": False,
    }
    forbidden_keys = {
        "prompt",
        "raw_prompt",
        "secret",
        "secrets",
        "argv",
        "worker_prose",
        "worker_report",
        "returned_content",
        "output_excerpt",
        "environment",
    }
    assert not forbidden_keys & set(payload)


def test_request_module_has_no_creation_or_external_authority():
    source_path = (
        Path(__file__).parents[1]
        / "scripts"
        / "capability_build"
        / "request.py"
    )
    source = source_path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    forbidden_imports = {
        "backend",
        "git",
        "github",
        "httpx",
        "os",
        "pathlib",
        "pygit2",
        "requests",
        "shutil",
        "subprocess",
    }
    forbidden_calls = {
        "compile",
        "eval",
        "exec",
        "open",
        "read_text",
        "read_bytes",
        "write_text",
        "write_bytes",
        "mkdir",
        "unlink",
        "remove",
        "rename",
        "replace",
        "run",
        "Popen",
        "system",
        "__import__",
    }
    forbidden_creation_names = {
        "new_job",
        "new_workflow",
        "record_workflow_step",
        "freeze_scope",
        "render_worker_brief",
        "validate_returned_files",
        "evaluate_evidence",
        "build_review_bundle",
        "build_human_handoff",
        "create_pr",
        "open_pr",
        "register",
        "install",
        "deploy",
        "dispatch_worker",
        "execute",
    }
    imports = []
    calls = []
    definitions = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imports.append(node.module or "")
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            definitions.append(node.name)
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                calls.append(node.func.id)
            elif isinstance(node.func, ast.Attribute):
                calls.append(node.func.attr)

    assert not any(
        imported.split(".")[0] in forbidden_imports
        for imported in imports
    )
    assert not forbidden_calls & set(calls)
    assert not forbidden_creation_names & set(definitions)
    assert not forbidden_creation_names & set(calls)
    assert "backend.tool_registry" not in source
