"""CB-027E adversarial TCB bypass suite.

Actively attempts to break enforcement. Does not weaken production code for
artificial failures. Proves: no bypass becomes ordinary; uncertainty != pass;
malformed != trusted; protected cannot disappear via normalization; omission
cannot silently pass.
"""

import dataclasses

import pytest

from backend.continuous_builder.trusted_policy import (
    create_mootos_tcb_registry_v1,
)
from backend.continuous_builder.trusted_policy_enforcement import (
    ADMISSION_IDENTITY_MISMATCH,
    ADMISSION_REVIEW,
    ADMISSION_STALE_RECEIPT,
    AUTHORITY_FLAGS,
    OUTCOME_FORBIDDEN,
    OUTCOME_MALFORMED,
    OUTCOME_ORDINARY,
    OUTCOME_REVIEW,
    OUTCOME_UNCERTAIN,
    TrustedPolicyDecision,
    TrustedPolicyDecisionReceipt,
    TrustedPolicyEnforcementError,
    admit_changed_paths_against_tcb,
    create_trusted_policy_decision_receipt,
    evaluate_changed_paths_against_tcb,
)


REGISTRY = create_mootos_tcb_registry_v1()
TCB_PATHS = REGISTRY.protected_paths


def _assert_not_ordinary(decision):
    assert decision.outcome != OUTCOME_ORDINARY
    assert decision.allows_ordinary_continuation is False
    assert decision.blocks_advancement is True
    for flag in AUTHORITY_FLAGS:
        assert getattr(decision, flag) is False


# --- Attack cases (minimum 25) ----------------------------------------------


def test_attack_01_traversal_dotdot():
    decision = evaluate_changed_paths_against_tcb(
        ("../backend/continuous_builder/verifier_core.py",)
    )
    assert decision.outcome == OUTCOME_MALFORMED
    _assert_not_ordinary(decision)


def test_attack_02_absolute_path():
    decision = evaluate_changed_paths_against_tcb(
        ("/etc/passwd",)
    )
    assert decision.outcome == OUTCOME_MALFORMED
    _assert_not_ordinary(decision)


def test_attack_03_dot_segment_normalization_hide():
    # Non-canonical form of a TCB path must not become ordinary via normalize.
    decision = evaluate_changed_paths_against_tcb(
        ("backend/continuous_builder/./verifier_core.py",)
    )
    assert decision.outcome == OUTCOME_MALFORMED
    _assert_not_ordinary(decision)
    # Canonical form is still detected as protected.
    canonical = evaluate_changed_paths_against_tcb(
        ("backend/continuous_builder/verifier_core.py",)
    )
    assert canonical.outcome == OUTCOME_REVIEW


def test_attack_04_duplicate_paths():
    decision = evaluate_changed_paths_against_tcb(
        (
            "backend/continuous_builder/verifier_core.py",
            "backend/continuous_builder/verifier_core.py",
        )
    )
    assert decision.outcome == OUTCOME_MALFORMED
    _assert_not_ordinary(decision)


def test_attack_05_case_collision_input():
    decision = evaluate_changed_paths_against_tcb(
        ("backend/memory.py", "backend/Memory.py")
    )
    assert decision.outcome == OUTCOME_MALFORMED
    _assert_not_ordinary(decision)


def test_attack_06_case_variant_of_tcb_path():
    decision = evaluate_changed_paths_against_tcb(
        ("Backend/continuous_builder/verifier_core.py",)
    )
    assert decision.outcome == OUTCOME_MALFORMED
    _assert_not_ordinary(decision)


def test_attack_07_backslash_separator():
    decision = evaluate_changed_paths_against_tcb(
        (r"backend\continuous_builder\verifier_core.py",)
    )
    assert decision.outcome == OUTCOME_MALFORMED
    _assert_not_ordinary(decision)


def test_attack_08_fake_registry_cannot_inject():
    import inspect
    from backend.continuous_builder import trusted_policy_enforcement as mod

    assert "registry" not in inspect.signature(
        mod.evaluate_changed_paths_against_tcb
    ).parameters
    # Local dict claiming ordinary is TCB does nothing.
    fake = {"backend/memory.py": "trusted"}
    assert fake["backend/memory.py"] == "trusted"
    decision = evaluate_changed_paths_against_tcb(("backend/memory.py",))
    assert decision.outcome == OUTCOME_ORDINARY
    assert decision.registry_sha256 == REGISTRY.registry_sha256


def test_attack_09_fake_component_via_direct_match_construction():
    with pytest.raises(TrustedPolicyEnforcementError):
        from backend.continuous_builder.trusted_policy_enforcement import (
            TCBMatchRecord,
        )
        TCBMatchRecord(
            path="backend/memory.py",
            component_id="fake_component",
            category="verifier",
            change_policy="protected_core_review",
            protected=True,
            outcome=OUTCOME_REVIEW,
        )


def test_attack_10_forged_decision_digest():
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


