"""GP-B8 corpus + adversarial decomposition tests."""

from pathlib import Path

import pytest

from backend.continuous_builder.gpa_eval_schema import AUTHORITY_FLAGS
from backend.continuous_builder.gpb_decomposer import decompose_task_contract
from backend.continuous_builder.gpb_decomposition_node import create_decomposition_node
from backend.continuous_builder.gpb_eval_corpus import (
    CORPUS_BASE_SHA,
    EVALUATOR_ONLY_KEYS,
    create_gpb_decomp_eval_corpus_v1,
    gpb_eval_case_by_id,
    gpb_eval_corpus_is_descriptive_only,
    to_worker_visible_dict,
    verify_no_evaluator_leakage,
)
from backend.continuous_builder.gpb_plan_revision import (
    make_revision_op,
    revise_execution_plan,
)
from backend.continuous_builder.gpb_scope_rules import (
    check_contract_identity_preserved,
    check_node_against_contract,
    check_plan_nodes_against_contract,
)
from backend.continuous_builder.gpb_task_contract import create_frozen_task_contract
from backend.continuous_builder.system_model import build_system_model

BASELINE = "a" * 64
REPO = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def model():
    return build_system_model(REPO, base_sha=CORPUS_BASE_SHA)


@pytest.fixture(scope="module")
def corpus():
    return create_gpb_decomp_eval_corpus_v1()


def _contract_from_case(case, **overrides):
    values = dict(
        task_contract_id=f"tc_{case.case_id}",
        base_sha=CORPUS_BASE_SHA,
        architecture_baseline_sha256=BASELINE,
        taxonomy_class_id=case.taxonomy_class_id,
        goal=case.worker_goal,
        intent_summary=case.title,
        allowed_scope=tuple(sorted(case.worker_allowed_scope)),
        forbidden_scope=tuple(sorted(case.worker_forbidden_scope)),
        acceptance_criteria=("acceptance preserved",),
        required_gates=("unit_tests",),
    )
    values.update(overrides)
    return create_frozen_task_contract(**values)


def test_corpus_sealed_and_zero_authority(corpus):
    assert corpus.base_sha == CORPUS_BASE_SHA
    assert len(corpus.cases) >= 15
    for name in AUTHORITY_FLAGS:
        assert getattr(corpus, name) is False
    assert gpb_eval_corpus_is_descriptive_only() is True


def test_worker_view_excludes_evaluator_keys(corpus):
    for case in corpus.cases:
        payload = to_worker_visible_dict(case)
        for key in EVALUATOR_ONLY_KEYS:
            assert key not in payload
        verify_no_evaluator_leakage(payload)


def test_nested_evaluator_leak_detected():
    with pytest.raises(Exception):
        verify_no_evaluator_leakage(
            {"ok": True, "nested": {"ground_truth_notes": "secret"}}
        )


def test_simple_not_over_decomposed(model, corpus):
    case = gpb_eval_case_by_id(corpus, "gpb_nb_001")
    plan = decompose_task_contract(_contract_from_case(case), model)
    slices = [n for n in plan.nodes if n.level == "slice"]
    atomics = [n for n in plan.nodes if n.level == "atomic"]
    assert len(slices) <= (case.expected_max_slices or 0)
    assert len(atomics) >= case.expected_min_atomics


def test_large_not_one_giant_slice(model, corpus):
    case = gpb_eval_case_by_id(corpus, "gpb_multi_001")
    plan = decompose_task_contract(_contract_from_case(case), model)
    atomics = [n for n in plan.nodes if n.level == "atomic"]
    assert len(atomics) >= case.expected_min_atomics


def test_tcb_adjacent_escalates(model, corpus):
    case = gpb_eval_case_by_id(corpus, "gpb_tcb_001")
    plan = decompose_task_contract(_contract_from_case(case), model)
    assert plan.requires_escalation is True
    assert any("tcb" in r for r in plan.escalation_reasons)


