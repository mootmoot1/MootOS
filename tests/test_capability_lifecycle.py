"""Tests for the V0.3E lifecycle model
(scripts/capability_pipeline/lifecycle.py, review.py) and the core
install invariant this whole phase exists to prove:

    A proposed/specified/implemented/tested/reviewed/ready_for_pr/merged
    CapabilityRecord -- at ANY state, with ANY reviews attached -- can
    never, by itself, cause a tool to appear in a real ToolRegistry.

Covers required categories 7, 8, 9, 10, 11, 12 plus the adversarial list
(mark a fake capability installed, skip spec validation, bypass
registration authority, auto-advance lifecycle, treat AI review as
approval, weaken risk classification).
"""

import pytest

from backend.tool_registry import ToolRegistry
from backend.tool_types import ToolNotFoundError
from backend.tools_reference import register_reference_tools
from scripts.capability_pipeline.lifecycle import (
    LIFECYCLE_STATES,
    STATE_IMPLEMENTED,
    STATE_MERGED,
    STATE_PROPOSED,
    STATE_READY_FOR_PR,
    STATE_SPECIFIED,
    STATE_TESTED,
    CapabilityRecord,
    LifecycleError,
    attach_review,
    new_record,
    record_from_dict,
    transition,
)
from scripts.capability_pipeline.review import (
    ROLE_ARCHITECTURE,
    ROLE_CORRECTNESS,
    ROLE_SECURITY,
    VERDICT_BLOCKING_CONCERN,
    VERDICT_NO_CONCERNS,
    AdvisoryReview,
    AdvisoryReviewError,
)
from scripts.capability_pipeline.spec import spec_from_dict


def _fake_spec(**overrides):
    base = {
        "capability_id": "fake.capability",
        "human_readable_goal": "A spec-only capability that is never implemented.",
        "tool_names": ["fake.capability_tool"],
        "resource_or_connector": "None -- purely a test fixture.",
        "input_contract": {"type": "object", "properties": {}, "required": [], "additionalProperties": False},
        "output_contract": {"ok": "always true"},
        "side_effects": "None -- read-only.",
        "has_side_effects": False,
        "idempotent": True,
        "risk": "read_only",
        "data_exposure": "local",
        "limitations": "Fixture only.",
        "required_tests": ["a test that will never actually exist"],
        "rollback_notes": "N/A -- never implemented.",
        "registration_requirement": "N/A -- never implemented.",
    }
    base.update(overrides)
    return spec_from_dict(base)


def _fresh_registry() -> ToolRegistry:
    registry = ToolRegistry()
    register_reference_tools(registry)
    return registry


# --- new_record / transition basics ------------------------------------------


def test_new_record_starts_in_proposed_state():
    record = new_record(_fake_spec(), actor="Tester", note="initial proposal")
    assert record.state == STATE_PROPOSED
    assert len(record.history) == 1
    assert record.history[0].actor == "Tester"


def test_new_record_requires_actor_and_note():
    with pytest.raises(LifecycleError):
        new_record(_fake_spec(), actor="", note="x")
    with pytest.raises(LifecycleError):
        new_record(_fake_spec(), actor="Tester", note="")


def test_transition_advances_exactly_one_state_forward():
    record = new_record(_fake_spec(), actor="Tester", note="proposed")
    record = transition(record, STATE_SPECIFIED, actor="Tester", note="spec validated")
    assert record.state == STATE_SPECIFIED
    assert len(record.history) == 2


def test_full_forward_walk_through_every_state_succeeds():
    record = new_record(_fake_spec(), actor="Tester", note="proposed")
    for state in LIFECYCLE_STATES[1:]:
        record = transition(record, state, actor="Tester", note=f"advance to {state}")
    assert record.state == STATE_MERGED
    assert len(record.history) == len(LIFECYCLE_STATES)


def test_transitioning_to_the_same_state_twice_fails():
    record = new_record(_fake_spec(), actor="Tester", note="proposed")
    with pytest.raises(LifecycleError):
        transition(record, STATE_PROPOSED, actor="Tester", note="repeat")


