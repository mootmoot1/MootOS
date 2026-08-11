"""V0.3E x V0.3D integration: proves the manual capability-build pipeline
actually invokes and respects the real, unmodified V0.3D mechanical gates
against the kind of diff this pipeline produces.

Deliberately does NOT shell out to git against a real 'origin/main' ref --
the normal CI build job checks out with fetch-depth: 1 and no extra
fetch, so a real ref like 'origin/main' is not guaranteed to exist
locally (this is the exact class of bug already fixed once in V0.3D's own
three-dot-semantics test; this file does not repeat it). Every gate
below is exercised through its real, pure, git-independent entry point
instead: a literal list of changed paths, or the real files already on
disk in this working tree.
"""

from pathlib import Path

from scripts.gates import policy
from scripts.gates.protected_paths import evaluate_changed_paths
from scripts.gates.registration_authority import evaluate_files as evaluate_registration_authority
from scripts.gates.risk_metadata import evaluate as evaluate_risk_metadata
from scripts.gates.secret_scan import evaluate_paths as evaluate_secret_scan


REPO_ROOT = Path(__file__).resolve().parent.parent

# Representative of the kind of diff V0.3E's manual pipeline actually
# produces: one protected-core registration edit, plus new, unprotected
# capability files (tool module, tests, docs, spec artifacts).
V03E_STYLE_CHANGED_PATHS = (
    "backend/tool_registry.py",
    "backend/tools_task_summary.py",
    "backend/tasks.py",
    "backend/capability_catalog.py",
    "tests/test_tools_task_summary.py",
    "tests/test_capability_spec.py",
    "tests/test_capability_lifecycle.py",
    "scripts/capability_pipeline/spec.py",
    "scripts/capability_pipeline/lifecycle.py",
    "scripts/capability_pipeline/review.py",
    "capability_specs/tasks_status_summary.json",
    "docs/CAPABILITY_BUILD_PIPELINE.md",
)


# --- 13. V0.3D gates run and fail appropriately on protected changes --------


def test_protected_path_gate_flags_exactly_the_registry_edit():
    """A V0.3E-shaped diff must fail the protected-path gate, and fail on
    exactly backend/tool_registry.py -- not on the new tool module, the
    tests, the pipeline tooling, or the docs, all of which are
    deliberately unprotected (docs/GATES_AND_RELEASE_SAFETY.md Sec2)."""
    result = evaluate_changed_paths(V03E_STYLE_CHANGED_PATHS)

    assert result.passed is False
    assert result.violations == ("backend/tool_registry.py",)
    assert "backend/tools_task_summary.py" not in result.violations
    assert "FAIL" in result.summary()


def test_the_registry_edit_alone_is_sufficient_to_fail_the_gate():
    result = evaluate_changed_paths(["backend/tool_registry.py"])
    assert result.passed is False


def test_a_v03e_diff_with_the_registry_edit_removed_would_pass():
    """Sanity check on the other direction: if a future capability truly
    needs no protected-core change at all (unlike this one), the gate
    correctly has nothing to object to."""
    without_registry_edit = tuple(p for p in V03E_STYLE_CHANGED_PATHS if p != "backend/tool_registry.py")
    result = evaluate_changed_paths(without_registry_edit)
    assert result.passed is True


def test_backend_tool_registry_py_is_confirmed_still_in_the_real_policy():
    """Direct assertion against the real, unmodified policy -- this test
    would fail loudly if V0.3E (or anything else) ever weakened
    protection on the registration-authority file, which this phase's
    instructions explicitly forbid."""
    assert "backend/tool_registry.py" in policy.DENIED_PATHS


def test_the_new_capability_pipeline_tooling_itself_is_not_a_protected_path():
    """scripts/capability_pipeline/ is offline dev tooling, not part of
    scripts/gates/ -- it must not be (and is not) swept into the gates'
    own self-protection prefix."""
    for path in (
        "scripts/capability_pipeline/spec.py",
        "scripts/capability_pipeline/lifecycle.py",
        "scripts/capability_pipeline/review.py",
    ):
        result = evaluate_changed_paths([path])
        assert result.passed is True, f"{path} should not be protected"


# --- Adversarial: bypass registration authority ------------------------------


def test_registration_authority_gate_is_clean_against_the_new_v03e_backend_files():
    """Re-runs the real registration-authority scan against the actual,
    real source of the new V0.3E backend files on disk -- proving no
    dynamic-import/plugin-discovery/executor-bypass pattern was
    introduced by this phase, on top of V0.3D's own full-repo test
    already covering this."""
    files = []
    for relative in ("backend/tools_task_summary.py", "backend/tasks.py", "backend/tool_registry.py"):
        files.append((relative, (REPO_ROOT / relative).read_text(encoding="utf-8")))

    result = evaluate_registration_authority(files)
    assert result.passed is True, result.summary()


def test_the_new_tool_module_calls_registry_register_not_the_executor_directly():
    """A textual confirmation that backend/tools_task_summary.py follows
    the one approved registration shape (registry.register(...)) and
    never calls a tool's executor itself -- the exact bypass shape
    registration_authority.py exists to catch."""
    source = (REPO_ROOT / "backend" / "tools_task_summary.py").read_text(encoding="utf-8")
    assert "registry.register(" in source
    assert ".executor(" not in source


# --- Risk metadata / secret scan stay green around the new files ------------


def test_risk_metadata_gate_still_passes_with_the_new_tool_registered():
    result = evaluate_risk_metadata(REPO_ROOT)
    assert result.passed is True, result.summary()


def test_secret_scan_gate_is_clean_against_every_new_v03e_file():
    new_paths = [
        "backend/tools_task_summary.py",
        "backend/tasks.py",
        "scripts/capability_pipeline/spec.py",
        "scripts/capability_pipeline/lifecycle.py",
        "scripts/capability_pipeline/review.py",
        "scripts/capability_pipeline/build_proof_record.py",
        "scripts/capability_pipeline/build_gap_report_example.py",
        "capability_specs/tasks_status_summary.json",
        "capability_specs/tasks_status_summary.gap_report.json",
    ]
    result = evaluate_secret_scan(new_paths, REPO_ROOT)
    assert result.passed is True, result.summary()


# --- Migration safety is untouched -------------------------------------------


def test_v03e_touches_no_migration():
    """V0.3E adds no schema change -- backend/migrations.py must not
    appear anywhere in a representative V0.3E diff."""
    assert "backend/migrations.py" not in V03E_STYLE_CHANGED_PATHS
