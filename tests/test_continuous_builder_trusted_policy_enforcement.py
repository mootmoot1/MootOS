"""Focused tests for CB-027B/C TCB enforcement and decision receipts."""

import dataclasses

import pytest

from backend.continuous_builder.trusted_policy import (
    create_mootos_tcb_registry_v1,
)
from backend.continuous_builder.trusted_policy_enforcement import (
    AUTHORITY_FLAGS,
    OUTCOME_FORBIDDEN,
    OUTCOME_MALFORMED,
    OUTCOME_ORDINARY,
    OUTCOME_REVIEW,
    TCBMatchRecord,
    TrustedPolicyDecision,
    TrustedPolicyDecisionReceipt,
    TrustedPolicyEnforcementError,
    create_trusted_policy_decision_receipt,
    evaluate_changed_paths_against_tcb,
)


TCB_PATHS = create_mootos_tcb_registry_v1().protected_paths


def test_ordinary_paths_not_blocked():
    decision = evaluate_changed_paths_against_tcb(
        ("backend/memory.py", "frontend/app.js")
    )
    assert decision.outcome == OUTCOME_ORDINARY
    assert decision.allows_ordinary_continuation is True
    assert decision.blocks_advancement is False
    assert decision.tcb_matches == ()
    assert decision.ordinary_paths == (
        "backend/memory.py",
        "frontend/app.js",
    )
    for flag in AUTHORITY_FLAGS:
        assert getattr(decision, flag) is False


def test_every_canonical_tcb_path_detected():
    registry = create_mootos_tcb_registry_v1()
    for path in registry.protected_paths:
        decision = evaluate_changed_paths_against_tcb((path,))
        assert decision.blocks_advancement is True
        assert decision.outcome in (OUTCOME_REVIEW, OUTCOME_FORBIDDEN)
        assert len(decision.tcb_matches) == 1
        match = decision.tcb_matches[0]
        assert match.path == path
        assert match.protected is True
        component = registry.component_for_path(path)
        assert match.component_id == component.component_id
        assert match.category == component.category
        assert match.change_policy == component.change_policy


def test_adversarial_verifier_protected():
    path = "backend/continuous_builder/adversarial_verifier.py"
    decision = evaluate_changed_paths_against_tcb((path,))
    assert decision.outcome == OUTCOME_REVIEW
    assert decision.tcb_matches[0].component_id == "cb_verifier_core"
    assert decision.tcb_matches[0].category == "verifier"


def test_trusted_policy_self_protects():
    path = "backend/continuous_builder/trusted_policy.py"
    decision = evaluate_changed_paths_against_tcb((path,))
    assert decision.outcome == OUTCOME_FORBIDDEN
    assert decision.tcb_matches[0].category == "trusted_policy"
    assert decision.tcb_matches[0].change_policy == "human_only"
    assert decision.requires_human_review is False


def test_no_fake_registry_injection_surface():
    """evaluate_* never accepts a registry argument."""
    import inspect
    from backend.continuous_builder import trusted_policy_enforcement as mod

    sig = inspect.signature(mod.evaluate_changed_paths_against_tcb)
    assert "registry" not in sig.parameters
    assert "tcb_registry" not in sig.parameters
    # Local fake map cannot influence classification.
    fake = {"backend/memory.py": "verifier"}
    assert fake.get("backend/memory.py") == "verifier"
    decision = evaluate_changed_paths_against_tcb(("backend/memory.py",))
    assert decision.outcome == OUTCOME_ORDINARY
    registry = create_mootos_tcb_registry_v1()
    assert decision.registry_sha256 == registry.registry_sha256


@pytest.mark.parametrize(
    "path",
    [
        "../secrets.txt",
        "../../etc/passwd",
        "/etc/passwd",
        "backend/../backend/memory.py",
        "backend/continuous_builder/./verifier_core.py",
        "Backend/continuous_builder/verifier_core.py",
        "backend/continuous_builder/Verifier_Core.py",
        r"backend\memory.py",
        "backend/continuous_builder/*.py",
        ".git/config",
        "backend/.env",
        "backend/continuous_builder/",
    ],
)
def test_traversal_case_absolute_malformed_fail_closed(path):
    decision = evaluate_changed_paths_against_tcb((path,))
    assert decision.outcome == OUTCOME_MALFORMED
    assert decision.blocks_advancement is True
    assert decision.tcb_matches == ()
    assert decision.canonical_paths == ()


