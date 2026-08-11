"""V0.3E proof #2: installation invariants and V0.3A/V0.3B/V0.3D
integration for the projects.overview capability.

The point of these tests is not that projects.overview works (that is
tests/test_tools_project_insight.py's job) -- it is that **nothing except
explicit registration in merged code installs it**, and that the derived
V0.3A/V0.3B views follow the registry rather than any artifact, spec, or
lifecycle state.

Covers required categories 1-5, 9, and 10 for proof #2. The generic
lifecycle/spec invariants proven once in proof #1
(tests/test_capability_lifecycle.py, tests/test_capability_spec.py)
are not re-proven here; this file covers what is specific to proof #2.
"""

from pathlib import Path

import pytest

from backend.capability_catalog import (
    build_capability_index,
    build_tool_catalog,
    render_capability_manifest,
)
from backend.gap_reasoning import resolve_requirements
from backend.tool_registry import ToolRegistry, build_default_registry
from backend.tool_types import ToolNotFoundError
from backend.tools_project_insight import register_v03e_proof2_tools
from backend.tools_reference import register_reference_tools
from backend.tools_task_summary import register_v03e_tools
from backend.tools_web import register_v03c_tools
from scripts.capability_pipeline.lifecycle import (
    LIFECYCLE_STATES,
    STATE_MERGED,
    CapabilityRecord,
    load_record,
    new_record,
    transition,
)
from scripts.capability_pipeline.review import (
    ROLE_ARCHITECTURE,
    ROLE_CORRECTNESS,
    ROLE_SECURITY,
    VERDICT_NO_CONCERNS,
    AdvisoryReview,
)
from scripts.capability_pipeline.spec import spec_from_dict
from scripts.gates import policy
from scripts.gates.protected_paths import evaluate_changed_paths
from scripts.gates.registration_authority import evaluate_files as evaluate_registration_authority
from scripts.gates.risk_metadata import evaluate as evaluate_risk_metadata
from scripts.gates.secret_scan import evaluate_paths as evaluate_secret_scan


REPO_ROOT = Path(__file__).resolve().parent.parent
RECORD_PATH = REPO_ROOT / "capability_specs" / "projects_overview.json"
TOOL_NAME = "projects.overview"
CAPABILITY_ID = "projects.insight"


def _pre_proof2_registry() -> ToolRegistry:
    """The registry exactly as merged on origin/main before proof #2:
    V0.2A reference tools + V0.3C + V0.3E proof #1, and nothing else."""
    registry = ToolRegistry()
    register_reference_tools(registry)
    register_v03c_tools(registry)
    register_v03e_tools(registry)
    return registry


def _with_proof2_registry() -> ToolRegistry:
    registry = _pre_proof2_registry()
    register_v03e_proof2_tools(registry)
    return registry


# --- 1/2. Absent before registration; module existence installs nothing ------


def test_capability_is_absent_from_every_derived_view_before_registration():
    registry = _pre_proof2_registry()

    assert TOOL_NAME not in {d.name for d in registry.list_definitions()}
    assert TOOL_NAME not in {entry["name"] for entry in build_tool_catalog(registry)}
    assert CAPABILITY_ID not in {entry["id"] for entry in build_capability_index(registry)}
    assert TOOL_NAME not in render_capability_manifest(registry)
    with pytest.raises(ToolNotFoundError):
        registry.get(TOOL_NAME)


def test_importing_the_implementation_module_does_not_install_it():
    """backend.tools_project_insight and backend.project_insight are both
    imported at the top of this file. If import alone had any registering
    side effect, a freshly-built pre-proof-#2 registry would show it."""
    import backend.project_insight  # noqa: F401  (import IS the test)
    import backend.tools_project_insight  # noqa: F401

    assert TOOL_NAME not in {d.name for d in _pre_proof2_registry().list_definitions()}


# --- 3. Spec / lifecycle / review artifacts install nothing ------------------


def test_the_committed_proof2_record_is_valid_and_not_yet_merged():
    record = load_record(RECORD_PATH)
    assert record.spec.capability_id == CAPABILITY_ID
    assert record.spec.tool_names == (TOOL_NAME,)
    # Proof #2 deliberately stops before `merged` -- nothing in this
    # session opens a PR or merges.
    assert record.state != STATE_MERGED


def test_the_committed_spec_artifact_revalidates_from_disk():
    """The spec inside the record must still pass the same schema
    validation it was created under -- a hand-edit that broke a rule
    would fail here rather than sit silently in the repository."""
    record = load_record(RECORD_PATH)
    assert spec_from_dict(record.spec.to_dict()) == record.spec


