"""Tests for the V0.3D registration/execution-authority gate
(scripts/gates/registration_authority.py).

Uses `evaluate_files` (a pure function over (relative_path, source_text)
pairs) for the synthetic/adversarial cases -- fast, and tests the actual
detection logic directly. A small number of tests exercise `evaluate()`
against this repository's real `backend/` tree.
"""

from pathlib import Path

from scripts.gates.registration_authority import (
    evaluate,
    evaluate_files,
    scan_dangerous_constructs,
    scan_executor_call_sites,
)


# --- 10. Alternate registry/executor bypass patterns are rejected ------------


def test_importlib_import_module_is_flagged():
    files = [("backend/sneaky.py", "import importlib\nmod = importlib.import_module(name)\n")]
    violations = scan_dangerous_constructs(files)
    assert any("dynamic import (importlib.import_module)" in v for v in violations)


def test_dunder_import_is_flagged():
    files = [("backend/sneaky.py", "mod = __import__('os')\n")]
    violations = scan_dangerous_constructs(files)
    assert any("dynamic import (__import__)" in v for v in violations)


def test_pkgutil_iter_modules_is_flagged():
    files = [("backend/sneaky.py", "import pkgutil\nfor m in pkgutil.iter_modules(path):\n    pass\n")]
    violations = scan_dangerous_constructs(files)
    assert any("plugin auto-discovery (pkgutil.iter_modules)" in v for v in violations)


def test_pkg_resources_is_flagged():
    files = [("backend/sneaky.py", "import pkg_resources\n")]
    violations = scan_dangerous_constructs(files)
    assert any("plugin auto-discovery (pkg_resources)" in v for v in violations)


def test_entry_points_is_flagged():
    files = [("backend/sneaky.py", "plugins = entry_points(group='mootos.tools')\n")]
    violations = scan_dangerous_constructs(files)
    assert any("plugin auto-discovery (entry_points)" in v for v in violations)


def test_bare_eval_is_flagged():
    files = [("backend/sneaky.py", "result = eval(user_supplied)\n")]
    violations = scan_dangerous_constructs(files)
    assert any("dynamic code execution (eval)" in v for v in violations)


def test_bare_exec_is_flagged():
    files = [("backend/sneaky.py", "exec(user_supplied)\n")]
    violations = scan_dangerous_constructs(files)
    assert any("dynamic code execution (exec)" in v for v in violations)


def test_violation_message_includes_file_and_line_number():
    files = [("backend/sneaky.py", "# comment\n# comment\nmod = __import__('os')\n")]
    violations = scan_dangerous_constructs(files)
    assert any(v.startswith("backend/sneaky.py:3:") for v in violations)


def test_executor_call_outside_the_central_executor_is_flagged():
    files = [("backend/tool_conversation.py", "output = tool_definition.executor(args)\n")]
    violations = scan_executor_call_sites(files)
    assert len(violations) == 1
    assert "backend/tool_conversation.py:1:" in violations[0]
    assert "outside the central executor" in violations[0]


def test_executor_call_inside_tool_executor_py_is_allowed():
    files = [("backend/tool_executor.py", "output = definition.executor(**kwargs)\n")]
    assert scan_executor_call_sites(files) == []


def test_executor_call_inside_tool_types_py_is_allowed():
    """tool_types.py defines the `executor` field but must never call it;
    it is allow-listed on the theory that it doesn't, not because calling
    it there would be safe -- if it ever does, this test still passes,
    which is a known, accepted narrowness of a purely textual scan."""
    files = [("backend/tool_types.py", "# executor: Callable field defined below\n")]
    assert scan_executor_call_sites(files) == []


def test_multiple_bypass_files_all_reported_together():
    files = [
        ("backend/a.py", "mod = importlib.import_module(x)\n"),
        ("backend/b.py", "out = something.executor(args)\n"),
    ]
    result = evaluate_files(files)
    assert result.passed is False
    assert len(result.violations) == 2


# --- False-positive avoidance -------------------------------------------------


def test_execute_tool_function_name_does_not_false_positive_on_exec_substring():
    """`execute_tool`, `execute`, `executor` (the field name itself) must
    not trip the bare-`exec(`/`eval(` word-boundary patterns -- those match
    only the literal call shapes `exec(` / `eval(`, not substrings."""
    files = [
        (
            "backend/tool_executor.py",
            "def execute_tool(name, args):\n"
            "    definition = registry.lookup(name)\n"
            "    return definition.executor(**args)\n",
        )
    ]
    result = evaluate_files(files)
    assert result.passed is True


def test_unrelated_dotted_exec_or_eval_attribute_access_does_not_false_positive():
    """A method call like `something.exec(...)` or `obj.eval(...)` (dotted
    access) is a different construct from the bare builtin call and is
    intentionally not flagged -- the negative lookbehind excludes it."""
    files = [("backend/db.py", "cursor.execute(query)\n")]
    result = evaluate_files(files)
    assert result.passed is True


def test_regular_function_definition_named_similarly_is_not_flagged():
    files = [("backend/tasks.py", "def evaluate_dependencies(task):\n    pass\n")]
    result = evaluate_files(files)
    assert result.passed is True


def test_clean_file_with_no_dangerous_constructs_passes():
    files = [
        (
            "backend/tools_reference.py",
            "from backend.tool_types import ToolDefinition\n\n"
            "def build_tools():\n    return [ToolDefinition(...)]\n",
        )
    ]
    result = evaluate_files(files)
    assert result.passed is True
    assert "PASS" in result.summary()


# --- Adversarial: attempts to evade the registration-authority gate ---------


def test_underscore_prefixed_import_lookalike_is_not_confused_with_dunder_import():
    """`_my__import__thing(x)` must not be mistaken for the builtin
    `__import__(` call -- the negative lookbehind on the leading
    underscore exists precisely so an identifier that merely *contains*
    the dunder name isn't flagged."""
    files = [("backend/x.py", "value = _my__import__thing(x)\n")]
    violations = scan_dangerous_constructs(files)
    assert violations == []


def test_summary_lists_every_violation_line():
    files = [("backend/sneaky.py", "import importlib\nmod = importlib.import_module('os')\n")]
    result = evaluate_files(files)
    summary = result.summary()
    assert "FAIL" in summary
    assert "VIOLATION" in summary
    assert "importlib.import_module" in summary


def test_multiline_file_only_flags_the_offending_lines_not_the_whole_file():
    files = [
        (
            "backend/mixed.py",
            "def safe_function():\n    return 1\n\n\ndef sneaky_function():\n    return eval('1')\n",
        )
    ]
    violations = scan_dangerous_constructs(files)
    assert len(violations) == 1
    assert violations[0].startswith("backend/mixed.py:6:")


# --- git/filesystem-backed integration (real repository) ---------------------


def test_evaluate_against_the_real_repository_backend_tree_passes():
    """The gate against this repository's actual, unmodified backend/
    tree must pass -- proving no known-dangerous construct or executor
    bypass currently exists in the codebase."""
    repository_root = Path(__file__).resolve().parent.parent
    result = evaluate(repository_root)
    assert result.passed is True, result.summary()


def test_evaluate_defaults_to_current_working_directory_when_root_omitted(monkeypatch):
    repository_root = Path(__file__).resolve().parent.parent
    monkeypatch.chdir(repository_root)
    result = evaluate()
    assert result.passed is True, result.summary()