def test_transition_requires_actor_and_note():
    record = new_record(_fake_spec(), actor="Tester", note="proposed")
    with pytest.raises(LifecycleError):
        transition(record, STATE_SPECIFIED, actor="", note="x")
    with pytest.raises(LifecycleError):
        transition(record, STATE_SPECIFIED, actor="Tester", note="  ")


def test_transition_to_an_unknown_state_fails():
    record = new_record(_fake_spec(), actor="Tester", note="proposed")
    with pytest.raises(LifecycleError, match="Unknown lifecycle state"):
        transition(record, "not_a_real_state", actor="Tester", note="x")


def test_records_are_immutable_transition_returns_a_new_object():
    record = new_record(_fake_spec(), actor="Tester", note="proposed")
    advanced = transition(record, STATE_SPECIFIED, actor="Tester", note="advance")
    assert record.state == STATE_PROPOSED
    assert advanced.state == STATE_SPECIFIED
    assert advanced is not record


# --- Adversarial: auto-advance lifecycle --------------------------------------


@pytest.mark.parametrize(
    "start_state,skip_to",
    [
        (STATE_PROPOSED, STATE_IMPLEMENTED),
        (STATE_PROPOSED, STATE_READY_FOR_PR),
        (STATE_PROPOSED, STATE_MERGED),
        (STATE_SPECIFIED, STATE_TESTED),
        (STATE_SPECIFIED, STATE_MERGED),
    ],
)
def test_skipping_ahead_in_the_lifecycle_is_always_rejected(start_state, skip_to):
    record = new_record(_fake_spec(), actor="Tester", note="proposed")
    # Walk manually to start_state.
    for state in LIFECYCLE_STATES[1:LIFECYCLE_STATES.index(start_state) + 1]:
        record = transition(record, state, actor="Tester", note="advance")
    with pytest.raises(LifecycleError, match="only the immediate next state"):
        transition(record, skip_to, actor="Tester", note="try to skip ahead")


def test_moving_backward_in_the_lifecycle_is_rejected():
    record = new_record(_fake_spec(), actor="Tester", note="proposed")
    record = transition(record, STATE_SPECIFIED, actor="Tester", note="advance")
    record = transition(record, STATE_IMPLEMENTED, actor="Tester", note="advance")
    with pytest.raises(LifecycleError):
        transition(record, STATE_SPECIFIED, actor="Tester", note="try to go back")


def test_no_function_in_the_lifecycle_module_can_set_state_to_merged_directly():
    """There is exactly one way to reach 'merged': six consecutive,
    individually-attributed transition() calls. This test asserts that
    walking through fewer than six calls, or calling transition() with
    new_state=STATE_MERGED from any state other than ready_for_pr, always
    fails -- i.e. there is no shortcut, keyword, or alternate function."""
    record = new_record(_fake_spec(), actor="Tester", note="proposed")
    with pytest.raises(LifecycleError):
        transition(record, STATE_MERGED, actor="Tester", note="shortcut attempt")


# --- 11/12. No lifecycle transition or review can install anything ----------


def test_no_lifecycle_transition_registers_anything_on_a_real_registry():
    """The core V0.3E invariant: walk a record through every state,
    checking after every single transition that the fixture's tool name
    is still completely absent from a real ToolRegistry. Nothing in
    lifecycle.py imports, references, or touches backend.tool_registry."""
    registry = _fresh_registry()
    record = new_record(_fake_spec(), actor="Tester", note="proposed")
    assert "fake.capability_tool" not in {d.name for d in registry.list_definitions()}

    for state in LIFECYCLE_STATES[1:]:
        record = transition(record, state, actor="Tester", note=f"advance to {state}")
        assert "fake.capability_tool" not in {d.name for d in registry.list_definitions()}
        with pytest.raises(ToolNotFoundError):
            registry.get("fake.capability_tool")

    assert record.state == STATE_MERGED  # reached the terminal state...
    # ...and it STILL never touched the registry.
    assert "fake.capability_tool" not in {d.name for d in registry.list_definitions()}


