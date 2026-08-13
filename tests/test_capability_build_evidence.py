"""Focused tests for V0.4A Slice 4 verification planning and evidence."""

import ast
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from scripts.capability_build.evidence import (
    MAX_OUTPUT_EXCERPT_BYTES,
    EvidenceRecord,
    VerificationCommand,
    VerificationError,
    build_default_verification_plan,
    evaluate_evidence,
)
from scripts.capability_build.intake import (
    ReturnedFile,
    validate_returned_files,
)
from scripts.capability_build.scope import FrozenScope


def _scope():
    return FrozenScope(
        allowed_new_files=(
            "backend/tools_widget.py",
            "tests/test_widget.py",
        ),
        justifications={
            "backend/tools_widget.py": "Add the approved tool adapter.",
            "tests/test_widget.py": "Add focused regression coverage.",
        },
    )


def _accepted_intake(*, reverse=False):
    returned = (
        ReturnedFile(
            "backend/tools_widget.py",
            "create",
            "def widget():\n    return 1\n",
        ),
        ReturnedFile(
            "tests/test_widget.py",
            "create",
            "def test_widget():\n    assert True\n",
        ),
    )
    if reverse:
        returned = tuple(reversed(returned))
    return validate_returned_files(_scope(), returned)


def _records_for(plan, status="passed"):
    return tuple(
        EvidenceRecord(
            command_name=command.name,
            status=status,
            summary=f"{command.name} {status}.",
            exit_code=0 if status == "passed" else 1,
        )
        for command in plan.commands
    )


def test_default_plan_from_accepted_intake_is_inert_and_conservative():
    plan = build_default_verification_plan(_accepted_intake())

    assert plan.intake_accepted is True
    assert plan.blocking_findings == ()
    assert plan.touched_files == (
        "backend/tools_widget.py",
        "tests/test_widget.py",
    )
    assert tuple(command.kind for command in plan.commands) == (
        "static",
        "lint",
        "test",
    )
    assert plan.commands[0].argv == (
        "python3",
        "-m",
        "py_compile",
        "backend/tools_widget.py",
        "tests/test_widget.py",
    )
    assert plan.commands[-1].argv == (
        "python3",
        "-m",
        "pytest",
        "tests/test_widget.py",
        "-q",
    )
    assert all(not command.allow_network for command in plan.commands)
    assert all(not command.writes_allowed for command in plan.commands)


def test_default_plan_rejects_failed_intake():
    failed = validate_returned_files(
        _scope(),
        (ReturnedFile("backend/unapproved.py", "create", "VALUE = 1\n"),),
    )

    with pytest.raises(VerificationError, match="intake was not accepted"):
        build_default_verification_plan(failed)


def test_default_plan_ordering_is_deterministic():
    forward = build_default_verification_plan(_accepted_intake())
    reverse = build_default_verification_plan(_accepted_intake(reverse=True))

    assert forward == reverse


def test_verification_models_are_immutable():
    command = VerificationCommand(
        name="tests",
        argv=("python3", "-m", "pytest", "tests", "-q"),
        kind="test",
    )

    with pytest.raises(FrozenInstanceError):
        command.name = "changed"


def test_shell_string_instead_of_argv_is_rejected():
    with pytest.raises(
        VerificationError, match="argv must be a tuple or list"
    ):
        VerificationCommand(
            name="tests",
            argv="python3 -m pytest tests -q",
            kind="test",
        )


def test_single_shell_command_string_inside_argv_is_rejected():
    with pytest.raises(VerificationError, match="shell command string"):
        VerificationCommand(
            name="tests",
            argv=("python3 -m pytest tests -q",),
            kind="test",
        )


def test_shell_metacharacters_are_rejected():
    with pytest.raises(VerificationError, match="shell metacharacters"):
        VerificationCommand(
            name="tests",
            argv=("python3", "-m", "pytest", "; rm -rf target"),
            kind="test",
        )


@pytest.mark.parametrize(
    "argv",
    [
        ("git", "diff", "--check"),
        ("/bin/bash", "-lc", "pytest"),
        ("rm", "temporary-file"),
        ("python3", "wrapper.py", "curl"),
    ],
)
def test_dangerous_commands_and_verbs_are_rejected(argv):
    with pytest.raises(VerificationError, match="dangerous command token"):
        VerificationCommand(name="unsafe", argv=argv, kind="static")


@pytest.mark.parametrize("flag", ["-c", "-Ic"])
def test_python_c_is_rejected(flag):
    with pytest.raises(VerificationError, match="python -c"):
        VerificationCommand(
            name="unsafe",
            argv=("python3", flag, "print('unsafe')"),
            kind="static",
        )


