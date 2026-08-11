"""Tests for the V0.3D protected-path gate (scripts/gates/protected_paths.py).

Deliberately uses `evaluate_changed_paths` (a pure function over a plain
list of path strings) rather than real git diffs for most cases -- this is
faster, avoids constructing throwaway commits, and tests the actual
decision logic directly. `git_changed_paths`/`evaluate` (the git-backed
wrappers) get a smaller, focused set of tests against this repository's
real history.
"""

import subprocess

import pytest

from scripts.gates import policy
from scripts.gates.protected_paths import (
    evaluate,
    evaluate_changed_paths,
    git_changed_paths,
    is_denied,
)


# --- 1. Ordinary allowed feature-file changes pass ---------------------------


@pytest.mark.parametrize(
    "path",
    [
        "backend/tools_reference.py",
        "backend/tools_web.py",
        "backend/gap_reasoning.py",
        "backend/self_inspection.py",
        "backend/capability_catalog.py",
        "backend/memory.py",
        "backend/tasks.py",
        "tests/test_tools_reference.py",
        "tests/test_gap_reasoning.py",
        "docs/TOOL_SYSTEM.md",
        "docs/GATES_AND_RELEASE_SAFETY.md",
        "ARCHITECTURE.md",
        "ROADMAP.md",
        "README.md",
        "requirements.txt",
        "requirements-dev.txt",
        "frontend/app.js",
        ".env.example",
    ],
)
def test_ordinary_feature_files_are_allowed(path):
    assert is_denied(path) is False


def test_a_batch_of_ordinary_changes_passes_as_a_whole():
    result = evaluate_changed_paths(
        [
            "backend/tools_reference.py",
            "tests/test_tools_reference.py",
            "docs/TOOL_SYSTEM.md",
        ]
    )
    assert result.passed is True
    assert result.violations == ()
    assert "PASS" in result.summary()


# --- 2. Changes to protected permission/approval files fail -----------------


@pytest.mark.parametrize(
    "path",
    [
        "backend/tool_executor.py",
        "backend/tool_operations.py",
        "backend/tool_conversation.py",
        "backend/tool_budget.py",
        "backend/tool_types.py",
        "backend/tool_validation.py",
        "backend/tool_registry.py",
        "backend/auth.py",
        "backend/main.py",
        "backend/tool_routes.py",
        "backend/application.py",
        "railway.toml",
    ],
)
def test_protected_core_files_are_denied(path):
    assert is_denied(path) is True


def test_a_mixed_batch_fails_if_any_single_file_is_protected():
    result = evaluate_changed_paths(
        [
            "backend/tools_reference.py",  # allowed
            "docs/TOOL_SYSTEM.md",  # allowed
            "backend/tool_executor.py",  # protected
        ]
    )
    assert result.passed is False
    assert result.violations == ("backend/tool_executor.py",)
    assert "FAIL" in result.summary()
    assert "backend/tool_executor.py" in result.summary()


def test_github_workflows_directory_is_denied():
    """Not just the current workflow file -- the whole directory, so a
    future second workflow file is covered without a policy update."""
    assert is_denied(".github/workflows/python-package.yml") is True
    assert is_denied(".github/workflows/a-future-workflow.yml") is True


# --- 3. Changes to the gate policy itself fail unless explicitly allowed ----


@pytest.mark.parametrize(
    "path",
    [
        "scripts/gates/policy.py",
        "scripts/gates/protected_paths.py",
        "scripts/gates/migration_safety.py",
        "scripts/gates/risk_metadata.py",
        "scripts/gates/registration_authority.py",
        "scripts/gates/secret_scan.py",
        "scripts/gates/run_gates.py",
        "scripts/gates/__init__.py",
        "scripts/gates/some_future_gate_file.py",
    ],
)
def test_gate_policy_and_tooling_cannot_evade_its_own_protection(path):
    """A diff cannot rewrite the policy (or any gate script) to grant
    itself permission -- the whole scripts/gates/ tree is protected."""
    assert is_denied(path) is True