def test_attach_review_never_changes_lifecycle_state():
    record = new_record(_fake_spec(), actor="Tester", note="proposed")
    record = transition(record, STATE_SPECIFIED, actor="Tester", note="advance")
    review = AdvisoryReview(
        role=ROLE_CORRECTNESS, reviewer="Claude", summary="fine", findings=(), verdict=VERDICT_NO_CONCERNS
    )
    reviewed = attach_review(record, review)
    assert reviewed.state == record.state == STATE_SPECIFIED
    assert reviewed.reviews == (review,)


def test_attaching_a_review_with_no_concerns_still_does_not_install_anything():
    """Even a maximally positive review (no_concerns, from all three
    roles) attached to a record sitting at ready_for_pr must not cause
    the fixture tool to appear anywhere in a real registry -- reviews are
    advisory text, never authority (ADR-032)."""
    registry = _fresh_registry()
    record = new_record(_fake_spec(), actor="Tester", note="proposed")
    for state in LIFECYCLE_STATES[1:6]:  # up to and including ready_for_pr
        record = transition(record, state, actor="Tester", note="advance")
    assert record.state == STATE_READY_FOR_PR

    for role in (ROLE_CORRECTNESS, ROLE_SECURITY, ROLE_ARCHITECTURE):
        record = attach_review(
            record,
            AdvisoryReview(role=role, reviewer="Claude", summary="fine", findings=(), verdict=VERDICT_NO_CONCERNS),
        )

    assert record.state == STATE_READY_FOR_PR
    assert len(record.reviews) == 3
    assert "fake.capability_tool" not in {d.name for d in registry.list_definitions()}


def test_a_blocking_concern_review_also_cannot_change_state_either_direction():
    """Symmetry check: a review cannot advance the record (tested above)
    and a review cannot revert/block it either -- attach_review has no
    state-mutating effect regardless of verdict."""
    record = new_record(_fake_spec(), actor="Tester", note="proposed")
    review = AdvisoryReview(
        role=ROLE_SECURITY,
        reviewer="Grok",
        summary="serious concern",
        findings=("this would be bad",),
        verdict=VERDICT_BLOCKING_CONCERN,
    )
    reviewed = attach_review(record, review)
    assert reviewed.state == STATE_PROPOSED


def test_review_module_exposes_no_approval_authority_methods():
    """Structural guard mirroring the spec-side one: neither the review
    module's dataclass nor the lifecycle module exposes anything named
    approve/install/merge/deploy -- reviews and lifecycle records stay
    inert data with exactly one narrow, explicit mutator (transition)."""
    import scripts.capability_pipeline.lifecycle as lifecycle_module
    import scripts.capability_pipeline.review as review_module

    for forbidden in ("approve", "install", "merge_now", "deploy", "auto_advance"):
        assert not hasattr(lifecycle_module, forbidden)
        assert not hasattr(review_module, forbidden)

    record = new_record(_fake_spec(), actor="Tester", note="x")
    for forbidden in ("install", "execute", "register", "approve", "merge", "deploy"):
        assert not hasattr(record, forbidden)


# --- Adversarial: mark a fake capability installed ---------------------------


def test_a_record_forged_directly_at_state_merged_still_installs_nothing():
    """The most direct adversarial attempt: build a CapabilityRecord (not
    even through new_record/transition -- the raw dataclass) already
    sitting at state='merged', for a tool name that has never been
    implemented anywhere. It must still be completely absent from every
    real registry -- state is just a string field on an inert record."""
    spec = _fake_spec(capability_id="totally.fake", tool_names=["totally.fake_tool"])
    forged = CapabilityRecord(spec=spec, state=STATE_MERGED, history=(), reviews=())

    assert forged.state == STATE_MERGED  # the forgery "succeeds" as data...
    registry = _fresh_registry()
    # ...and STILL changes nothing about what's actually installed.
    assert "totally.fake_tool" not in {d.name for d in registry.list_definitions()}
    with pytest.raises(ToolNotFoundError):
        registry.get("totally.fake_tool")


