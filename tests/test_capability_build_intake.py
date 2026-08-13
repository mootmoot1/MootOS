"""Focused tests for V0.4A Slice 3 returned-worker intake validation."""

import ast
from pathlib import Path

import pytest

from scripts.capability_build.intake import (
    MAX_RETURNED_FILE_BYTES,
    FileIntakeDecision,
    IntakeError,
    ReturnedFile,
    WorkerSummary,
    validate_returned_files,
)
from scripts.capability_build.scope import FrozenScope


def _scope():
    return FrozenScope(
        allowed_new_files=(
            "backend/tools_widget.py",
            "tests/test_widget.py",
        ),
        allowed_existing_files=("backend/widgets.py",),
        protected_files=("ops/protected/**",),
        forbidden_paths=("private/**",),
        justifications={
            "backend/tools_widget.py": "Add the approved tool adapter.",
            "tests/test_widget.py": "Add focused regression coverage.",
            "backend/widgets.py": "Expose the existing domain query.",
        },
    )


def _safe_items():
    return (
        ReturnedFile(
            path="backend/tools_widget.py",
            operation="create",
            content="def summarize_widget():\n    return {'count': 1}\n",
        ),
        ReturnedFile(
            path="backend/widgets.py",
            operation="modify",
            content="def list_widgets():\n    return []\n",
        ),
    )


def _returned_assignment(name, *value_parts):
    return name + ' = "' + "".join(value_parts) + '"\n'


def test_happy_path_accepts_create_and_modify_inside_frozen_scope():
    result = validate_returned_files(
        _scope(),
        _safe_items(),
        WorkerSummary(
            summary="Added the approved widget files.",
            tests_run=("pytest tests/test_widget.py -q",),
        ),
    )

    assert result.accepted is True
    assert result.blocking_findings == ()
    assert result.warnings == ()
    assert result.touched_files == (
        "backend/tools_widget.py",
        "backend/widgets.py",
    )
    assert all(
        isinstance(decision, FileIntakeDecision)
        and decision.accepted
        and decision.scope_category == "allowed"
        for decision in result.file_decisions
    )


def test_empty_returned_file_list_fails_closed():
    result = validate_returned_files(_scope(), ())

    assert result.accepted is False
    assert result.blocking_findings == (
        "returned package contains no files",
    )
    assert result.touched_files == ()


def test_returned_file_outside_scope_fails_with_explanation():
    result = validate_returned_files(
        _scope(),
        (
            ReturnedFile(
                "backend/unapproved.py", "create", "VALUE = 1\n"
            ),
        ),
    )

    assert result.accepted is False
    assert result.file_decisions[0].scope_category == "outside_scope"
    assert "outside the frozen approved scope" in result.blocking_findings[0]


@pytest.mark.parametrize(
    "path,operation,expected_category",
    [
        ("backend/tools_widget.py", "modify", "wrong_operation"),
        ("backend/widgets.py", "create", "wrong_operation"),
    ],
)
def test_create_modify_mismatch_fails(path, operation, expected_category):
    result = validate_returned_files(
        _scope(), (ReturnedFile(path, operation, "VALUE = 1\n"),)
    )

    assert result.accepted is False
    assert result.file_decisions[0].scope_category == expected_category
    assert "approved only for" in result.file_decisions[0].scope_explanation


@pytest.mark.parametrize(
    "path,category,phrase",
    [
        ("ops/protected/config.py", "protected", "protected rule"),
        ("private/credentials.py", "forbidden", "forbidden rule"),
        ("backend/tool_registry.py", "protected", "protected rule"),
        ("data/mootos.db", "forbidden", "forbidden rule"),
    ],
)
def test_protected_and_forbidden_paths_fail(path, category, phrase):
    result = validate_returned_files(
        _scope(), (ReturnedFile(path, "modify", "VALUE = 1\n"),)
    )

    assert result.accepted is False
    assert result.file_decisions[0].scope_category == category
    assert phrase in result.file_decisions[0].scope_explanation


def test_duplicate_path_fails():
    item = ReturnedFile(
        "backend/tools_widget.py", "create", "VALUE = 1\n"
    )
    result = validate_returned_files(_scope(), (item, item))

    assert result.accepted is False
    assert any(
        "duplicate returned path" in item
        for item in result.blocking_findings
    )
    assert all(not decision.accepted for decision in result.file_decisions)


def test_same_path_with_conflicting_operations_fails():
    result = validate_returned_files(
        _scope(),
        (
            ReturnedFile(
                "backend/tools_widget.py", "create", "VALUE = 1\n"
            ),
            ReturnedFile(
                "backend/tools_widget.py", "modify", "VALUE = 2\n"
            ),
        ),
    )

    assert result.accepted is False
    assert any(
        "conflicting operations" in item
        for item in result.blocking_findings
    )


