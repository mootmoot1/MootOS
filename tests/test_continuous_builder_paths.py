"""Tests for M3: deterministic, host-independent POSIX path
canonicalization -- direct unit tests of paths.py, plus the blueprint
and conflict-analysis integration points that depend on it."""

import pytest

from backend.continuous_builder.blueprint import BlueprintError
from backend.continuous_builder.blueprint_parser import parse_blueprint
from backend.continuous_builder.conflict_analysis import (
    EligibilityResources,
    analyze_conflicts,
)
from backend.continuous_builder.dependency_analysis import analyze_dependencies
from backend.continuous_builder.paths import (
    PathCanonicalizationError,
    canonicalize_repo_path,
)
from backend.continuous_builder.queue_proposal import propose_candidates
from test_continuous_builder_blueprint import make_blueprint, make_slice


@pytest.mark.parametrize("value,expected", [
    ("backend/db.py", "backend/db.py"),
    ("./backend/db.py", "backend/db.py"),
    ("backend/./db.py", "backend/db.py"),
    ("backend//db.py", "backend/db.py"),
    ("backend/sub/../db.py", "backend/db.py"),
    ("a/b/../../c", "c"),
])
def test_equivalent_paths_canonicalize_identically(value, expected):
    assert canonicalize_repo_path(value) == expected


@pytest.mark.parametrize("value", [
    "../escape",
    "a/../../escape",
    "/etc/passwd",
    "~/secrets",
    "~root/.ssh/id_rsa",
    "C:/Windows/System32",
    "a\\..\\..\\etc\\passwd",
    "a\\b",
    "",
    ".",
    "..",
])
def test_unsafe_or_ambiguous_paths_are_rejected(value):
    with pytest.raises(PathCanonicalizationError):
        canonicalize_repo_path(value)


def test_backslash_traversal_cannot_bypass_forward_slash_dot_dot_check():
    """A pre-Phase-2.5 regex only rejected ".." bounded by "/" -- a
    backslash-delimited ".." string passed validation even though it is
    exactly the traversal the check exists to catch on a platform that
    treats backslash as a separator. It must be rejected outright now,
    not resolved."""
    with pytest.raises(PathCanonicalizationError):
        canonicalize_repo_path("a\\..\\..\\b")


def test_blueprint_slice_rejects_unsafe_paths_via_canonicalization():
    with pytest.raises(BlueprintError, match="unsafe path"):
        make_slice(allowed_paths=("~/secrets",))
    with pytest.raises(BlueprintError, match="unsafe path"):
        make_slice(allowed_paths=("a\\..\\..\\etc",))


def test_blueprint_slice_normalizes_equivalent_paths_to_the_same_value():
    slice_ = make_slice(allowed_paths=("backend/./continuous_builder/blueprint.py",))
    assert slice_.allowed_paths == ("backend/continuous_builder/blueprint.py",)


def test_blueprint_rejects_paths_that_canonicalize_to_a_duplicate():
    with pytest.raises(BlueprintError, match="unique"):
        make_slice(allowed_paths=(
            "backend/db.py", "backend/./db.py",
        ))


def test_conflict_analysis_recognizes_equivalent_paths_as_overlapping():
    parsed = parse_blueprint(
        make_blueprint(
            slices=(make_slice(allowed_paths=("backend/db.py",)),),
        ).canonical_bytes()
    )
    dependencies = analyze_dependencies(parsed, propose_candidates(parsed))
    resources = EligibilityResources(
        available_capabilities=("planning",),
        available_authority_classes=(),
        active_slice_scopes=(
            ("other-slice", ("backend/./db.py",)),
        ),
    )
    analysis = analyze_conflicts(dependencies, resources)
    assert analysis.results[0].eligible is False
    assert "active_scope_conflict:other-slice" in analysis.results[0].blocked_reasons


def test_path_matching_is_case_sensitive_regardless_of_host_platform():
    from backend.continuous_builder.conflict_analysis import _paths_overlap
    assert _paths_overlap("Backend/DB.py", "backend/db.py") is False
    assert _paths_overlap("backend/db.py", "backend/db.py") is True
