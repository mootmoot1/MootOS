"""Tests for the V0.3E capability specification schema
(scripts/capability_pipeline/spec.py).

Covers required categories 1-6 from the V0.3E task plus adversarial
attempts to skip validation by constructing the dataclass directly.
"""

import pytest

from scripts.capability_pipeline.spec import CapabilitySpec, CapabilitySpecError, spec_from_dict


def _good_spec_dict(**overrides):
    base = {
        "capability_id": "tasks.status_insight",
        "human_readable_goal": "Report Task counts by status without manual counting.",
        "tool_names": ["tasks.status_summary"],
        "resource_or_connector": "Task resource, local SQLite storage; no external connector.",
        "input_contract": {
            "type": "object",
            "properties": {"project": {"type": "string"}},
            "required": [],
            "additionalProperties": False,
        },
        "output_contract": {"counts": "status -> count mapping", "total": "sum of counts"},
        "side_effects": "None -- read-only.",
        "has_side_effects": False,
        "idempotent": True,
        "risk": "read_only",
        "data_exposure": "local",
        "limitations": "Counts only, no task content.",
        "required_tests": ["counts every status including zero"],
        "rollback_notes": "Remove the registration call and delete the tool module.",
        "registration_requirement": "Explicit call added to backend/tool_registry.py.",
        "dependencies": ["tasks.list"],
        "protected_core_impact": ["backend/tool_registry.py"],
        "requires_human_registration_review": True,
    }
    base.update(overrides)
    return base


# --- 1. A valid capability spec passes validation -----------------------------


def test_a_valid_spec_passes_validation():
    spec = spec_from_dict(_good_spec_dict())
    assert spec.capability_id == "tasks.status_insight"
    assert spec.tool_names == ("tasks.status_summary",)
    assert spec.risk == "read_only"


def test_a_valid_spec_round_trips_through_to_dict_and_back():
    spec = spec_from_dict(_good_spec_dict())
    round_tripped = spec_from_dict(spec.to_dict())
    assert round_tripped == spec


def test_a_spec_with_no_protected_core_impact_and_review_flag_false_is_valid():
    spec = spec_from_dict(
        _good_spec_dict(protected_core_impact=[], requires_human_registration_review=False)
    )
    assert spec.protected_core_impact == ()
    assert spec.requires_human_registration_review is False


def test_dependencies_may_be_empty():
    spec = spec_from_dict(_good_spec_dict(dependencies=[]))
    assert spec.dependencies == ()


# --- 2. Malformed/unknown fields fail closed ----------------------------------


def test_an_unknown_top_level_field_is_rejected():
    with pytest.raises(CapabilitySpecError, match="Unknown capability-spec field"):
        spec_from_dict(_good_spec_dict(**{"totally_made_up_field": "x"}))


def test_a_non_mapping_spec_is_rejected():
    with pytest.raises(CapabilitySpecError):
        spec_from_dict(["not", "a", "mapping"])


def test_input_contract_must_declare_type_object():
    with pytest.raises(CapabilitySpecError, match="type: 'object'"):
        spec_from_dict(_good_spec_dict(input_contract={"type": "array"}))


def test_input_contract_must_declare_properties_and_required():
    with pytest.raises(CapabilitySpecError):
        spec_from_dict(_good_spec_dict(input_contract={"type": "object"}))


def test_output_contract_must_be_non_empty():
    with pytest.raises(CapabilitySpecError, match="output_contract"):
        spec_from_dict(_good_spec_dict(output_contract={}))


def test_output_contract_entries_need_non_empty_descriptions():
    with pytest.raises(CapabilitySpecError):
        spec_from_dict(_good_spec_dict(output_contract={"counts": ""}))


def test_required_tests_cannot_be_empty():
    with pytest.raises(CapabilitySpecError, match="required_tests"):
        spec_from_dict(_good_spec_dict(required_tests=[]))


def test_limitations_cannot_be_blank():
    with pytest.raises(CapabilitySpecError, match="limitations"):
        spec_from_dict(_good_spec_dict(limitations="   "))


def test_rollback_notes_cannot_be_blank():
    with pytest.raises(CapabilitySpecError, match="rollback_notes"):
        spec_from_dict(_good_spec_dict(rollback_notes=""))


def test_registration_requirement_cannot_be_blank():
    with pytest.raises(CapabilitySpecError, match="registration_requirement"):
        spec_from_dict(_good_spec_dict(registration_requirement=""))


def test_has_side_effects_must_be_a_real_boolean():
    with pytest.raises(CapabilitySpecError, match="has_side_effects"):
        spec_from_dict(_good_spec_dict(has_side_effects="yes"))


# --- 3. Missing risk fails ------------------------------------------------------


def test_missing_risk_field_fails():
    data = _good_spec_dict()
    del data["risk"]
    with pytest.raises(CapabilitySpecError, match="Malformed capability spec"):
        spec_from_dict(data)