def test_duplicate_paths_fail_closed():
    decision = evaluate_changed_paths_against_tcb(
        ("backend/memory.py", "backend/memory.py")
    )
    assert decision.outcome == OUTCOME_MALFORMED
    assert "path_duplicate" in decision.reason_codes


def test_case_collision_within_input_fail_closed():
    decision = evaluate_changed_paths_against_tcb(
        ("backend/memory.py", "backend/Memory.py")
    )
    assert decision.outcome == OUTCOME_MALFORMED
    assert "path_case_collision" in decision.reason_codes


def test_mixed_ordinary_and_review_takes_review():
    decision = evaluate_changed_paths_against_tcb(
        (
            "backend/memory.py",
            "backend/continuous_builder/verifier_core.py",
        )
    )
    assert decision.outcome == OUTCOME_REVIEW
    assert decision.ordinary_paths == ("backend/memory.py",)
    assert len(decision.tcb_matches) == 1


def test_mixed_review_and_forbidden_takes_forbidden():
    decision = evaluate_changed_paths_against_tcb(
        (
            "backend/continuous_builder/verifier_core.py",
            "backend/continuous_builder/trusted_policy.py",
        )
    )
    assert decision.outcome == OUTCOME_FORBIDDEN


def test_decision_deterministic_and_ordered():
    paths = (
        "frontend/app.js",
        "backend/memory.py",
        "backend/continuous_builder/check_runner.py",
    )
    a = evaluate_changed_paths_against_tcb(paths)
    b = evaluate_changed_paths_against_tcb(tuple(reversed(paths)))
    assert a.decision_sha256 == b.decision_sha256
    assert a.canonical_paths == b.canonical_paths
    assert a.canonical_paths == tuple(sorted(a.canonical_paths))
    assert a.canonical_bytes() == b.canonical_bytes()


def test_direct_decision_construction_without_token_rejected():
    with pytest.raises(TrustedPolicyEnforcementError, match="trusted system"):
        TrustedPolicyDecision(
            outcome=OUTCOME_ORDINARY,
            policy_version="cb-trusted-policy-enforcement-v1",
            registry_version="mootos-tcb-registry-v1",
            registry_sha256="0" * 64,
            canonical_paths=(),
            canonical_paths_sha256="0" * 64,
            ordinary_paths=(),
            tcb_matches=(),
            reason_codes=(),
            input_path_count=0,
            decision_sha256="0" * 64,
        )


def test_direct_match_construction_without_token_rejected():
    with pytest.raises(TrustedPolicyEnforcementError, match="trusted system"):
        TCBMatchRecord(
            path="backend/continuous_builder/verifier_core.py",
            component_id="cb_verifier_core",
            category="verifier",
            change_policy="protected_core_review",
            protected=True,
            outcome=OUTCOME_REVIEW,
        )


def test_authority_promotion_rejected():
    decision = evaluate_changed_paths_against_tcb(("backend/memory.py",))
    for flag in AUTHORITY_FLAGS:
        with pytest.raises(TrustedPolicyEnforcementError, match="authority"):
            TrustedPolicyDecision(
                outcome=decision.outcome,
                policy_version=decision.policy_version,
                registry_version=decision.registry_version,
                registry_sha256=decision.registry_sha256,
                canonical_paths=decision.canonical_paths,
                canonical_paths_sha256=decision.canonical_paths_sha256,
                ordinary_paths=decision.ordinary_paths,
                tcb_matches=decision.tcb_matches,
                reason_codes=decision.reason_codes,
                input_path_count=decision.input_path_count,
                decision_sha256=decision.decision_sha256,
                **{flag: True},
                _token=getattr(decision, "_token"),
            )


def test_forged_decision_digest_rejected():
    decision = evaluate_changed_paths_against_tcb(("backend/memory.py",))
    with pytest.raises(TrustedPolicyEnforcementError, match="digest"):
        TrustedPolicyDecision(
            outcome=decision.outcome,
            policy_version=decision.policy_version,
            registry_version=decision.registry_version,
            registry_sha256=decision.registry_sha256,
            canonical_paths=decision.canonical_paths,
            canonical_paths_sha256=decision.canonical_paths_sha256,
            ordinary_paths=decision.ordinary_paths,
            tcb_matches=decision.tcb_matches,
            reason_codes=decision.reason_codes,
            input_path_count=decision.input_path_count,
            decision_sha256="ab" * 32,
            _token=getattr(decision, "_token"),
        )