@pytest.mark.parametrize(
    "field,value,message",
    [
        ("allow_network", True, "network-enabled"),
        ("writes_allowed", True, "write-enabled"),
    ],
)
def test_network_and_write_flags_are_rejected(field, value, message):
    arguments = {
        "name": "tests",
        "argv": ("python3", "-m", "pytest", "tests", "-q"),
        "kind": "test",
        field: value,
    }

    with pytest.raises(VerificationError, match=message):
        VerificationCommand(**arguments)


@pytest.mark.parametrize("timeout", [0, 301, True])
def test_timeout_limit_is_enforced(timeout):
    with pytest.raises(VerificationError, match="timeout_seconds"):
        VerificationCommand(
            name="tests",
            argv=("python3", "-m", "pytest", "tests", "-q"),
            kind="test",
            timeout_seconds=timeout,
        )


def test_unsupported_kind_is_rejected():
    with pytest.raises(VerificationError, match="unsupported command kind"):
        VerificationCommand(
            name="deploy",
            argv=("deploy-tool",),
            kind="deploy",
        )


def test_all_required_passed_evidence_is_accepted():
    plan = build_default_verification_plan(_accepted_intake())
    records = tuple(reversed(_records_for(plan)))

    bundle = evaluate_evidence(plan, records)

    assert bundle.accepted is True
    assert bundle.status == "passed"
    assert bundle.missing_commands == ()
    assert tuple(record.command_name for record in bundle.records) == tuple(
        command.name for command in plan.commands
    )
    assert bundle.summary() == (
        "verification evidence: passed; passed=3; failed=0; blocked=0; "
        "not_run=0; missing=none"
    )


def test_missing_evidence_is_not_accepted():
    plan = build_default_verification_plan(_accepted_intake())

    bundle = evaluate_evidence(plan, _records_for(plan)[:-1])

    assert bundle.accepted is False
    assert bundle.status == "incomplete"
    assert bundle.missing_commands == (plan.commands[-1].name,)


def test_failed_evidence_is_not_accepted():
    plan = build_default_verification_plan(_accepted_intake())
    records = list(_records_for(plan))
    records[1] = EvidenceRecord(
        command_name=plan.commands[1].name,
        status="failed",
        summary="Blocking lint findings were reported.",
        exit_code=1,
    )

    bundle = evaluate_evidence(plan, records)

    assert bundle.accepted is False
    assert bundle.status == "failed"


def test_blocked_evidence_dominates_failed_evidence():
    plan = build_default_verification_plan(_accepted_intake())
    records = list(_records_for(plan))
    records[0] = EvidenceRecord(
        command_name=plan.commands[0].name,
        status="failed",
        summary="Static validation failed.",
        exit_code=1,
    )
    records[1] = EvidenceRecord(
        command_name=plan.commands[1].name,
        status="blocked",
        summary="Verification environment was unavailable.",
    )

    bundle = evaluate_evidence(plan, records)

    assert bundle.accepted is False
    assert bundle.status == "blocked"


@pytest.mark.parametrize("status", ["unknown", "PASS", ""])
def test_unknown_evidence_status_is_rejected(status):
    with pytest.raises(VerificationError, match="unknown evidence status"):
        EvidenceRecord("tests", status, "External result.")


@pytest.mark.parametrize(
    "output",
    [
        "x" * (MAX_OUTPUT_EXCERPT_BYTES + 1),
        "safe\x00unsafe",
        "safe\u0085unsafe",
    ],
)
def test_output_excerpt_bounds_and_controls_are_rejected(output):
    with pytest.raises(VerificationError, match="output_excerpt"):
        EvidenceRecord(
            command_name="tests",
            status="failed",
            summary="Tests failed.",
            exit_code=1,
            output_excerpt=output,
        )


def test_passed_evidence_rejects_nonzero_exit_code():
    with pytest.raises(VerificationError, match="nonzero exit code"):
        EvidenceRecord("tests", "passed", "Tests passed.", exit_code=1)


def test_unknown_and_duplicate_evidence_records_are_rejected():
    plan = build_default_verification_plan(_accepted_intake())
    unknown = EvidenceRecord("unknown", "passed", "Unknown passed.")
    with pytest.raises(VerificationError, match="unknown command"):
        evaluate_evidence(plan, (unknown,))

    duplicate = _records_for(plan)[0]
    with pytest.raises(VerificationError, match="duplicate evidence"):
        evaluate_evidence(plan, (duplicate, duplicate))


def test_evidence_module_has_no_execution_or_filesystem_authority():
    source_path = (
        Path(__file__).parents[1]
        / "scripts"
        / "capability_build"
        / "evidence.py"
    )
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    forbidden_imports = {
        "backend",
        "git",
        "os",
        "pathlib",
        "pygit2",
        "dulwich",
        "shutil",
        "subprocess",
    }
    forbidden_calls = {
        "eval",
        "exec",
        "open",
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
        imported.split(".")[0] in forbidden_imports
        for imported in imports
    )
    assert not forbidden_calls & set(calls)