def test_the_committed_record_carries_all_three_distinct_review_roles():
    record = load_record(RECORD_PATH)
    roles = {review.role for review in record.reviews}
    assert roles == {ROLE_CORRECTNESS, ROLE_SECURITY, ROLE_ARCHITECTURE}


def test_no_lifecycle_state_of_the_real_proof2_spec_installs_the_capability():
    """Walk the REAL proof #2 spec through every lifecycle state,
    including `merged`, against a pre-proof-#2 registry -- the tool must
    stay absent at every single step. Lifecycle state is inert data."""
    spec = load_record(RECORD_PATH).spec
    registry = _pre_proof2_registry()
    record = new_record(spec, actor="Tester", note="invariant walk")

    for state in LIFECYCLE_STATES[1:]:
        record = transition(record, state, actor="Tester", note=f"advance to {state}")
        assert TOOL_NAME not in {d.name for d in registry.list_definitions()}
        assert CAPABILITY_ID not in {e["id"] for e in build_capability_index(registry)}

    assert record.state == STATE_MERGED
    with pytest.raises(ToolNotFoundError):
        registry.get(TOOL_NAME)


def test_a_forged_merged_record_for_proof2_installs_nothing():
    """The direct attack: construct a record already at `merged` for the
    real proof #2 spec, bypassing transition() entirely."""
    spec = load_record(RECORD_PATH).spec
    forged = CapabilityRecord(spec=spec, state=STATE_MERGED, history=(), reviews=())

    assert forged.state == STATE_MERGED
    assert TOOL_NAME not in {d.name for d in _pre_proof2_registry().list_definitions()}


def test_attaching_more_positive_reviews_installs_nothing():
    record = load_record(RECORD_PATH)
    registry = _pre_proof2_registry()

    from scripts.capability_pipeline.lifecycle import attach_review

    for role in (ROLE_CORRECTNESS, ROLE_SECURITY, ROLE_ARCHITECTURE):
        record = attach_review(
            record,
            AdvisoryReview(
                role=role,
                reviewer="Enthusiastic Reviewer",
                summary="ship it",
                findings=(),
                verdict=VERDICT_NO_CONCERNS,
            ),
        )

    assert TOOL_NAME not in {d.name for d in registry.list_definitions()}


def test_the_gap_report_artifact_installs_nothing():
    """A Gap Report naming projects.insight as missing is advisory data;
    reading it cannot make the capability exist (ADR-030)."""
    import json

    gap_path = REPO_ROOT / "capability_specs" / "projects_overview.gap_report.json"
    report = json.loads(gap_path.read_text(encoding="utf-8"))

    assert CAPABILITY_ID in report["missing_capabilities"]
    assert TOOL_NAME not in {d.name for d in _pre_proof2_registry().list_definitions()}


# --- 4/5. Explicit registration installs it; absence removes it --------------


def test_explicit_registration_makes_it_appear_in_every_v03a_derived_view():
    registry = _with_proof2_registry()

    assert TOOL_NAME in {d.name for d in registry.list_definitions()}
    assert TOOL_NAME in {entry["name"] for entry in build_tool_catalog(registry)}
    index = {entry["id"]: entry for entry in build_capability_index(registry)}
    assert index[CAPABILITY_ID]["tools"] == [TOOL_NAME]
    assert TOOL_NAME in render_capability_manifest(registry)


def test_not_calling_the_registration_makes_it_disappear_again():
    """This is the rollback path, proven structurally: a registry built
    without the registration call -- exactly what reverting the one-line
    change to backend/tool_registry.py produces -- has no trace of the
    capability in any derived view, with no cleanup step required."""
    with_it = _with_proof2_registry()
    without_it = _pre_proof2_registry()

    assert TOOL_NAME in {d.name for d in with_it.list_definitions()}
    assert TOOL_NAME not in {d.name for d in without_it.list_definitions()}
    assert CAPABILITY_ID not in {e["id"] for e in build_capability_index(without_it)}
    assert TOOL_NAME not in render_capability_manifest(without_it)


def test_the_two_registries_do_not_leak_into_each_other():
    """Registries are independent objects -- registering on one must not
    retroactively affect another already-built one."""
    without_it = _pre_proof2_registry()
    _with_proof2_registry()  # build a second registry that DOES have it

    assert TOOL_NAME not in {d.name for d in without_it.list_definitions()}


def test_this_branch_registers_it_in_the_real_default_registry():
    """On THIS branch the registration line has been added, so the real
    build_default_registry() contains it. That is correct for this
    branch's own code -- it is not evidence that production has it until
    this branch is actually merged and deployed."""
    assert TOOL_NAME in {d.name for d in build_default_registry().list_definitions()}


# --- 9. V0.3B resolves missing before, installed after -----------------------


