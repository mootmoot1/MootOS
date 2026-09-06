"""GP-D8 -- Recovery / restart reconstruction (no launch).

Rebuild derived job state from durable header + events. Reconstruction is
deterministic: rebuild twice must be identical. This module never launches
workers, providers, or GitHub actions, and never widens sealed ceilings.
"""

from __future__ import annotations

from dataclasses import dataclass

from .gpd_job_header import DurableJobHeader, header_ceilings_cannot_widen
from .gpd_job_state import DerivedJobState, TERMINAL_STATES, reduce_job_state
from .gpd_job_store import JobLedgerStore, JobStoreError
from .gpd_side_effect import (
    execution_unknown_blocks_blind_retry,
    retry_eligibility,
)
from .gpd_failure import classify_failure
from .gpa_eval_schema import canonical_json, sha256_hex
from .trusted_policy import create_trusted_policy_snapshot


class RecoveryError(JobStoreError):
    """Raised when recovery cannot reconstruct safely."""


@dataclass(frozen=True)
class RecoveredJobView:
    header: DurableJobHeader
    state: DerivedJobState
    attempts: tuple
    leases: tuple
    heartbeats: tuple
    checkpoints: tuple
    side_effects: tuple
    reconciliations: tuple
    recovery_digest: str
    retry_eligible: bool
    blind_retry_blocked: bool
    human_gates: tuple

    def to_dict(self):
        return {
            "blind_retry_blocked": self.blind_retry_blocked,
            "header_sha256": self.header.header_sha256,
            "human_gates": list(self.human_gates),
            "job_id": self.header.job_id,
            "recovery_digest": self.recovery_digest,
            "retry_eligible": self.retry_eligible,
            "state": self.state.to_dict(),
            "attempt_ids": [a.attempt_id for a in self.attempts],
            "checkpoint_ids": [c.checkpoint_id for c in self.checkpoints],
            "side_effect_ids": [s.side_effect_id for s in self.side_effects],
        }


def _reject_stale_bindings(header, expected_contract_sha256=None,
                           expected_admission_sha256=None,
                           expected_tcb_registry_sha256=None,
                           expected_policy_version=None):
    if expected_contract_sha256 is not None and (
        header.task_contract_sha256 != expected_contract_sha256
    ):
        raise RecoveryError("stale contract rejected")
    if expected_admission_sha256 is not None and (
        header.admission_decision_sha256 != expected_admission_sha256
    ):
        raise RecoveryError("stale admission rejected")
    if expected_tcb_registry_sha256 is not None and (
        header.tcb_registry_sha256 != expected_tcb_registry_sha256
    ):
        raise RecoveryError("stale TCB registry rejected")
    if expected_policy_version is not None and (
        header.trusted_policy_version != expected_policy_version
    ):
        raise RecoveryError("stale trusted policy version rejected")


def reconstruct_job(
    store,
    job_id,
    *,
    expected_contract_sha256=None,
    expected_admission_sha256=None,
    expected_tcb_registry_sha256=None,
    expected_policy_version=None,
    verify_live_tcb=False,
):
    """Load durable history and derive state. No worker launch."""
    if not isinstance(store, JobLedgerStore):
        raise RecoveryError("store invalid")
    header = store.load_header(job_id)
    _reject_stale_bindings(
        header,
        expected_contract_sha256=expected_contract_sha256,
        expected_admission_sha256=expected_admission_sha256,
        expected_tcb_registry_sha256=expected_tcb_registry_sha256,
        expected_policy_version=expected_policy_version,
    )
    if verify_live_tcb:
        snapshot = create_trusted_policy_snapshot()
        if header.tcb_registry_sha256 != snapshot.registry_sha256:
            raise RecoveryError("live TCB registry digest drift")
        if header.trusted_policy_version != snapshot.policy_version:
            raise RecoveryError("live trusted policy version drift")
    events = store.load_events(job_id)
    state = reduce_job_state(header, events)
    attempts = tuple(store.load_attempts(job_id))
    leases = tuple(store.load_leases(job_id))
    heartbeats = tuple(store.load_heartbeats(job_id))
    checkpoints = tuple(store.load_checkpoints(job_id))
    side_effects = tuple(store.load_side_effects(job_id))
    reconciliations = tuple(store.load_reconciliations(job_id))
    latest_reconcile = reconciliations[-1] if reconciliations else None
    blind_blocked = execution_unknown_blocks_blind_retry(
        state.state, side_effects
    )
    eligible = retry_eligibility(
        state.state, reconciliation=latest_reconcile, side_effects=side_effects
    )
    # Cancelled must not look running; terminal must not reopen.
    if state.state == "cancelled" and state.state == "running":
        raise RecoveryError("cancelled cannot equal running")
    if state.terminal and state.state not in TERMINAL_STATES:
        raise RecoveryError("terminal flag inconsistent")
    body = {
        "attempts": [a.attempt_sha256 for a in attempts],
        "blind_retry_blocked": blind_blocked,
        "checkpoints": [c.checkpoint_sha256 for c in checkpoints],
        "header_sha256": header.header_sha256,
        "human_gates": list(header.required_gates),
        "job_id": header.job_id,
        "leases": [lease.lease_sha256 for lease in leases],
        "reconciliations": [r.reconciliation_sha256 for r in reconciliations],
        "retry_eligible": eligible,
        "side_effects": [s.side_effect_sha256 for s in side_effects],
        "state_digest": state.state_digest,
    }
    digest = sha256_hex(canonical_json(body))
    return RecoveredJobView(
        header=header,
        state=state,
        attempts=attempts,
        leases=leases,
        heartbeats=heartbeats,
        checkpoints=checkpoints,
        side_effects=side_effects,
        reconciliations=reconciliations,
        recovery_digest=digest,
        retry_eligible=eligible,
        blind_retry_blocked=blind_blocked,
        human_gates=header.required_gates,
    )


def recovery_is_deterministic(store, job_id):
    """Rebuild twice; digests must match."""
    first = reconstruct_job(store, job_id)
    second = reconstruct_job(store, job_id)
    if first.recovery_digest != second.recovery_digest:
        raise RecoveryError("recovery is not deterministic")
    if first.state.state_digest != second.state.state_digest:
        raise RecoveryError("derived state digest drift across rebuild")
    if not header_ceilings_cannot_widen(first.header, second.header):
        raise RecoveryError("header mutated across recovery")
    return True


def recovery_does_not_launch():
    return True