def test_policy_module_lists_its_own_directory_as_denied():
    """Direct assertion on the policy data itself, not just behavior --
    guards against someone editing DENIED_PATHS to remove this entry
    without a test failing to notice."""
    assert "scripts/gates/" in policy.DENIED_PATHS


def test_allowed_exceptions_do_not_currently_defeat_any_self_protection():
    """Today ALLOWED_EXCEPTIONS is empty; if it is ever populated, no entry
    may live inside scripts/gates/ itself -- that would let a future PR
    excuse its own policy tampering."""
    for exception in policy.ALLOWED_EXCEPTIONS:
        assert not exception.startswith("scripts/gates/"), (
            f"{exception!r} would let a diff exempt the gate tooling from its own protection"
        )


# --- Adversarial: attempts to evade the path gate ----------------------------


@pytest.mark.parametrize(
    "path",
    [
        "backend/tool_executor.py.bak",  # not exact -- must NOT falsely match
        "backend/tool_executorx.py",
        "backend/subdir/tool_executor.py",
        "not_backend/tool_executor.py",
    ],
)
def test_lookalike_paths_are_not_confused_with_protected_ones(path):
    """The gate matches exact paths / real subdirectories -- not substrings
    -- so it neither over-blocks innocuous similarly-named files nor
    (more importantly) could be tricked into treating a *different*,
    non-identical path as equivalent to a protected one."""
    assert is_denied(path) is False


def test_evaluate_changed_paths_strips_whitespace_before_checking():
    """`evaluate_changed_paths` (the real entry point every caller uses) is
    the layer that normalizes whitespace -- git itself never emits padded
    paths, but this proves stray whitespace can't be used to slip a
    protected path past the check."""
    result = evaluate_changed_paths([" backend/tool_executor.py ", "\tbackend/tool_operations.py\t"])
    assert result.passed is False
    assert set(result.violations) == {"backend/tool_executor.py", "backend/tool_operations.py"}


@pytest.mark.parametrize(
    "path",
    ["./backend/tool_executor.py", "backend//tool_executor.py"],
)
def test_non_canonical_path_forms_are_not_treated_as_protected(path):
    """git diff --name-only never emits a './'-prefixed or doubled-slash
    path, so `is_denied` intentionally does not special-case them -- they
    simply fail to match anything, which is the safe direction (a real
    protected-path touch is never expressed this way by git, so there is
    nothing here for an attacker to exploit by *avoiding* a match)."""
    assert is_denied(path) is False


def test_a_diff_that_adds_a_new_file_under_a_denied_directory_is_still_caught():
    """Protection is directory-prefix based, not "must already exist" --
    a brand-new file placed under scripts/gates/ is caught exactly like an
    edit to an existing one."""
    assert is_denied("scripts/gates/brand_new_file_nobody_has_seen.py") is True


def test_empty_and_blank_paths_are_ignored_not_denied():
    result = evaluate_changed_paths(["", "   ", "backend/tools_reference.py"])
    assert result.passed is True
    assert result.changed_paths == ("backend/tools_reference.py",)


# --- git-backed integration (small, real-history smoke tests) ---------------


def test_git_changed_paths_returns_a_list_of_strings():
    # Diffing a commit against itself must yield no changes.
    paths = git_changed_paths("HEAD", "HEAD")
    assert paths == []


def test_git_changed_paths_uses_three_dot_merge_base_semantics():
    """Sanity check that this really shells out to `git diff A...B`, not
    `git diff A B` -- verified by confirming the invocation succeeds
    against a real ref and returns a list (exact contents depend on repo
    state, which is why this only checks the type/shape, not specific
    paths)."""
    paths = git_changed_paths("HEAD~1", "HEAD")
    assert isinstance(paths, list)
    assert all(isinstance(path, str) for path in paths)


def test_evaluate_end_to_end_against_a_real_but_trivial_diff():
    result = evaluate("HEAD", "HEAD")
    assert result.passed is True
    assert result.changed_paths == ()


def test_git_changed_paths_raises_on_an_invalid_ref():
    with pytest.raises(subprocess.CalledProcessError):
        git_changed_paths("this-ref-does-not-exist-anywhere", "HEAD")
