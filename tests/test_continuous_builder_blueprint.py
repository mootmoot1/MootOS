"""Tests for inert Continuous Builder blueprint domain models."""

from dataclasses import FrozenInstanceError, replace

import pytest

from backend.continuous_builder.blueprint import (
    SCHEMA_VERSION,
    BlueprintError,
    BuildBudget,
    ContinuousBuilderBlueprint,
    RollbackContract,
    SliceBlueprint,
    SystemBlueprint,
)


def make_slice(**changes):
    values = dict(
        slice_id="CB-001", version="1", system_id="builder",
        objective="Define bounded planning models.",
        acceptance_criteria=("Models are immutable.",),
        hard_dependencies=(), soft_dependencies=(),
        requested_capabilities=("planning",), expected_risk="low",
        allowed_paths=("backend/continuous_builder/blueprint.py",),
        forbidden_paths=("backend/db.py",),
        required_tests=("tests/test_continuous_builder_blueprint.py",),
        required_gates=("protected_core",),
        budget=BuildBudget(1, 0, 30, 4096),
        rollback=RollbackContract("Revert the slice.", ("Run tests.",)),
        human_checkpoints=("Before persistence.",),
        non_goals=("No execution.",), authority_classes=(),
    )
    values.update(changes)
    return SliceBlueprint(**values)


def make_blueprint(slices=None, **changes):
    values = dict(
        schema_version=SCHEMA_VERSION, blueprint_id="continuous-builder",
        blueprint_version="phase-1", source_commit="a" * 40,
        goal="Plan bounded work without executing it.",
        systems=(SystemBlueprint("builder", "Builder", "Planning only."),),
        slices=tuple(slices or (make_slice(),)),
    )
    values.update(changes)
    return ContinuousBuilderBlueprint(**values)


def test_blueprint_is_immutable_deterministic_and_inert():
    first = make_blueprint()
    second = make_blueprint()
    assert first.canonical_bytes() == second.canonical_bytes()
    assert "executor" not in first.to_dict()
    assert "dispatch" not in first.to_dict()
    with pytest.raises(FrozenInstanceError):
        first.goal = "changed"


@pytest.mark.parametrize("change", [
    {"expected_risk": "root"},
    {"priority_class": "model_selected"},
    {"allowed_paths": ("../escape",)},
    {"promotion_eligibility": "automatic"},
])
def test_slice_rejects_unsupported_or_unsafe_values(change):
    with pytest.raises(BlueprintError):
        make_slice(**change)


def test_blueprint_rejects_unknown_system_and_schema_version():
    with pytest.raises(BlueprintError, match="unknown system"):
        make_blueprint(slices=(make_slice(system_id="missing"),))
    with pytest.raises(BlueprintError, match="schema version"):
        make_blueprint(schema_version="99")


def test_nested_collections_are_frozen_and_bounded():
    item = make_slice(allowed_paths=["backend/continuous_builder/model.py"])
    assert isinstance(item.allowed_paths, tuple)
    with pytest.raises(BlueprintError, match="item bound"):
        make_slice(non_goals=tuple(str(index) for index in range(65)))


def test_secret_like_text_and_mutated_derived_values_fail_closed():
    with pytest.raises(BlueprintError, match="secret-like"):
        make_slice(objective="api_key=do-not-store")
    original = make_blueprint()
    forged = replace(original, slices=(replace(make_slice(), version="2"),))
    assert original.canonical_bytes() != forged.canonical_bytes()