def test_gap_reasoning_resolves_the_capability_missing_before_registration():
    proposed = [{"capability": CAPABILITY_ID, "reason": "needed", "externally_blocked": False}]

    resolutions = resolve_requirements(proposed, _pre_proof2_registry())

    assert resolutions[0].installed is False
    assert resolutions[0].tools == ()


def test_gap_reasoning_resolves_the_capability_installed_after_registration():
    proposed = [{"capability": CAPABILITY_ID, "reason": "needed", "externally_blocked": False}]

    resolutions = resolve_requirements(proposed, _with_proof2_registry())

    assert resolutions[0].installed is True
    assert resolutions[0].tools == (TOOL_NAME,)


def test_the_gap_was_real_not_manufactured_by_naming():
    """The concern this test exists to answer: was projects.insight just a
    new dotted string invented to fabricate a gap, when an equivalent
    capability was already installed? No -- against the same pre-proof-#2
    registry, the deterministic resolver confirms projects.view IS
    installed while projects.insight is NOT. The two are distinguishable
    facts about the registry, not naming."""
    registry = _pre_proof2_registry()
    resolutions = resolve_requirements(
        [
            {"capability": "projects.view", "reason": "x", "externally_blocked": False},
            {"capability": CAPABILITY_ID, "reason": "y", "externally_blocked": False},
        ],
        registry,
    )

    by_capability = {item.capability: item for item in resolutions}
    assert by_capability["projects.view"].installed is True
    assert by_capability["projects.view"].tools == ("projects.list",)
    assert by_capability[CAPABILITY_ID].installed is False


# --- 10. V0.3D gates behave correctly ----------------------------------------


PROOF2_STYLE_CHANGED_PATHS = (
    "backend/tool_registry.py",
    "backend/project_insight.py",
    "backend/tools_project_insight.py",
    "backend/capability_catalog.py",
    "tests/test_tools_project_insight.py",
    "tests/test_capability_proof2_invariants.py",
    "capability_specs/projects_overview.json",
    "docs/CAPABILITY_BUILD_PIPELINE.md",
)


def test_protected_path_gate_flags_exactly_the_registry_edit():
    result = evaluate_changed_paths(PROOF2_STYLE_CHANGED_PATHS)

    assert result.passed is False
    assert result.violations == ("backend/tool_registry.py",)
    assert "FAIL" in result.summary()


def test_the_new_proof2_modules_are_not_protected_paths():
    """New capability modules must remain freely addable -- that is the
    property docs/GATES_AND_RELEASE_SAFETY.md §9 promises future
    capability work."""
    for path in ("backend/project_insight.py", "backend/tools_project_insight.py"):
        assert evaluate_changed_paths([path]).passed is True


def test_proof2_did_not_weaken_the_protected_path_policy():
    """Direct assertion against the real policy: proof #2 must not have
    removed backend/tool_registry.py (or the gates' own self-protection)
    to make its diff green."""
    assert "backend/tool_registry.py" in policy.DENIED_PATHS
    assert "scripts/gates/" in policy.DENIED_PATHS
    assert policy.ALLOWED_EXCEPTIONS == ()


def test_registration_authority_gate_is_clean_against_the_new_backend_files():
    files = [
        (relative, (REPO_ROOT / relative).read_text(encoding="utf-8"))
        for relative in (
            "backend/project_insight.py",
            "backend/tools_project_insight.py",
            "backend/tool_registry.py",
        )
    ]
    result = evaluate_registration_authority(files)
    assert result.passed is True, result.summary()


def test_the_new_tool_module_uses_registry_register_and_never_calls_an_executor():
    source = (REPO_ROOT / "backend" / "tools_project_insight.py").read_text(encoding="utf-8")
    assert "registry.register(" in source
    assert ".executor(" not in source


def test_risk_metadata_gate_still_passes_with_the_new_tool_registered():
    assert evaluate_risk_metadata(REPO_ROOT).passed is True


def test_secret_scan_gate_is_clean_against_every_new_proof2_file():
    new_paths = [
        "backend/project_insight.py",
        "backend/tools_project_insight.py",
        "tests/test_tools_project_insight.py",
        "tests/test_capability_proof2_invariants.py",
        "capability_specs/projects_overview.json",
        "capability_specs/projects_overview.gap_report.json",
        "scripts/capability_pipeline/build_gap_report_proof2.py",
        "scripts/capability_pipeline/build_proof2_record.py",
    ]
    result = evaluate_secret_scan(new_paths, REPO_ROOT)
    assert result.passed is True, result.summary()


def test_proof2_adds_no_migration():
    assert "backend/migrations.py" not in PROOF2_STYLE_CHANGED_PATHS