def test_forbidden_scope_child_escalates(corpus):
    case = gpb_eval_case_by_id(corpus, "gpb_forbid_001")
    c = _contract_from_case(case)
    node = create_decomposition_node(
        node_id="n_bad",
        parent_id=None,
        level="atomic",
        node_type="implement",
        title="bad",
        objective="o",
        rationale="r",
        candidate_allowed_scope=tuple(sorted(case.worker_allowed_scope))
        + ("backend/continuous_builder/worker_request.py",),
        inherited_forbidden_scope=tuple(sorted(case.worker_forbidden_scope)),
        acceptance_checkpoint=("acceptance preserved",),
        complexity_estimate="small",
        children=(),
    )
    result = check_node_against_contract(c, node)
    assert result.preserved is False
    assert any(v.code == "new_path_outside_envelope" for v in result.violations)


def test_acceptance_cannot_preserve(corpus):
    case = gpb_eval_case_by_id(corpus, "gpb_accept_001")
    c = _contract_from_case(case)
    node = create_decomposition_node(
        node_id="n_relax",
        parent_id=None,
        level="atomic",
        node_type="implement",
        title="relax",
        objective="o",
        rationale="r",
        candidate_allowed_scope=tuple(sorted(case.worker_allowed_scope)),
        inherited_forbidden_scope=(),
        acceptance_checkpoint=("completely unrelated criterion",),
        complexity_estimate="small",
        children=(),
    )
    result = check_node_against_contract(c, node)
    assert result.preserved is False
    assert any(v.code == "relaxed_acceptance" for v in result.violations)


def test_stale_base_escalates(corpus):
    case = gpb_eval_case_by_id(corpus, "gpb_stale_001")
    original = _contract_from_case(case)
    stale = _contract_from_case(
        case, base_sha="dddddddddddddddddddddddddddddddddddddddd"
    )
    result = check_contract_identity_preserved(original, stale)
    assert result.preserved is False
    assert any(v.code == "changed_base_sha" for v in result.violations)


def test_tampered_contract_digest(corpus):
    case = gpb_eval_case_by_id(corpus, "gpb_tamper_001")
    c = _contract_from_case(case)
    object.__setattr__(c, "goal", "tampered goal text")
    from backend.continuous_builder.gpb_task_contract import TaskContractError
    with pytest.raises(TaskContractError, match="contract_sha256 mismatch"):
        c.__post_init__()


def test_cycle_detected(corpus):
    case = gpb_eval_case_by_id(corpus, "gpb_cycle_001")
    c = _contract_from_case(case)
    a = create_decomposition_node(
        node_id="n_a",
        parent_id=None,
        level="atomic",
        node_type="refactor",
        title="a",
        objective="o",
        rationale="r",
        depends_on=("n_b",),
        candidate_allowed_scope=tuple(sorted(case.worker_allowed_scope)),
        inherited_forbidden_scope=(),
        acceptance_checkpoint=("acceptance preserved",),
        complexity_estimate="small",
        children=(),
    )
    b = create_decomposition_node(
        node_id="n_b",
        parent_id=None,
        level="atomic",
        node_type="refactor",
        title="b",
        objective="o",
        rationale="r",
        depends_on=("n_a",),
        candidate_allowed_scope=tuple(sorted(case.worker_allowed_scope)),
        inherited_forbidden_scope=(),
        acceptance_checkpoint=("acceptance preserved",),
        complexity_estimate="small",
        children=(),
    )
    result = check_plan_nodes_against_contract(c, (a, b))
    assert any(v.code == "cycle_detected" for v in result.violations)


def test_duplicate_node_ids(corpus):
    case = gpb_eval_case_by_id(corpus, "gpb_nb_001")
    c = _contract_from_case(case)
    a = create_decomposition_node(
        node_id="n_dup",
        parent_id=None,
        level="atomic",
        node_type="implement",
        title="a",
        objective="o",
        rationale="r",
        candidate_allowed_scope=tuple(sorted(case.worker_allowed_scope)),
        inherited_forbidden_scope=tuple(sorted(case.worker_forbidden_scope)),
        acceptance_checkpoint=("acceptance preserved",),
        complexity_estimate="small",
        children=(),
    )
    b = create_decomposition_node(
        node_id="n_dup",
        parent_id=None,
        level="atomic",
        node_type="implement",
        title="b",
        objective="o",
        rationale="r",
        candidate_allowed_scope=tuple(sorted(case.worker_allowed_scope)),
        inherited_forbidden_scope=tuple(sorted(case.worker_forbidden_scope)),
        acceptance_checkpoint=("acceptance preserved",),
        complexity_estimate="small",
        children=(),
    )
    result = check_plan_nodes_against_contract(c, (a, b))
    assert any(v.code == "duplicate_node_id" for v in result.violations)


