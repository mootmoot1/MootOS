"""Adversarial / unit tests for GP-B1 Frozen Task Intent Contract."""

import pytest

from backend.continuous_builder.gpa_eval_schema import AUTHORITY_FLAGS, GPAEvalSchemaError
from backend.continuous_builder.gpb_task_contract import (
    FrozenTaskContract,
    TASK_CONTRACT_VERSION,
    TaskContractError,
    create_frozen_task_contract,
    task_contract_is_planning_only,
    task_contract_risk_is_descriptive_only,
)

TRUSTED_BASE = "b448dcaf679861b23cc690186fc96815776a6e3d"
BASELINE_DIGEST = "a" * 64


def _contract(**overrides):
    values = dict(
        task_contract_id="tc_narrow_bug_001",
        base_sha=TRUSTED_BASE,
        architecture_baseline_sha256=BASELINE_DIGEST,
        taxonomy_class_id="narrow_bug_fix",
        goal="Fix WidgetCounter.add() clamp bug",
        intent_summary="Correct overflow clamp without widening scope",
        allowed_scope=("tests/fixtures/gpa_eval/nb_001/widget_counter.py",),
        forbidden_scope=("backend/continuous_builder/trusted_policy.py",),
        acceptance_criteria=("count never exceeds capacity",),
        budget_ceiling_wall_clock_seconds=600,
        risk_ceiling_indicators=("none",),
        required_gates=("unit_tests", "human_review"),
        constraints=("no schema migration",),
        uncertainties=("ownership of helper module unknown",),
    )
    values.update(overrides)
    return create_frozen_task_contract(**values)


def test_deterministic_contract_digest():
    a = _contract()
    b = _contract()
    assert a.contract_sha256 == b.contract_sha256
    assert a == b


def test_zero_authority_and_planning_flags():
    c = _contract()
    for name in AUTHORITY_FLAGS:
        assert getattr(c, name) is False
    assert c.execution_authorized is False
    assert c.decomposition_execution_authorized is False
    assert c.provider_launch_authorized is False
    assert c.scope_expansion_authorized is False
    assert c.risk_classification_descriptive_only is True
    assert c.capability_admission_deferred_to_gpc is True


def test_descriptive_only_helpers():
    assert task_contract_is_planning_only() is True
    assert task_contract_risk_is_descriptive_only() is True


def test_schema_version_constant():
    assert _contract().schema_version == TASK_CONTRACT_VERSION


def test_rejects_unknown_taxonomy():
    with pytest.raises(TaskContractError, match="taxonomy_class_id"):
        _contract(taxonomy_class_id="not_a_real_class")


def test_rejects_stale_base_sha_format():
    with pytest.raises(GPAEvalSchemaError, match="base_sha"):
        _contract(base_sha="deadbeef")


def test_rejects_forged_baseline_digest():
    with pytest.raises(GPAEvalSchemaError, match="architecture_baseline"):
        _contract(architecture_baseline_sha256="not-a-digest")


def test_rejects_forbidden_overlap_allowed():
    path = "tests/fixtures/gpa_eval/nb_001/widget_counter.py"
    with pytest.raises(TaskContractError, match="overlaps"):
        _contract(allowed_scope=(path,), forbidden_scope=(path,))


def test_rejects_empty_allowed_scope():
    with pytest.raises(TaskContractError, match="allowed_scope"):
        _contract(allowed_scope=())


def test_rejects_empty_acceptance():
    with pytest.raises(TaskContractError, match="acceptance_criteria"):
        _contract(acceptance_criteria=())


def test_rejects_unsupported_risk_indicator():
    with pytest.raises(TaskContractError, match="risk_ceiling"):
        _contract(risk_ceiling_indicators=("totally_made_up",))


def test_rejects_oversized_goal():
    with pytest.raises(GPAEvalSchemaError, match="goal"):
        _contract(goal="x" * 5000)


def test_rejects_path_traversal():
    with pytest.raises(GPAEvalSchemaError):
        _contract(allowed_scope=("../etc/passwd",))


def test_rejects_absolute_path():
    with pytest.raises(GPAEvalSchemaError):
        _contract(allowed_scope=("/tmp/evil.py",))


def test_cannot_construct_without_token():
    with pytest.raises(TaskContractError, match="trusted construction"):
        FrozenTaskContract(
            schema_version=TASK_CONTRACT_VERSION,
            task_contract_id="tc_x",
            repository_identity="mootos",
            base_sha=TRUSTED_BASE,
            architecture_baseline_sha256=BASELINE_DIGEST,
            taxonomy_class_id="narrow_bug_fix",
            goal="g",
            intent_summary="i",
            allowed_scope=("a.py",),
            forbidden_scope=(),
            acceptance_criteria=("ok",),
            budget_ceiling_wall_clock_seconds=None,
            budget_ceiling_input_tokens=None,
            budget_ceiling_output_tokens=None,
            budget_ceiling_cost_usd_cents=None,
            risk_ceiling_indicators=("none",),
            risk_classification_descriptive_only=True,
            capability_admission_deferred_to_gpc=True,
            required_gates=(),
            constraints=(),
            uncertainties=(),
            generator_version="gpb-task-contract-generator-v1",
            contract_sha256="b" * 64,
        )


def test_forged_field_with_stale_digest_rejected(monkeypatch):
    c = _contract()
    object.__setattr__(c, "goal", "silently widened intent")
    with pytest.raises(TaskContractError, match="contract_sha256 mismatch"):
        c.__post_init__()


def test_required_gates_canonical_order():
    c = _contract(required_gates=("human_review", "unit_tests"))
    assert c.required_gates == ("human_review", "unit_tests")


def test_to_dict_round_trip_identity():
    c = _contract()
    d = c.to_dict()
    assert d["contract_sha256"] == c.contract_sha256
    assert d["execution_authorized"] is False
    assert d["capability_admission_deferred_to_gpc"] is True