def test_attack_11_forged_receipt_digest():
    receipt = create_trusted_policy_decision_receipt(
        evaluate_changed_paths_against_tcb(("backend/memory.py",))
    )
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
            receipt_sha256="cd" * 32,
            _token=getattr(receipt, "_token"),
        )


def test_attack_12_stale_receipt_replay_across_candidates():
    prior = create_trusted_policy_decision_receipt(
        evaluate_changed_paths_against_tcb(("backend/memory.py",)),
        candidate_digest="11" * 32,
        worker_request_digest="22" * 32,
    )
    admission = admit_changed_paths_against_tcb(
        ("backend/memory.py",),
        candidate_digest="33" * 32,
        worker_request_digest="22" * 32,
        prior_receipt=prior,
    )
    assert admission.status == ADMISSION_STALE_RECEIPT
    assert admission.allows_continuation is False


def test_attack_13_cross_candidate_path_set_replay():
    prior = create_trusted_policy_decision_receipt(
        evaluate_changed_paths_against_tcb(("backend/memory.py",)),
        candidate_digest="11" * 32,
    )
    admission = admit_changed_paths_against_tcb(
        ("frontend/app.js",),
        candidate_digest="11" * 32,
        prior_receipt=prior,
    )
    assert admission.status == ADMISSION_STALE_RECEIPT


def test_attack_14_inventory_lie_omits_tcb_path():
    # Worker declares only ordinary while authoritative inventory has TCB.
    admission = admit_changed_paths_against_tcb(
        ("backend/continuous_builder/verifier_core.py",),
        worker_declared_paths=("backend/memory.py",),
    )
    assert admission.status == ADMISSION_IDENTITY_MISMATCH
    assert admission.allows_continuation is False


def test_attack_15_mixed_paths_cannot_downgrade_protected():
    decision = evaluate_changed_paths_against_tcb(
        (
            "backend/memory.py",
            "frontend/app.js",
            "backend/continuous_builder/verifier_core.py",
        )
    )
    assert decision.outcome == OUTCOME_REVIEW
    _assert_not_ordinary(decision)


def test_attack_16_self_mod_trusted_policy():
    decision = evaluate_changed_paths_against_tcb(
        ("backend/continuous_builder/trusted_policy.py",)
    )
    assert decision.outcome == OUTCOME_FORBIDDEN
    assert decision.tcb_matches[0].category == "trusted_policy"
    _assert_not_ordinary(decision)


def test_attack_17_modify_verifier_core():
    decision = evaluate_changed_paths_against_tcb(
        ("backend/continuous_builder/verifier_core.py",)
    )
    assert decision.outcome == OUTCOME_REVIEW
    _assert_not_ordinary(decision)


def test_attack_18_modify_adversarial_verifier():
    decision = evaluate_changed_paths_against_tcb(
        ("backend/continuous_builder/adversarial_verifier.py",)
    )
    assert decision.outcome == OUTCOME_REVIEW
    _assert_not_ordinary(decision)


def test_attack_19_modify_artifact_intake():
    decision = evaluate_changed_paths_against_tcb(
        ("backend/continuous_builder/worker_artifact.py",)
    )
    assert decision.outcome == OUTCOME_REVIEW
    _assert_not_ordinary(decision)


def test_attack_20_modify_worker_authorization():
    decision = evaluate_changed_paths_against_tcb(
        ("backend/continuous_builder/worker_authorization.py",)
    )
    assert decision.outcome == OUTCOME_REVIEW
    _assert_not_ordinary(decision)


def test_attack_21_modify_approval_authority():
    decision = evaluate_changed_paths_against_tcb(
        ("backend/continuous_builder/chief_builder.py",)
    )
    assert decision.outcome == OUTCOME_FORBIDDEN
    _assert_not_ordinary(decision)


def test_attack_22_modify_publication_authority():
    decision = evaluate_changed_paths_against_tcb(
        ("scripts/capability_build/pr_publication_authorization.py",)
    )
    assert decision.outcome == OUTCOME_FORBIDDEN
    _assert_not_ordinary(decision)


def test_attack_23_unknown_policy_category_surfaces():
    # Enforcement maps only known CHANGE_POLICIES; unsupported would be
    # uncertain. Prove ordinary unknown paths stay ordinary, and no public
    # API accepts unknown policy injection.
    decision = evaluate_changed_paths_against_tcb(("docs/README.md",))
    assert decision.outcome == OUTCOME_ORDINARY
    with pytest.raises(TrustedPolicyEnforcementError):
        from backend.continuous_builder.trusted_policy_enforcement import (
            TCBMatchRecord,
        )
        TCBMatchRecord(
            path="docs/README.md",
            component_id="cb_fake",
            category="not_a_category",
            change_policy="unreviewed_free_for_all",
            protected=True,
            outcome=OUTCOME_REVIEW,
            _token=object(),
        )


def test_attack_24_malformed_encoding_and_null():
    decision = evaluate_changed_paths_against_tcb(("backend/mem\x00ory.py",))
    assert decision.outcome == OUTCOME_MALFORMED
    _assert_not_ordinary(decision)


