"""GP-D9 -- Adversarial / failure-injection corpus for durable job ledger.

Evaluator-facing cases only. No worker/provider/GitHub execution.
"""

from __future__ import annotations

from .gpa_eval_schema import canonical_json, sha256_hex

CORPUS_VERSION = "gpd-eval-corpus-v1"


def adversarial_cases():
    """Bounded corpus of GP-D invariants that must hold."""
    cases = (
        {
            "case_id": "gpd_dup_event_id",
            "invariant": "duplicate_event_ids_rejected",
            "expect_fail_closed": True,
        },
        {
            "case_id": "gpd_sequence_gap",
            "invariant": "sequence_violations_fail",
            "expect_fail_closed": True,
        },
        {
            "case_id": "gpd_malformed_event",
            "invariant": "malformed_rejected",
            "expect_fail_closed": True,
        },
        {
            "case_id": "gpd_stale_contract",
            "invariant": "stale_contract_admission_rejected",
            "expect_fail_closed": True,
        },
        {
            "case_id": "gpd_ceiling_widen",
            "invariant": "ceilings_cannot_widen",
            "expect_fail_closed": True,
        },
        {
            "case_id": "gpd_terminal_reopen",
            "invariant": "terminal_no_silent_reopen",
            "expect_fail_closed": True,
        },
        {
            "case_id": "gpd_worker_success_not_terminal",
            "invariant": "worker_success_alone_not_terminal_success",
            "expect_fail_closed": True,
        },
        {
            "case_id": "gpd_missing_proof_unknown",
            "invariant": "missing_proof_execution_unknown",
            "expect_fail_closed": True,
        },
        {
            "case_id": "gpd_unknown_no_blind_retry",
            "invariant": "unknown_no_blind_retry_unsafe_se",
            "expect_fail_closed": True,
        },
        {
            "case_id": "gpd_reconcile_first",
            "invariant": "reconcile_before_retry",
            "expect_fail_closed": True,
        },
        {
            "case_id": "gpd_dup_side_effect",
            "invariant": "duplicate_se_identity_detected",
            "expect_fail_closed": True,
        },
        {
            "case_id": "gpd_hb_no_progress_stall",
            "invariant": "heartbeat_without_progress_stall_evidence",
            "expect_fail_closed": False,
        },
        {
            "case_id": "gpd_expired_lease_not_no_se",
            "invariant": "expired_lease_not_side_effect_absence",
            "expect_fail_closed": True,
        },
        {
            "case_id": "gpd_checkpoint_tamper",
            "invariant": "checkpoint_tamper_detected",
            "expect_fail_closed": True,
        },
        {
            "case_id": "gpd_recovery_deterministic",
            "invariant": "recovery_deterministic_rebuild_identical",
            "expect_fail_closed": False,
        },
        {
            "case_id": "gpd_history_survives",
            "invariant": "history_survives_restart",
            "expect_fail_closed": False,
        },
        {
            "case_id": "gpd_retry_new_attempt",
            "invariant": "retry_creates_new_attempt",
            "expect_fail_closed": False,
        },
        {
            "case_id": "gpd_human_gates_survive",
            "invariant": "gpc_human_gates_survive",
            "expect_fail_closed": False,
        },
        {
            "case_id": "gpd_cancelled_ne_running",
            "invariant": "cancelled_not_running",
            "expect_fail_closed": False,
        },
        {
            "case_id": "gpd_main_merge_human",
            "invariant": "main_merge_human_controlled",
            "expect_fail_closed": False,
        },
    )
    return cases


def corpus_digest():
    return sha256_hex(canonical_json({
        "cases": list(adversarial_cases()),
        "corpus_version": CORPUS_VERSION,
    }))
