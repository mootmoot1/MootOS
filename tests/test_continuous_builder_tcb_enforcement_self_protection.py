"""Closure coverage for CB-027 Trusted Policy / TCB enforcement self-protection."""

from backend.continuous_builder.trusted_policy import (
    classify_tcb_path,
    create_mootos_tcb_registry_v1,
    is_tcb_path,
)
from backend.continuous_builder.trusted_policy_enforcement import (
    OUTCOME_FORBIDDEN,
    evaluate_changed_paths_against_tcb,
)


ENFORCEMENT_PATH = "backend/continuous_builder/trusted_policy_enforcement.py"


def test_enforcement_module_is_in_canonical_tcb_registry():
    registry = create_mootos_tcb_registry_v1()
    assert ENFORCEMENT_PATH in registry.protected_paths
    assert len(registry.protected_paths) == 15

    component = registry.component_for_path(ENFORCEMENT_PATH)
    assert component is not None
    assert component.component_id == "cb_trusted_policy"
    assert component.category == "trusted_policy"
    assert component.change_policy == "human_only"


def test_enforcement_module_query_helpers_fail_closed_as_protected():
    assert is_tcb_path(ENFORCEMENT_PATH) is True
    classification = classify_tcb_path(ENFORCEMENT_PATH)
    assert classification is not None
    assert classification.component_id == "cb_trusted_policy"
    assert classification.category == "trusted_policy"
    assert classification.change_policy == "human_only"


def test_enforcement_module_cannot_classify_its_own_change_as_ordinary():
    decision = evaluate_changed_paths_against_tcb((ENFORCEMENT_PATH,))
    assert decision.outcome == OUTCOME_FORBIDDEN
    assert decision.blocks_advancement is True
    assert decision.allows_ordinary_continuation is False
    assert decision.requires_human_review is False
    assert len(decision.tcb_matches) == 1
    assert decision.tcb_matches[0].path == ENFORCEMENT_PATH
    assert decision.tcb_matches[0].component_id == "cb_trusted_policy"
    assert decision.tcb_matches[0].change_policy == "human_only"
    assert decision.publication_authorized is False
    assert decision.queue_transition_authorized is False
    assert decision.github_authorized is False
    assert decision.merge_authorized is False
    assert decision.main_advancement_authorized is False
    assert decision.worker_output_trusted is False


def test_registry_digest_is_deterministic_after_enforcement_self_protection():
    first = create_mootos_tcb_registry_v1()
    second = create_mootos_tcb_registry_v1()
    assert first.registry_sha256 == second.registry_sha256
    assert first.registry_sha256 == (
        "56e38846274900aaab74c396afd65635187c369d5b1928764adb5aadde857dec"
    )
