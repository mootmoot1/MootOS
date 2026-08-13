"""Tests for V0.4B Slice 4 pure BuildJob binding input."""

import ast
import json
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from scripts.capability_build.job_binding import (
    MAX_ACTOR_BYTES,
    MAX_BINDING_SUMMARY_BYTES,
    MAX_CAPABILITY_ID_BYTES,
    MAX_JOB_ID_BYTES,
    MAX_NOTE_BYTES,
    STATUS_BLOCKED,
    STATUS_READY_FOR_JOB_CREATION,
    BuildJobBinding,
)


SPEC_SHA256 = "a" * 64
BASE_SHA = "b" * 40


def _binding(**overrides):
    values = {
        "job_id": "job-v04b-slice-4",
        "capability_id": "projects.insight",
        "spec_sha256": SPEC_SHA256,
        "base_sha": BASE_SHA,
        "actor": "human:tester",
        "note": "Create the approved offline build job.",
    }
    values.update(overrides)
    return BuildJobBinding(**values)


def test_valid_binding_is_ready_for_job_creation():
    binding = _binding()

    assert binding.schema_version == 1
    assert binding.status == STATUS_READY_FOR_JOB_CREATION
    assert binding.ready_for_job_creation is True
    assert binding.blocking_reasons == ()
    assert binding.offline_only is True
    assert binding.autonomous is False
    assert binding.runtime_authority is False


@pytest.mark.parametrize(
    "field",
    ["job_id", "capability_id", "spec_sha256", "base_sha", "actor"],
)
@pytest.mark.parametrize("missing", [None, "", " \n\t "])
def test_missing_required_field_blocks(field, missing):
    binding = _binding(**{field: missing})

    assert binding.status == STATUS_BLOCKED
    assert binding.ready_for_job_creation is False
    assert getattr(binding, field) == ""
    assert any(
        field in reason and "required" in reason
        for reason in binding.blocking_reasons
    )


def test_missing_note_blocks():
    binding = _binding(note="  ")

    assert binding.status == STATUS_BLOCKED
    assert binding.note == ""
    assert binding.blocking_reasons == ("note is required.",)


@pytest.mark.parametrize(
    "job_id",
    ["-starts-with-dash", "has spaces", "../escape", "job/slash"],
)
def test_malformed_job_id_blocks_and_is_omitted(job_id):
    binding = _binding(job_id=job_id)

    assert binding.status == STATUS_BLOCKED
    assert binding.job_id == ""
    assert binding.blocking_reasons == (
        "job_id has an invalid format.",
    )


@pytest.mark.parametrize(
    "capability_id",
    [
        "Projects.insight",
        "projects-insight",
        "projects..insight",
        "projects.insight!",
        "../projects.insight",
    ],
)
def test_malformed_capability_id_blocks_and_is_omitted(capability_id):
    binding = _binding(capability_id=capability_id)

    assert binding.status == STATUS_BLOCKED
    assert binding.capability_id == ""
    assert binding.blocking_reasons == (
        "capability_id has an invalid format.",
    )


@pytest.mark.parametrize(
    "spec_sha256",
    ["a" * 63, "a" * 65, "A" * 64, "g" * 64, "not-a-hash"],
)
def test_malformed_spec_sha256_blocks_and_is_omitted(spec_sha256):
    binding = _binding(spec_sha256=spec_sha256)

    assert binding.status == STATUS_BLOCKED
    assert binding.spec_sha256 == ""
    assert binding.blocking_reasons == (
        "spec_sha256 has an invalid format.",
    )


@pytest.mark.parametrize(
    "base_sha",
    ["a" * 6, "a" * 65, "A" * 40, "g" * 40, "not-a-sha"],
)
def test_malformed_base_sha_blocks_and_is_omitted(base_sha):
    binding = _binding(base_sha=base_sha)

    assert binding.status == STATUS_BLOCKED
    assert binding.base_sha == ""
    assert binding.blocking_reasons == (
        "base_sha has an invalid format.",
    )


def test_base_sha_accepts_existing_build_job_length_contract():
    assert _binding(base_sha="a" * 7).ready_for_job_creation is True
    assert _binding(base_sha="a" * 40).ready_for_job_creation is True
    assert _binding(base_sha="a" * 64).ready_for_job_creation is True


@pytest.mark.parametrize(
    "field,maximum",
    [
        ("job_id", MAX_JOB_ID_BYTES),
        ("capability_id", MAX_CAPABILITY_ID_BYTES),
        ("actor", MAX_ACTOR_BYTES),
        ("note", MAX_NOTE_BYTES),
    ],
)
def test_overlong_fields_block_and_are_not_retained(field, maximum):
    value = "x" * (maximum + 1)
    binding = _binding(**{field: value})

    assert binding.status == STATUS_BLOCKED
    assert getattr(binding, field) == ""
    assert any("exceeds" in reason for reason in binding.blocking_reasons)
    assert value not in binding.summary()


def test_unicode_normalization_and_whitespace_collapse():
    binding = _binding(
        actor="  Cafe\u0301   reviewer  ",
        note="  Create\tapproved\njob   offline.  ",
    )

    assert binding.actor == "Café reviewer"
    assert binding.note == "Create approved job offline."
    assert binding.ready_for_job_creation is True


def test_control_characters_are_stripped():
    binding = _binding(
        actor="human\x00reviewer",
        note="Create\x07approved\u0085job.",
    )

    assert binding.actor == "human reviewer"
    assert binding.note == "Create approved job."
    assert binding.ready_for_job_creation is True


def test_secret_shaped_input_blocks_and_is_omitted():
    fake_key = "sk-" + "abcdefghijklmnopqrstuv"
    binding = _binding(note="Observed " + fake_key)

    assert binding.status == STATUS_BLOCKED
    assert binding.note == ""
    assert fake_key not in binding.summary()
    assert binding.blocking_reasons == (
        "note contains secret-like material.",
    )


def test_named_long_credential_blocks_without_literal_fixture():
    credential = "correct-horse-" + "battery-staple"
    binding = _binding(note="password = " + credential)

    assert binding.status == STATUS_BLOCKED
    assert binding.note == ""
    assert credential not in binding.summary()


def test_to_dict_and_summary_are_deterministic():
    first = _binding()
    second = _binding()

    assert first == second
    assert first.to_dict() == second.to_dict()
    assert first.summary() == second.summary()
    assert json.loads(first.summary()) == first.to_dict()


def test_binding_is_immutable():
    binding = _binding()

    with pytest.raises(FrozenInstanceError):
        binding.status = STATUS_BLOCKED
    with pytest.raises(FrozenInstanceError):
        binding.job_id = "changed"


def test_summary_is_bounded_and_has_no_raw_operational_fields():
    binding = _binding()
    summary = binding.summary()
    payload = json.loads(summary)

    assert len(summary.encode("utf-8")) <= MAX_BINDING_SUMMARY_BYTES
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


def test_binding_module_has_no_creation_or_external_authority():
    source_path = (
        Path(__file__).parents[1]
        / "scripts"
        / "capability_build"
        / "job_binding.py"
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
        "transition",
        "record_workflow_step",
        "freeze_scope",
        "create_workspace_dirs",
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
    assert "scripts.capability_build.job" not in source
    assert "backend.tool_registry" not in source