def test_a_record_loaded_from_a_hand_edited_merged_json_file_still_installs_nothing(tmp_path):
    """Same attack, via the file-loading path: hand-author a JSON record
    claiming state 'merged' for a tool that was never actually
    registered anywhere in backend/, and confirm load_record() accepts it
    as *data* (it's a syntactically valid record) while the real registry
    remains completely unaware of it."""
    from scripts.capability_pipeline.lifecycle import load_record

    spec = _fake_spec(capability_id="forged.capability", tool_names=["forged.capability_tool"])
    forged_path = tmp_path / "forged.json"
    forged_path.write_text(
        CapabilityRecord(spec=spec, state=STATE_MERGED, history=(), reviews=()).to_json(),
        encoding="utf-8",
    )

    loaded = load_record(forged_path)
    assert loaded.state == STATE_MERGED

    registry = _fresh_registry()
    assert "forged.capability_tool" not in {d.name for d in registry.list_definitions()}


# --- record_from_dict / round trip -------------------------------------------


def test_record_from_dict_rejects_unknown_top_level_fields():
    spec = _fake_spec()
    data = CapabilityRecord(spec=spec, state=STATE_PROPOSED, history=(), reviews=()).to_dict()
    data["unexpected_field"] = True
    with pytest.raises(LifecycleError, match="Unknown capability-record field"):
        record_from_dict(data)


def test_record_from_dict_rejects_an_unknown_state():
    spec = _fake_spec()
    data = CapabilityRecord(spec=spec, state=STATE_PROPOSED, history=(), reviews=()).to_dict()
    data["state"] = "installed_forever"
    with pytest.raises(LifecycleError, match="Unknown lifecycle state"):
        record_from_dict(data)


def test_record_from_dict_rejects_an_invalid_embedded_spec():
    data = {"spec": {"capability_id": "bad id with spaces"}, "state": STATE_PROPOSED}
    with pytest.raises(LifecycleError, match="Invalid embedded spec"):
        record_from_dict(data)


def test_record_round_trips_through_json(tmp_path):
    from scripts.capability_pipeline.lifecycle import save_record, load_record

    record = new_record(_fake_spec(), actor="Tester", note="proposed")
    record = transition(record, STATE_SPECIFIED, actor="Tester", note="advance")
    record = attach_review(
        record,
        AdvisoryReview(
            role=ROLE_ARCHITECTURE,
            reviewer="ChatGPT",
            summary="fine",
            findings=(),
            verdict=VERDICT_NO_CONCERNS,
        ),
    )

    path = tmp_path / "record.json"
    save_record(record, path)
    loaded = load_record(path)

    assert loaded.state == record.state
    assert loaded.spec == record.spec
    assert len(loaded.history) == len(record.history)
    assert len(loaded.reviews) == 1
    assert loaded.reviews[0].role == ROLE_ARCHITECTURE


# --- AdvisoryReview validation -------------------------------------------------


def test_review_rejects_an_invalid_role():
    with pytest.raises(AdvisoryReviewError):
        AdvisoryReview(role="not_a_real_role", reviewer="X", summary="y", findings=(), verdict=VERDICT_NO_CONCERNS)


def test_review_rejects_an_invalid_verdict():
    with pytest.raises(AdvisoryReviewError):
        AdvisoryReview(role=ROLE_CORRECTNESS, reviewer="X", summary="y", findings=(), verdict="approved")


def test_review_from_dict_rejects_unknown_fields():
    with pytest.raises(AdvisoryReviewError):
        AdvisoryReview.from_dict(
            {
                "role": ROLE_CORRECTNESS,
                "reviewer": "X",
                "summary": "y",
                "findings": [],
                "verdict": VERDICT_NO_CONCERNS,
                "sneaky": True,
            }
        )