def test_malicious_revision_escalates(model, corpus):
    case = gpb_eval_case_by_id(corpus, "gpb_nb_001")
    c = _contract_from_case(case)
    plan = decompose_task_contract(c, model)
    evil = create_decomposition_node(
        node_id="n_evil_rev",
        parent_id=plan.root_node_id,
        level="atomic",
        node_type="implement",
        title="evil",
        objective="o",
        rationale="r",
        candidate_allowed_scope=tuple(sorted(case.worker_allowed_scope))
        + ("backend/continuous_builder/gpa_eval_schema.py",),
        inherited_forbidden_scope=tuple(sorted(case.worker_forbidden_scope)),
        acceptance_checkpoint=("acceptance preserved",),
        complexity_estimate="small",
        children=(),
    )
    result = revise_execution_plan(
        c, plan, (make_revision_op(op="insert_prerequisite", new_node=evil),)
    )
    assert result.applied is False
    assert result.requires_escalation is True


def test_nondeterministic_ordering_guard(model, corpus):
    case = gpb_eval_case_by_id(corpus, "gpb_multi_001")
    c = _contract_from_case(case)
    a = decompose_task_contract(c, model)
    b = decompose_task_contract(c, model)
    assert a.plan_sha256 == b.plan_sha256
    assert [n.node_id for n in a.nodes] == [n.node_id for n in b.nodes]


def test_unknown_ownership_valid(model, corpus):
    case = gpb_eval_case_by_id(corpus, "gpb_own_001")
    plan = decompose_task_contract(_contract_from_case(case), model)
    # Must produce a plan; UNKNOWN must not crash or invent execution authority.
    assert plan.execution_authorized is False
    assert plan.approved_to_execute is False


def test_removed_gate_and_budget_and_intent(corpus):
    case = gpb_eval_case_by_id(corpus, "gpb_nb_001")
    original = _contract_from_case(
        case,
        required_gates=("unit_tests", "human_review"),
        budget_ceiling_wall_clock_seconds=600,
    )
    no_gate = _contract_from_case(
        case,
        required_gates=("unit_tests",),
        budget_ceiling_wall_clock_seconds=600,
    )
    r1 = check_contract_identity_preserved(original, no_gate)
    assert any(v.code == "removed_gate" for v in r1.violations)
    bigger = _contract_from_case(
        case,
        required_gates=("human_review", "unit_tests"),
        budget_ceiling_wall_clock_seconds=9000,
    )
    r2 = check_contract_identity_preserved(original, bigger)
    assert any(v.code == "increased_budget" for v in r2.violations)
    intent = _contract_from_case(
        case,
        required_gates=("human_review", "unit_tests"),
        budget_ceiling_wall_clock_seconds=600,
        goal="Changed intent entirely for escalation check",
    )
    r3 = check_contract_identity_preserved(original, intent)
    assert any(v.code == "changed_intent" for v in r3.violations)


def test_unsupported_schema_rejected():
    from backend.continuous_builder.gpb_task_contract import (
        FrozenTaskContract,
        TASK_CONTRACT_VERSION,
        TaskContractError,
    )
    with pytest.raises(TaskContractError, match="trusted construction"):
        FrozenTaskContract(
            schema_version="gpb-task-contract-v999",
            task_contract_id="tc_x",
            repository_identity="mootos",
            base_sha=CORPUS_BASE_SHA,
            architecture_baseline_sha256=BASELINE,
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
            contract_sha256="e" * 64,
        )


def test_forged_plan_digest(model, corpus):
    case = gpb_eval_case_by_id(corpus, "gpb_nb_001")
    plan = decompose_task_contract(_contract_from_case(case), model)
    from backend.continuous_builder.gpb_decomposer import DecomposerError
    object.__setattr__(plan, "plan_id", "tampered_plan_id")
    with pytest.raises(DecomposerError, match="plan_sha256 mismatch"):
        plan.__post_init__()