@pytest.mark.parametrize(
    "path",
    [
        "/absolute/file.py",
        "../escape.py",
        "safe/../../escape.py",
        "tests/*.py",
        "safe/file.py\x00tail",
        "safe/control\x01.py",
        "safe/control\u0085.py",
    ],
)
def test_returned_file_model_rejects_unsafe_paths(path):
    with pytest.raises(IntakeError, match="Unsafe returned path"):
        ReturnedFile(path, "create", "VALUE = 1\n")


def test_returned_file_model_rejects_unsupported_operation():
    with pytest.raises(IntakeError, match="Unsupported"):
        ReturnedFile("backend/tools_widget.py", "delete", "")


def test_oversized_content_is_rejected():
    with pytest.raises(IntakeError, match="exceeds"):
        ReturnedFile(
            "backend/tools_widget.py",
            "create",
            "x" * (MAX_RETURNED_FILE_BYTES + 1),
        )


@pytest.mark.parametrize(
    "content",
    [b"binary", "safe\x00unsafe", "safe\x07unsafe", "safe\u0085unsafe"],
)
def test_non_text_and_binary_control_content_is_rejected(content):
    with pytest.raises(IntakeError, match="text|binary/control"):
        ReturnedFile("backend/tools_widget.py", "create", content)


@pytest.mark.parametrize(
    "content",
    [
        _returned_assignment(
            "OPENAI_API_KEY", "sk-", "abcdefghijklmnopqrstuv"
        ),
        _returned_assignment(
            "password", "correct-horse-battery-", "staple"
        ),
        _returned_assignment(
            "token", "ghp_", "abcdefghijklmnopqrstuvwxyz123456"
        ),
    ],
)
def test_obvious_secret_patterns_are_blocking(content):
    result = validate_returned_files(
        _scope(),
        (ReturnedFile("backend/tools_widget.py", "create", content),),
    )

    assert result.accepted is False
    assert any("secret-like" in item for item in result.blocking_findings)


@pytest.mark.parametrize(
    "content",
    [
        'open("data/mootos.db", "rb")\n',
        'Path("data/profile.json").read_text()\n',
        'Path("data") / "profile.json"\n',
        'sqlite3.connect("data/mootos.db")\n',
    ],
)
def test_data_path_access_is_blocking(content):
    result = validate_returned_files(
        _scope(),
        (ReturnedFile("backend/tools_widget.py", "create", content),),
    )

    assert result.accepted is False
    assert any("access data/" in item for item in result.blocking_findings)


@pytest.mark.parametrize(
    "content",
    [
        "import subprocess\nsubprocess.run(['echo', 'bad'])\n",
        "import sys, subprocess\n",
        'os.system("echo bad")\n',
        'subprocess.run("echo bad", shell=True)\n',
    ],
)
def test_subprocess_and_shell_usage_is_blocking(content):
    result = validate_returned_files(
        _scope(),
        (ReturnedFile("backend/tools_widget.py", "create", content),),
    )

    assert result.accepted is False
    assert any(
        "subprocess or shell" in item
        for item in result.blocking_findings
    )


@pytest.mark.parametrize(
    "content",
    [
        "from git import Repo\nRepo('.').git.push()\n",
        'command = "git push origin branch"\n',
        'run(["git", "commit", "-m", "bad"])\n',
    ],
)
def test_git_automation_usage_is_blocking(content):
    result = validate_returned_files(
        _scope(),
        (ReturnedFile("backend/tools_widget.py", "create", content),),
    )

    assert result.accepted is False
    assert any("Git automation" in item for item in result.blocking_findings)


@pytest.mark.parametrize(
    "content",
    [
        "from backend.tool_registry import get_tool_registry\n",
        "from backend import tool_registry\n",
    ],
)
def test_runtime_authority_import_is_blocking(content):
    result = validate_returned_files(
        _scope(),
        (
            ReturnedFile(
                "backend/tools_widget.py",
                "create",
                content,
            ),
        ),
    )

    assert result.accepted is False
    assert any(
        "runtime-authority" in item for item in result.blocking_findings
    )


def test_result_ordering_is_deterministic_regardless_of_input_order():
    forward = validate_returned_files(_scope(), _safe_items())
    reverse = validate_returned_files(_scope(), tuple(reversed(_safe_items())))

    assert forward == reverse
    assert [item.path for item in forward.file_decisions] == [
        "backend/tools_widget.py",
        "backend/widgets.py",
    ]


def test_worker_summary_round_trips_and_missing_tests_produces_warning():
    summary = WorkerSummary.from_dict(
        {"summary": "Implemented the approved files.", "tests_run": []}
    )
    assert WorkerSummary.from_dict(summary.to_dict()) == summary

    result = validate_returned_files(
        _scope(), _safe_items(), worker_summary=summary
    )
    assert result.accepted is True
    assert result.warnings == ("worker summary declares no tests run",)


def test_intake_module_has_no_runtime_execution_or_filesystem_authority():
    source_path = (
        Path(__file__).parents[1]
        / "scripts"
        / "capability_build"
        / "intake.py"
    )
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    forbidden_imports = {
        "backend",
        "git",
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
