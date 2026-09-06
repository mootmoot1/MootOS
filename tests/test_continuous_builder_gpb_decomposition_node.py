"""Tests for GP-B2 Decomposition Node Contract."""

import pytest

from backend.continuous_builder.gpa_eval_schema import (
    AUTHORITY_FLAGS,
    GPAEvalSchemaError,
    UNKNOWN,
)
from backend.continuous_builder.gpb_decomposition_node import (
    DecompositionNode,
    DecompositionNodeError,
    NODE_SCHEMA_VERSION,
    create_decomposition_node,
    decomposition_node_is_planning_only,
)


def _node(**overrides):
    values = dict(
        node_id="n_goal_001",
        parent_id=None,
        level="goal",
        node_type="decompose",
        title="Fix clamp bug",
        objective="Correct WidgetCounter overflow",
        rationale="Isolated defect with clear acceptance",
        depends_on=(),
        affected_components=("fixture.nb_001",),
        candidate_allowed_scope=(
            "tests/fixtures/gpa_eval/nb_001/widget_counter.py",
        ),
        inherited_forbidden_scope=(
            "backend/continuous_builder/trusted_policy.py",
        ),
        acceptance_checkpoint=("count never exceeds capacity",),
        complexity_estimate="small",
        uncertainty=UNKNOWN,
        requires_escalation=False,
        escalation_reasons=(),
        children=("n_atomic_001",),
    )
    values.update(overrides)
    return create_decomposition_node(**values)


def test_deterministic_node_digest():
    assert _node().node_sha256 == _node().node_sha256


def test_zero_authority():
    n = _node()
    for name in AUTHORITY_FLAGS:
        assert getattr(n, name) is False
    assert n.execution_authorized is False


def test_planning_only_helper():
    assert decomposition_node_is_planning_only() is True


def test_schema_version():
    assert _node().schema_version == NODE_SCHEMA_VERSION


def test_unknown_uncertainty_allowed():
    n = _node(uncertainty=UNKNOWN)
    assert n.uncertainty == UNKNOWN


def test_rejects_self_parent():
    with pytest.raises(DecompositionNodeError, match="parent itself"):
        _node(node_id="n_a", parent_id="n_a")


def test_rejects_self_dependency():
    with pytest.raises(DecompositionNodeError, match="depend on itself"):
        _node(node_id="n_a", depends_on=("n_a",))


def test_rejects_unsupported_level():
    with pytest.raises(DecompositionNodeError, match="level"):
        _node(level="ceremony_layer")


def test_rejects_unsupported_type():
    with pytest.raises(DecompositionNodeError, match="node_type"):
        _node(node_type="auto_merge")


def test_rejects_scope_forbidden_intersection():
    path = "tests/fixtures/gpa_eval/nb_001/widget_counter.py"
    with pytest.raises(DecompositionNodeError, match="intersects"):
        _node(
            candidate_allowed_scope=(path,),
            inherited_forbidden_scope=(path,),
        )


def test_escalation_requires_reasons():
    with pytest.raises(DecompositionNodeError, match="escalation_reasons"):
        _node(requires_escalation=True, escalation_reasons=())


def test_reasons_require_escalation_flag():
    with pytest.raises(DecompositionNodeError, match="requires_escalation"):
        _node(requires_escalation=False, escalation_reasons=("widen",))


def test_create_canonicalizes_children_order():
    n = _node(children=("n_b", "n_a"))
    assert n.children == ("n_a", "n_b")


def test_forged_digest_rejected():
    n = _node()
    object.__setattr__(n, "title", "tampered")
    with pytest.raises(DecompositionNodeError, match="node_sha256 mismatch"):
        n.__post_init__()


def test_cannot_construct_without_token():
    with pytest.raises(DecompositionNodeError, match="trusted construction"):
        DecompositionNode(
            schema_version=NODE_SCHEMA_VERSION,
            node_id="n_x",
            parent_id=None,
            level="atomic",
            node_type="implement",
            title="t",
            objective="o",
            rationale="r",
            depends_on=(),
            affected_components=(),
            candidate_allowed_scope=(),
            inherited_forbidden_scope=(),
            acceptance_checkpoint=(),
            complexity_estimate="small",
            uncertainty=UNKNOWN,
            requires_escalation=False,
            escalation_reasons=(),
            children=(),
            generator_version="gpb-decomposition-node-generator-v1",
            node_sha256="c" * 64,
        )


def test_rejects_path_traversal_in_scope():
    with pytest.raises(GPAEvalSchemaError):
        _node(candidate_allowed_scope=("../evil.py",))


def test_variable_depth_levels_supported():
    for level in ("goal", "slice", "atomic", "investigation"):
        n = _node(node_id=f"n_{level}", level=level, children=())
        assert n.level == level