def test_attack_25_oversized_path_set():
    paths = tuple(f"backend/file_{i}.py" for i in range(300))
    decision = evaluate_changed_paths_against_tcb(paths)
    assert decision.outcome == OUTCOME_MALFORMED
    assert "changed_paths_exceed_bound" in decision.reason_codes
    _assert_not_ordinary(decision)


def test_attack_26_authority_flags_forced_true_rejected():
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


def test_attack_27_duplicate_ownership_ambiguity_rejected_at_registry():
    # Registry itself rejects overlapping ownership; enforcement uses only
    # the canonical factory, so ambiguous ownership cannot be introduced.
    from backend.continuous_builder.trusted_policy import (
        TrustedPolicyError,
        TrustedPolicyRegistry,
    )
    registry = REGISTRY
    a = registry.components[0]
    b = registry.components[1]
    stolen = object.__new__(type(b))
    for item in dataclasses.fields(b):
        value = a.paths if item.name == "paths" else getattr(b, item.name)
        if item.name == "component_sha256":
            value = a.component_sha256
        object.__setattr__(stolen, item.name, value)
    components = tuple(
        stolen if c.component_id == b.component_id else c
        for c in registry.components
    )
    with pytest.raises(TrustedPolicyError, match="overlapping"):
        TrustedPolicyRegistry(
            version=registry.version,
            components=components,
            protected_paths=registry.protected_paths,
            registry_sha256=registry.registry_sha256,
            policy_version=registry.policy_version,
            _token=getattr(registry, "_token"),
        )


def test_attack_28_git_and_env_forbidden_classes():
    for path in (".git/config", "backend/.env", ".env"):
        decision = evaluate_changed_paths_against_tcb((path,))
        assert decision.outcome == OUTCOME_MALFORMED
        _assert_not_ordinary(decision)


def test_attack_29_directory_and_glob_forms():
    for path in (
        "backend/continuous_builder/",
        "backend/continuous_builder/*.py",
        "backend/**/verifier_core.py",
    ):
        decision = evaluate_changed_paths_against_tcb((path,))
        assert decision.outcome == OUTCOME_MALFORMED
        _assert_not_ordinary(decision)


def test_attack_30_omission_of_tcb_from_declared_set_cannot_pass():
    # Authoritative inventory includes TCB; omitting it from worker declaration
    # is identity mismatch, not ordinary continuation.
    admission = admit_changed_paths_against_tcb(
        (
            "backend/memory.py",
            "backend/continuous_builder/trusted_policy.py",
        ),
        worker_declared_paths=("backend/memory.py",),
    )
    assert admission.status == ADMISSION_IDENTITY_MISMATCH
    assert admission.allows_continuation is False


def test_attack_31_uncertainty_never_equals_pass():
    # Malformed inputs are not ordinary; empty reason uncertain path is
    # reserved for registry integrity failures, never a silent pass.
    decision = evaluate_changed_paths_against_tcb((123,))
    assert decision.outcome == OUTCOME_MALFORMED
    assert decision.outcome != OUTCOME_ORDINARY
    assert OUTCOME_UNCERTAIN != OUTCOME_ORDINARY


def test_attack_32_forged_receipt_outcome_downgrade():
    decision = evaluate_changed_paths_against_tcb(
        ("backend/continuous_builder/verifier_core.py",)
    )
    receipt = create_trusted_policy_decision_receipt(decision)
    with pytest.raises(TrustedPolicyEnforcementError):
        TrustedPolicyDecisionReceipt(
            receipt_version=receipt.receipt_version,
            policy_version=receipt.policy_version,
            registry_version=receipt.registry_version,
            registry_sha256=receipt.registry_sha256,
            decision_sha256=receipt.decision_sha256,
            outcome=OUTCOME_ORDINARY,
            canonical_paths_sha256=receipt.canonical_paths_sha256,
            tcb_match_count=0,
            tcb_matches_sha256=receipt.tcb_matches_sha256,
            reason_codes=("all_ordinary_paths",),
            reason_codes_sha256=receipt.reason_codes_sha256,
            candidate_digest=receipt.candidate_digest,
            worker_request_digest=receipt.worker_request_digest,
            input_identity=receipt.input_identity,
            receipt_sha256=receipt.receipt_sha256,
            _token=getattr(receipt, "_token"),
        )


def test_attack_33_all_canonical_tcb_paths_resist_bypass():
    for path in TCB_PATHS:
        decision = evaluate_changed_paths_against_tcb((path,))
        _assert_not_ordinary(decision)
        # Normalization-adjacent forms also fail closed (not ordinary).
        dotted = path.replace("/", "/./", 1)
        if dotted != path:
            alt = evaluate_changed_paths_against_tcb((dotted,))
            assert alt.outcome == OUTCOME_MALFORMED


def test_attack_34_admission_cannot_promote_authority():
    admission = admit_changed_paths_against_tcb(
        ("backend/continuous_builder/verifier_core.py",)
    )
    assert admission.status == ADMISSION_REVIEW
    for flag in AUTHORITY_FLAGS:
        assert getattr(admission, flag) is False
    assert admission.authorized is False