def test_invalid_risk_value_fails():
    with pytest.raises(CapabilitySpecError, match="'risk' must be one of"):
        spec_from_dict(_good_spec_dict(risk="super_dangerous"))


def test_invalid_data_exposure_value_fails():
    with pytest.raises(CapabilitySpecError, match="'data_exposure' must be one of"):
        spec_from_dict(_good_spec_dict(data_exposure="somewhere_else"))


# --- 4. Invalid capability/tool ids fail ----------------------------------------


@pytest.mark.parametrize(
    "bad_id",
    [
        "NoDotsNoLower",
        "has spaces.here",
        "trailing.dot.",
        ".leading.dot",
        "UPPERCASE.id",
        "onlyoneword",
        "",
        "123.starts_with_digit",
    ],
)
def test_invalid_capability_id_shapes_are_rejected(bad_id):
    with pytest.raises(CapabilitySpecError):
        spec_from_dict(_good_spec_dict(capability_id=bad_id))


@pytest.mark.parametrize("bad_tool_name", ["NotDotted", "has spaces.tool", ""])
def test_invalid_tool_name_shapes_are_rejected(bad_tool_name):
    with pytest.raises(CapabilitySpecError):
        spec_from_dict(_good_spec_dict(tool_names=[bad_tool_name]))


def test_tool_names_cannot_be_empty():
    with pytest.raises(CapabilitySpecError, match="tool_names"):
        spec_from_dict(_good_spec_dict(tool_names=[]))


# --- 5. A write-capable spec cannot be mislabeled read-only ---------------------


def test_read_only_risk_with_side_effects_true_is_rejected():
    with pytest.raises(CapabilitySpecError, match="cannot declare"):
        spec_from_dict(_good_spec_dict(risk="read_only", has_side_effects=True))


def test_internal_write_risk_with_side_effects_true_is_allowed():
    spec = spec_from_dict(
        _good_spec_dict(
            risk="internal_write",
            has_side_effects=True,
            side_effects="Creates exactly one new record once approved.",
        )
    )
    assert spec.risk == "internal_write"
    assert spec.has_side_effects is True


def test_high_risk_with_side_effects_true_is_allowed_by_the_schema():
    """The schema itself only blocks the read_only+side-effects
    combination; it does not forbid declaring high_risk -- authorization
    behavior for high_risk tools is enforced elsewhere (backend/
    tool_executor.py), unconditionally, regardless of what any spec says."""
    spec = spec_from_dict(
        _good_spec_dict(
            risk="high_risk",
            has_side_effects=True,
            side_effects="Would perform an irreversible external action.",
        )
    )
    assert spec.risk == "high_risk"


# --- 6. Protected-core impact is surfaced ---------------------------------------


def test_protected_core_impact_without_the_review_flag_is_rejected():
    with pytest.raises(CapabilitySpecError, match="requires_human_registration_review"):
        spec_from_dict(
            _good_spec_dict(
                protected_core_impact=["backend/tool_registry.py"],
                requires_human_registration_review=False,
            )
        )


def test_protected_core_impact_with_the_review_flag_true_is_accepted():
    spec = spec_from_dict(
        _good_spec_dict(
            protected_core_impact=["backend/tool_registry.py"],
            requires_human_registration_review=True,
        )
    )
    assert spec.protected_core_impact == ("backend/tool_registry.py",)
    assert spec.requires_human_registration_review is True


# --- Adversarial: constructing the dataclass directly cannot skip validation --


def test_constructing_the_dataclass_directly_still_validates():
    """Validation lives in __post_init__, not only in spec_from_dict -- so
    bypassing the dict-based entry point cannot produce an invalid spec."""
    good = _good_spec_dict()
    good.pop("risk")
    with pytest.raises((CapabilitySpecError, TypeError)):
        CapabilitySpec(risk="not_a_real_risk", **good)


def test_constructing_the_dataclass_directly_still_enforces_the_mislabel_rule():
    good = _good_spec_dict(risk="read_only", has_side_effects=True)
    good.pop("risk")
    good.pop("has_side_effects")
    with pytest.raises(CapabilitySpecError, match="cannot declare"):
        CapabilitySpec(risk="read_only", has_side_effects=True, **good)


def test_a_capability_spec_object_has_no_install_or_execute_method():
    """Structural guard: a CapabilitySpec is inert data. If a future edit
    ever adds an install()/execute()/register() method to this class,
    that is exactly the "capability self-installation" this phase must
    never introduce -- this test exists to catch that at the source."""
    spec = spec_from_dict(_good_spec_dict())
    for forbidden in ("install", "execute", "register", "approve", "merge", "deploy"):
        assert not hasattr(spec, forbidden), f"CapabilitySpec must not expose a {forbidden}() method"