def test_oversized_path_set_fail_closed():
    paths = tuple(f"backend/file_{index}.py" for index in range(300))
    decision = evaluate_changed_paths_against_tcb(paths)
    assert decision.outcome == OUTCOME_MALFORMED
    assert "changed_paths_exceed_bound" in decision.reason_codes


def test_malformed_input_types_fail_closed():
    for value in ("backend/memory.py", {"path": "x"}, None, 123):
        decision = evaluate_changed_paths_against_tcb(value)
        assert decision.outcome == OUTCOME_MALFORMED


def test_zero_authority_on_protected_outcomes():
    for path in (
        "backend/continuous_builder/verifier_core.py",
        "backend/continuous_builder/trusted_policy.py",
        "backend/continuous_builder/chief_builder.py",
    ):
        decision = evaluate_changed_paths_against_tcb((path,))
        for flag in AUTHORITY_FLAGS:
            assert getattr(decision, flag) is False
        assert decision.publication_authorized is False
        assert decision.merge_authorized is False


def test_publication_authority_path_forbidden():
    path = "scripts/capability_build/pr_publication_authorization.py"
    decision = evaluate_changed_paths_against_tcb((path,))
    assert decision.outcome == OUTCOME_FORBIDDEN
    assert decision.tcb_matches[0].category == "publication_authority"


def test_empty_change_set_is_ordinary():
    decision = evaluate_changed_paths_against_tcb(())
    assert decision.outcome == OUTCOME_ORDINARY
    assert "empty_change_set" in decision.reason_codes


# --- CB-027C receipts -------------------------------------------------------


def _decision(paths=("backend/memory.py",)):
    return evaluate_changed_paths_against_tcb(paths)


def test_receipt_deterministic_repeat():
    decision = _decision(
        (
            "backend/memory.py",
            "backend/continuous_builder/verifier_core.py",
        )
    )
    a = create_trusted_policy_decision_receipt(
        decision,
        candidate_digest="ab" * 32,
        worker_request_digest="cd" * 32,
        input_identity="candidate-1",
    )
    b = create_trusted_policy_decision_receipt(
        decision,
        candidate_digest="ab" * 32,
        worker_request_digest="cd" * 32,
        input_identity="candidate-1",
    )
    assert a.receipt_sha256 == b.receipt_sha256
    assert a.canonical_bytes() == b.canonical_bytes()
    assert a.decision_sha256 == decision.decision_sha256
    assert a.registry_sha256 == decision.registry_sha256
    assert a.outcome == decision.outcome
    assert a.tcb_match_count == len(decision.tcb_matches)
    assert a.reason_codes == decision.reason_codes


def test_forged_receipt_digest_rejected():
    receipt = create_trusted_policy_decision_receipt(_decision())
    with pytest.raises(TrustedPolicyEnforcementError, match="digest"):
        TrustedPolicyDecisionReceipt(
            receipt_version=receipt.receipt_version,
            policy_version=receipt.policy_version,
            registry_version=receipt.registry_version,
            registry_sha256=receipt.registry_sha256,
            decision_sha256=receipt.decision_sha256,
            outcome=receipt.outcome,
            canonical_paths_sha256=receipt.canonical_paths_sha256,
            tcb_match_count=receipt.tcb_match_count,
            tcb_matches_sha256=receipt.tcb_matches_sha256,
            reason_codes=receipt.reason_codes,
            reason_codes_sha256=receipt.reason_codes_sha256,
            candidate_digest=receipt.candidate_digest,
            worker_request_digest=receipt.worker_request_digest,
            input_identity=receipt.input_identity,
            receipt_sha256="ef" * 32,
            _token=getattr(receipt, "_token"),
        )


def test_forged_classification_outcome_on_receipt_rejected():
    decision = _decision(("backend/continuous_builder/verifier_core.py",))
    receipt = create_trusted_policy_decision_receipt(decision)
    with pytest.raises(TrustedPolicyEnforcementError, match="digest"):
        TrustedPolicyDecisionReceipt(
            receipt_version=receipt.receipt_version,
            policy_version=receipt.policy_version,
            registry_version=receipt.registry_version,
            registry_sha256=receipt.registry_sha256,
            decision_sha256=receipt.decision_sha256,
            outcome=OUTCOME_ORDINARY,
            canonical_paths_sha256=receipt.canonical_paths_sha256,
            tcb_match_count=receipt.tcb_match_count,
            tcb_matches_sha256=receipt.tcb_matches_sha256,
            reason_codes=receipt.reason_codes,
            reason_codes_sha256=receipt.reason_codes_sha256,
            candidate_digest=receipt.candidate_digest,
            worker_request_digest=receipt.worker_request_digest,
            input_identity=receipt.input_identity,
            receipt_sha256=receipt.receipt_sha256,
            _token=getattr(receipt, "_token"),
        )


