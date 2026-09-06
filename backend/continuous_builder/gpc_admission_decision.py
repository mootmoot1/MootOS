"""GP-C6 -- Capability Admission Decision & Receipt (thin untrusted wrapper).

Authoritative algorithm lives in ``gpc_trusted_admission_core``. This module
adapts sealed ``AdmissionInput`` into ``TrustedAdmissionFacts``, then
delegates. Re-exports decision/receipt types for API stability.
"""

from .gpc_admission_input import AdmissionInput
from .gpc_trusted_admission_core import (
    DECISION_VERSION,
    GENERATOR_VERSION,
    MATRIX_VERSION,
    RECEIPT_VERSION,
    AdmissionDecision,
    AdmissionReceipt,
    PerCapabilityDecision,
    TrustedAdmissionError,
    admit_from_trusted_facts,
    admission_decision_cannot_execute,
    admission_never_auto_approves_main_merge,
    create_admission_receipt,
    seal_trusted_admission_facts,
    seal_trusted_request_fact,
)

AdmissionDecisionError = TrustedAdmissionError


def facts_from_admission_input(admission_input):
    """Project untrusted AdmissionInput into sealed TrustedAdmissionFacts.

    Outside assembly is never trusted on its own — the core re-validates
    every field and re-checks live TCB identity at the boundary.
    """
    if not isinstance(admission_input, AdmissionInput):
        raise AdmissionDecisionError("admission_input invalid")
    requests = tuple(
        seal_trusted_request_fact(
            request_id=req.request_id,
            capability_id=req.capability_id,
            request_sha256=req.request_sha256,
            requested_scope=tuple(req.requested_scope),
            budget_wall_clock_seconds=req.budget_wall_clock_seconds,
            budget_input_tokens=req.budget_input_tokens,
            budget_output_tokens=req.budget_output_tokens,
            evidence_refs=tuple(req.evidence_refs),
            human_gate_requested=req.human_gate_requested,
            worker_safe_claim=req.worker_safe_claim,
            provider_id=req.provider_id,
            model_id=req.model_id,
            benchmark_score=req.benchmark_score,
        )
        for req in admission_input.capability_requests
    )
    return seal_trusted_admission_facts(
        facts_id=admission_input.admission_input_id,
        task_contract_id=admission_input.task_contract_id,
        contract_sha256=admission_input.contract_sha256,
        plan_id=admission_input.plan_id,
        plan_sha256=admission_input.plan_sha256,
        base_sha=admission_input.base_sha,
        architecture_baseline_sha256=(
            admission_input.architecture_baseline_sha256
        ),
        allowed_scope=tuple(admission_input.allowed_scope),
        forbidden_scope=tuple(admission_input.forbidden_scope),
        required_gates=tuple(admission_input.required_gates),
        risk_ceiling_indicators=tuple(admission_input.risk_ceiling_indicators),
        budget_ceiling_wall_clock_seconds=(
            admission_input.budget_ceiling_wall_clock_seconds
        ),
        budget_ceiling_input_tokens=(
            admission_input.budget_ceiling_input_tokens
        ),
        budget_ceiling_output_tokens=(
            admission_input.budget_ceiling_output_tokens
        ),
        budget_ceiling_cost_usd_cents=(
            admission_input.budget_ceiling_cost_usd_cents
        ),
        plan_requires_escalation=admission_input.plan_requires_escalation,
        plan_escalation_reasons=tuple(admission_input.plan_escalation_reasons),
        system_model_sha256=admission_input.system_model_sha256,
        system_model_version=admission_input.system_model_version,
        expected_system_model_sha256=None,
        trusted_policy_version=admission_input.trusted_policy_version,
        tcb_registry_version=admission_input.tcb_registry_version,
        tcb_registry_sha256=admission_input.tcb_registry_sha256,
        tcb_protected_path_count=admission_input.tcb_protected_path_count,
        tcb_snapshot_sha256=admission_input.tcb_snapshot_sha256,
        vocabulary_version=admission_input.vocabulary_version,
        vocabulary_sha256=admission_input.vocabulary_sha256,
        evidence_digests=(),
        capability_requests=requests,
    )


def admit_capabilities(admission_input, *, decision_id="gpc_decision_001"):
    """Evaluate sealed admission input via the trusted core algorithm."""
    facts = facts_from_admission_input(admission_input)
    return admit_from_trusted_facts(facts, decision_id=decision_id)


__all__ = [
    "AdmissionDecision",
    "AdmissionDecisionError",
    "AdmissionReceipt",
    "DECISION_VERSION",
    "GENERATOR_VERSION",
    "MATRIX_VERSION",
    "PerCapabilityDecision",
    "RECEIPT_VERSION",
    "admit_capabilities",
    "admission_decision_cannot_execute",
    "admission_never_auto_approves_main_merge",
    "create_admission_receipt",
    "facts_from_admission_input",
]