def test_forged_registry_digest_on_receipt_rejected():
    decision = _decision()
    receipt = create_trusted_policy_decision_receipt(decision)
    with pytest.raises(TrustedPolicyEnforcementError, match="digest"):
        TrustedPolicyDecisionReceipt(
            receipt_version=receipt.receipt_version,
            policy_version=receipt.policy_version,
            registry_version=receipt.registry_version,
            registry_sha256="aa" * 32,
            decision_sha256=receipt.decision_sha256,
            outcome=receipt.outcome,
            canonical_paths_sha256=receipt.canonical_paths_sha256,
            tcb_match_count=receipt.tcb_match_count,
            tcb_matches_sha256=receipt.tcb_matches_sha256,
            reason_codes=receipt.reason_codes,
            reason_codes_sha256=receipt.reason_codes_sha256,
            candidate_digest=receipt.candidate_digest,
            worker_request_digest=receipt.worker_request_digest,
            input_identity=receipt.input_identity,
            receipt_sha256=receipt.receipt_sha256,
            _token=getattr(receipt, "_token"),
        )


def test_altered_path_list_digest_rejected():
    decision = _decision(("backend/memory.py", "frontend/app.js"))
    receipt = create_trusted_policy_decision_receipt(decision)
    with pytest.raises(TrustedPolicyEnforcementError, match="digest"):
        TrustedPolicyDecisionReceipt(
            receipt_version=receipt.receipt_version,
            policy_version=receipt.policy_version,
            registry_version=receipt.registry_version,
            registry_sha256=receipt.registry_sha256,
            decision_sha256=receipt.decision_sha256,
            outcome=receipt.outcome,
            canonical_paths_sha256="bb" * 32,
            tcb_match_count=receipt.tcb_match_count,
            tcb_matches_sha256=receipt.tcb_matches_sha256,
            reason_codes=receipt.reason_codes,
            reason_codes_sha256=receipt.reason_codes_sha256,
            candidate_digest=receipt.candidate_digest,
            worker_request_digest=receipt.worker_request_digest,
            input_identity=receipt.input_identity,
            receipt_sha256=receipt.receipt_sha256,
            _token=getattr(receipt, "_token"),
        )


def test_altered_component_match_digest_rejected():
    decision = _decision(("backend/continuous_builder/verifier_core.py",))
    receipt = create_trusted_policy_decision_receipt(decision)
    with pytest.raises(TrustedPolicyEnforcementError, match="digest"):
        TrustedPolicyDecisionReceipt(
            receipt_version=receipt.receipt_version,
            policy_version=receipt.policy_version,
            registry_version=receipt.registry_version,
            registry_sha256=receipt.registry_sha256,
            decision_sha256=receipt.decision_sha256,
            outcome=receipt.outcome,
            canonical_paths_sha256=receipt.canonical_paths_sha256,
            tcb_match_count=receipt.tcb_match_count,
            tcb_matches_sha256="cc" * 32,
            reason_codes=receipt.reason_codes,
            reason_codes_sha256=receipt.reason_codes_sha256,
            candidate_digest=receipt.candidate_digest,
            worker_request_digest=receipt.worker_request_digest,
            input_identity=receipt.input_identity,
            receipt_sha256=receipt.receipt_sha256,
            _token=getattr(receipt, "_token"),
        )


def test_altered_reason_codes_rejected():
    decision = _decision(("backend/continuous_builder/verifier_core.py",))
    receipt = create_trusted_policy_decision_receipt(decision)
    with pytest.raises(TrustedPolicyEnforcementError, match="digest"):
        TrustedPolicyDecisionReceipt(
            receipt_version=receipt.receipt_version,
            policy_version=receipt.policy_version,
            registry_version=receipt.registry_version,
            registry_sha256=receipt.registry_sha256,
            decision_sha256=receipt.decision_sha256,
            outcome=receipt.outcome,
            canonical_paths_sha256=receipt.canonical_paths_sha256,
            tcb_match_count=receipt.tcb_match_count,
            tcb_matches_sha256=receipt.tcb_matches_sha256,
            reason_codes=("forged_reason",),
            reason_codes_sha256=receipt.reason_codes_sha256,
            candidate_digest=receipt.candidate_digest,
            worker_request_digest=receipt.worker_request_digest,
            input_identity=receipt.input_identity,
            receipt_sha256=receipt.receipt_sha256,
            _token=getattr(receipt, "_token"),
        )


def test_receipt_authority_promotion_rejected():
    receipt = create_trusted_policy_decision_receipt(_decision())
    for flag in AUTHORITY_FLAGS:
        with pytest.raises(TrustedPolicyEnforcementError, match="authority"):
            TrustedPolicyDecisionReceipt(
                receipt_version=receipt.receipt_version,
                policy_version=receipt.policy_version,
                registry_version=receipt.registry_version,
                registry_sha256=receipt.registry_sha256,
                decision_sha256=receipt.decision_sha256,
                outcome=receipt.outcome,
                canonical_paths_sha256=receipt.canonical_paths_sha256,
                tcb_match_count=receipt.tcb_match_count,
                tcb_matches_sha256=receipt.tcb_matches_sha256,
                reason_codes=receipt.reason_codes,
                reason_codes_sha256=receipt.reason_codes_sha256,
                candidate_digest=receipt.candidate_digest,
                worker_request_digest=receipt.worker_request_digest,
                input_identity=receipt.input_identity,
                receipt_sha256=receipt.receipt_sha256,
                **{flag: True},
                _token=getattr(receipt, "_token"),
            )


def test_worker_cannot_instantiate_receipt_without_token():
    with pytest.raises(TrustedPolicyEnforcementError, match="trusted derived"):
        TrustedPolicyDecisionReceipt(
            receipt_version="cb-trusted-policy-decision-receipt-v1",
            policy_version="cb-trusted-policy-enforcement-v1",
            registry_version="mootos-tcb-registry-v1",
            registry_sha256="0" * 64,
            decision_sha256="0" * 64,
            outcome=OUTCOME_ORDINARY,
            canonical_paths_sha256="0" * 64,
            tcb_match_count=0,
            tcb_matches_sha256="0" * 64,
            reason_codes=(),
            reason_codes_sha256="0" * 64,
            candidate_digest=None,
            worker_request_digest=None,
            input_identity=None,
            receipt_sha256="0" * 64,
        )


def test_stale_registry_digest_on_decision_cannot_mint_receipt():
    decision = _decision()
    # Bypass construction to plant a wrong registry digest; the sealed
    # receipt factory must still fail closed against the live registry.
    bypass = object.__new__(TrustedPolicyDecision)
    for item in dataclasses.fields(decision):
        value = getattr(decision, item.name)
        if item.name == "registry_sha256":
            value = "dd" * 32
        object.__setattr__(bypass, item.name, value)
    with pytest.raises(TrustedPolicyEnforcementError):
        create_trusted_policy_decision_receipt(bypass)


def test_receipt_stable_ordering_independent_of_input_order():
    paths_a = (
        "frontend/app.js",
        "backend/continuous_builder/check_runner.py",
        "backend/memory.py",
    )
    paths_b = tuple(reversed(paths_a))
    receipt_a = create_trusted_policy_decision_receipt(_decision(paths_a))
    receipt_b = create_trusted_policy_decision_receipt(_decision(paths_b))
    assert receipt_a.receipt_sha256 == receipt_b.receipt_sha256
    assert receipt_a.canonical_paths_sha256 == receipt_b.canonical_paths_sha256
    assert receipt_a.tcb_matches_sha256 == receipt_b.tcb_matches_sha256


def test_receipt_rejects_malformed_identity():
    decision = _decision()
    with pytest.raises(TrustedPolicyEnforcementError, match="identity"):
        create_trusted_policy_decision_receipt(
            decision, input_identity="bad identity with spaces!"
        )


def test_receipt_binds_candidate_and_request_digests():
    decision = _decision(("backend/continuous_builder/trusted_policy.py",))
    receipt = create_trusted_policy_decision_receipt(
        decision,
        candidate_digest="11" * 32,
        worker_request_digest="22" * 32,
        input_identity="attempt:abc",
    )
    assert receipt.candidate_digest == "11" * 32
    assert receipt.worker_request_digest == "22" * 32
    assert receipt.input_identity == "attempt:abc"
    assert receipt.outcome == OUTCOME_FORBIDDEN
    for flag in AUTHORITY_FLAGS:
        assert getattr(receipt, flag) is False
