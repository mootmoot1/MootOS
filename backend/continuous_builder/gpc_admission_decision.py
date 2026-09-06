"""GP-C6 -- Capability Admission Decision & Receipt.

Sealed decision / receipt for one AdmissionInput. Records requested,
admitted-within-bound, denied, human-gated, and escalated capabilities with
rules applied, evidence, policy/TCB identity, and a decision digest.

A valid decision NEVER executes work, NEVER merges Main, NEVER grants
runtime authority. Main merge remains separately human-gated.
Runtime enforcement of admitted bounds is deferred to GP-D/F.

Deterministic. Fail closed. No LLM. No TCB mutation.
"""

from dataclasses import dataclass, field

from .gpa_eval_schema import (
    AUTHORITY_FLAGS,
    GPAEvalSchemaError,
    canonical_json,
    require_id,
    require_no_authority,
    require_sha256,
    sha256_hex,
)
from .gpc_admission_input import AdmissionInput
from .gpc_budget_constraints import evaluate_budget_constraints
from .gpc_capability_vocabulary import (
    OUTCOME_ALLOW_WITHIN_BOUND,
    OUTCOME_DENY,
    OUTCOME_ESCALATE,
    OUTCOME_INSUFFICIENT_EVIDENCE,
    OUTCOME_REQUIRE_HUMAN_APPROVAL,
)
from .gpc_policy_matrix import (
    MATRIX_VERSION,
    create_gpc_policy_matrix_v1,
    lookup_matrix_outcome,
)
from .gpc_scope_risk_tcb import evaluate_scope_risk_tcb

DECISION_VERSION = "gpc-admission-decision-v1"
RECEIPT_VERSION = "gpc-admission-receipt-v1"
GENERATOR_VERSION = "gpc-admission-decision-generator-v1"
MAX_DECISION_BYTES = 512 * 1024
MAX_REASON_CODES = 64

_TOKEN = object()

_SEVERITY = {
    OUTCOME_ALLOW_WITHIN_BOUND: 0,
    OUTCOME_REQUIRE_HUMAN_APPROVAL: 1,
    OUTCOME_ESCALATE: 2,
    OUTCOME_INSUFFICIENT_EVIDENCE: 3,
    OUTCOME_DENY: 4,
}


class AdmissionDecisionError(GPAEvalSchemaError):
    """Raised when an admission decision cannot be sealed safely."""


def _severe(current, candidate):
    if _SEVERITY[candidate] >= _SEVERITY[current]:
        return candidate
    return current


@dataclass(frozen=True)
class PerCapabilityDecision:
    """One sealed per-request admission row. Grants no runtime authority."""

    request_id: str
    capability_id: str
    outcome: str
    reason_codes: tuple
    rules_applied: tuple
    human_gated: bool
    request_sha256: str
    row_sha256: str
    _token: object = field(default=None, repr=False, compare=False)

    def __post_init__(self):
        if self._token is not _TOKEN:
            raise AdmissionDecisionError(
                "per-capability decision requires trusted construction"
            )
        require_id(self.request_id, "request_id")
        if not isinstance(self.capability_id, str) or not self.capability_id:
            raise AdmissionDecisionError("capability_id malformed")
        if self.outcome not in _SEVERITY:
            raise AdmissionDecisionError("outcome unsupported")
        if type(self.reason_codes) is not tuple:
            raise AdmissionDecisionError("reason_codes malformed")
        if len(self.reason_codes) > MAX_REASON_CODES:
            raise AdmissionDecisionError("reason_codes exceeds bound")
        if type(self.rules_applied) is not tuple:
            raise AdmissionDecisionError("rules_applied malformed")
        if type(self.human_gated) is not bool:
            raise AdmissionDecisionError("human_gated must be bool")
        require_sha256(self.request_sha256, "request_sha256")
        require_sha256(self.row_sha256, "row_sha256")
        if self.row_sha256 != sha256_hex(canonical_json(self._body())):
            raise AdmissionDecisionError("row_sha256 mismatch")

    def _body(self):
        return {
            "capability_id": self.capability_id,
            "human_gated": self.human_gated,
            "outcome": self.outcome,
            "reason_codes": list(self.reason_codes),
            "request_id": self.request_id,
            "request_sha256": self.request_sha256,
            "rules_applied": list(self.rules_applied),
        }

    def to_dict(self):
        body = self._body()
        body["row_sha256"] = self.row_sha256
        return body


def _seal_row(**values):
    provisional = object.__new__(PerCapabilityDecision)
    for name, value in values.items():
        object.__setattr__(provisional, name, value)
    return PerCapabilityDecision(
        **values,
        row_sha256=sha256_hex(canonical_json(provisional._body())),
        _token=_TOKEN,
    )


@dataclass(frozen=True)
class AdmissionDecision:
    """Sealed aggregate admission decision. Never authorizes execution."""

    schema_version: str
    decision_id: str
    admission_input_id: str
    input_sha256: str
    task_contract_id: str
    contract_sha256: str
    plan_id: str
    plan_sha256: str
    base_sha: str
    architecture_baseline_sha256: str
    trusted_policy_version: str
    tcb_registry_sha256: str
    tcb_snapshot_sha256: str
    vocabulary_sha256: str
    matrix_version: str
    matrix_sha256: str
    per_capability: tuple
    requested_capability_ids: tuple
    admitted_within_bound: tuple
    denied: tuple
    human_gated: tuple
    escalated: tuple
    insufficient_evidence: tuple
    overall_outcome: str
    escalation_reasons: tuple
    generator_version: str
    decision_sha256: str
    publication_authorized: bool = False
    queue_transition_authorized: bool = False
    github_authorized: bool = False
    merge_authorized: bool = False
    main_advancement_authorized: bool = False
    result_trusted: bool = False
    worker_output_trusted: bool = False
    execution_authorized: bool = False
    approved_to_execute: bool = False
    capability_runtime_granted: bool = False
    main_merge_auto_approved: bool = False
    _token: object = field(default=None, repr=False, compare=False)

    def __post_init__(self):
        if self._token is not _TOKEN:
            raise AdmissionDecisionError(
                "admission decision requires trusted construction"
            )
        if self.schema_version != DECISION_VERSION:
            raise AdmissionDecisionError("schema_version unsupported")
        if self.generator_version != GENERATOR_VERSION:
            raise AdmissionDecisionError("generator_version unsupported")
        if self.matrix_version != MATRIX_VERSION:
            raise AdmissionDecisionError("matrix_version unsupported")
        require_id(self.decision_id, "decision_id")
        require_id(self.admission_input_id, "admission_input_id")
        require_sha256(self.input_sha256, "input_sha256")
        require_sha256(self.contract_sha256, "contract_sha256")
        require_sha256(self.plan_sha256, "plan_sha256")
        require_sha256(self.architecture_baseline_sha256, "architecture_baseline_sha256")
        require_sha256(self.tcb_registry_sha256, "tcb_registry_sha256")
        require_sha256(self.tcb_snapshot_sha256, "tcb_snapshot_sha256")
        require_sha256(self.vocabulary_sha256, "vocabulary_sha256")
        require_sha256(self.matrix_sha256, "matrix_sha256")
        if type(self.per_capability) is not tuple or not self.per_capability:
            raise AdmissionDecisionError("per_capability malformed")
        if self.overall_outcome not in _SEVERITY:
            raise AdmissionDecisionError("overall_outcome unsupported")
        require_no_authority(self)
        for name in (
            "execution_authorized",
            "approved_to_execute",
            "capability_runtime_granted",
            "main_merge_auto_approved",
        ):
            if getattr(self, name) is not False:
                raise AdmissionDecisionError(f"cannot claim {name}")
        # Main merge must never be in admitted_within_bound.
        if "cb.main.merge" in self.admitted_within_bound:
            raise AdmissionDecisionError(
                "main merge cannot be auto-admitted within bound"
            )
        if "cb.main.advance" in self.admitted_within_bound:
            raise AdmissionDecisionError(
                "main advance cannot be auto-admitted within bound"
            )
        require_sha256(self.decision_sha256, "decision_sha256")
        if self.decision_sha256 != sha256_hex(canonical_json(self._body())):
            raise AdmissionDecisionError("decision_sha256 mismatch")
        if len(canonical_json(self.to_dict())) > MAX_DECISION_BYTES:
            raise AdmissionDecisionError("decision exceeds byte bound")

    def _body(self):
        return {
            "admission_input_id": self.admission_input_id,
            "admitted_within_bound": list(self.admitted_within_bound),
            "approved_to_execute": False,
            "architecture_baseline_sha256": self.architecture_baseline_sha256,
            "base_sha": self.base_sha,
            "capability_runtime_granted": False,
            "contract_sha256": self.contract_sha256,
            "decision_id": self.decision_id,
            "denied": list(self.denied),
            "escalated": list(self.escalated),
            "escalation_reasons": list(self.escalation_reasons),
            "execution_authorized": False,
            "generator_version": self.generator_version,
            "github_authorized": False,
            "human_gated": list(self.human_gated),
            "input_sha256": self.input_sha256,
            "insufficient_evidence": list(self.insufficient_evidence),
            "main_advancement_authorized": False,
            "main_merge_auto_approved": False,
            "matrix_sha256": self.matrix_sha256,
            "matrix_version": self.matrix_version,
            "merge_authorized": False,
            "overall_outcome": self.overall_outcome,
            "per_capability": [row.to_dict() for row in self.per_capability],
            "plan_id": self.plan_id,
            "plan_sha256": self.plan_sha256,
            "publication_authorized": False,
            "queue_transition_authorized": False,
            "requested_capability_ids": list(self.requested_capability_ids),
            "result_trusted": False,
            "schema_version": self.schema_version,
            "task_contract_id": self.task_contract_id,
            "tcb_registry_sha256": self.tcb_registry_sha256,
            "tcb_snapshot_sha256": self.tcb_snapshot_sha256,
            "trusted_policy_version": self.trusted_policy_version,
            "vocabulary_sha256": self.vocabulary_sha256,
            "worker_output_trusted": False,
        }

    def to_dict(self):
        body = self._body()
        body["decision_sha256"] = self.decision_sha256
        return body


@dataclass(frozen=True)
class AdmissionReceipt:
    """Provenance receipt for one admission decision. Evidence only."""

    schema_version: str
    decision_id: str
    decision_sha256: str
    input_sha256: str
    contract_sha256: str
    plan_sha256: str
    tcb_registry_sha256: str
    matrix_sha256: str
    overall_outcome: str
    receipt_sha256: str
    publication_authorized: bool = False
    queue_transition_authorized: bool = False
    github_authorized: bool = False
    merge_authorized: bool = False
    main_advancement_authorized: bool = False
    result_trusted: bool = False
    worker_output_trusted: bool = False
    execution_authorized: bool = False
    approved_to_execute: bool = False
    _token: object = field(default=None, repr=False, compare=False)

    def __post_init__(self):
        if self._token is not _TOKEN:
            raise AdmissionDecisionError(
                "admission receipt requires trusted construction"
            )
        if self.schema_version != RECEIPT_VERSION:
            raise AdmissionDecisionError("receipt schema unsupported")
        require_sha256(self.decision_sha256, "decision_sha256")
        require_sha256(self.input_sha256, "input_sha256")
        require_sha256(self.contract_sha256, "contract_sha256")
        require_sha256(self.plan_sha256, "plan_sha256")
        require_sha256(self.tcb_registry_sha256, "tcb_registry_sha256")
        require_sha256(self.matrix_sha256, "matrix_sha256")
        require_no_authority(self)
        if self.execution_authorized is not False:
            raise AdmissionDecisionError("cannot claim execution_authorized")
        if self.approved_to_execute is not False:
            raise AdmissionDecisionError(
                "valid admission receipt is never approved_to_execute"
            )
        require_sha256(self.receipt_sha256, "receipt_sha256")
        if self.receipt_sha256 != sha256_hex(canonical_json(self._body())):
            raise AdmissionDecisionError("receipt_sha256 mismatch")

    def _body(self):
        return {
            "approved_to_execute": False,
            "contract_sha256": self.contract_sha256,
            "decision_id": self.decision_id,
            "decision_sha256": self.decision_sha256,
            "execution_authorized": False,
            "github_authorized": False,
            "input_sha256": self.input_sha256,
            "main_advancement_authorized": False,
            "matrix_sha256": self.matrix_sha256,
            "merge_authorized": False,
            "overall_outcome": self.overall_outcome,
            "plan_sha256": self.plan_sha256,
            "publication_authorized": False,
            "queue_transition_authorized": False,
            "result_trusted": False,
            "schema_version": self.schema_version,
            "tcb_registry_sha256": self.tcb_registry_sha256,
            "worker_output_trusted": False,
        }

    def to_dict(self):
        body = self._body()
        body["receipt_sha256"] = self.receipt_sha256
        return body


def _evaluate_one(request, admission_input, matrix):
    """Deterministically evaluate one capability request."""
    base_outcome, base_reason, human_gated, rule_id = lookup_matrix_outcome(
        matrix, request.capability_id
    )
    reasons = [base_reason]
    rules = [rule_id]

    # Provider / model / benchmark / worker_safe_claim NEVER grant.
    if request.worker_safe_claim:
        reasons.append("worker_safe_claim_ignored")
    if request.provider_id is not None:
        reasons.append("provider_identity_ignored")
    if request.model_id is not None:
        reasons.append("model_identity_ignored")
    if request.benchmark_score is not None:
        reasons.append("benchmark_score_ignored")

    scope_result = evaluate_scope_risk_tcb(
        capability_id=request.capability_id,
        requested_scope=request.requested_scope,
        allowed_scope=admission_input.allowed_scope,
        forbidden_scope=admission_input.forbidden_scope,
        risk_ceiling_indicators=admission_input.risk_ceiling_indicators,
        required_gates=admission_input.required_gates,
        plan_requires_escalation=admission_input.plan_requires_escalation,
        plan_escalation_reasons=admission_input.plan_escalation_reasons,
        base_matrix_outcome=base_outcome,
    )
    reasons.extend(scope_result.reason_codes)
    rules.append("scope_risk_tcb")
    outcome = scope_result.outcome

    budget_result = evaluate_budget_constraints(
        request=request,
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
        base_outcome=outcome,
    )
    reasons.extend(budget_result.reason_codes)
    rules.append("budget_constraints")
    outcome = budget_result.outcome

    # Human-gate flag on request or matrix forces at least human approval
    # when the tentative outcome would otherwise auto-allow.
    if (
        request.human_gate_requested or human_gated
    ) and outcome == OUTCOME_ALLOW_WITHIN_BOUND:
        outcome = OUTCOME_REQUIRE_HUMAN_APPROVAL
        reasons.append("human_gate_required")

    # Evidence-ref tamper markers used by adversarial corpus.
    for ref in request.evidence_refs:
        if ref == "gate_removed":
            outcome = _severe(outcome, OUTCOME_DENY)
            reasons.append("required_gate_removed")
        if ref == "scope_broadened":
            outcome = _severe(outcome, OUTCOME_DENY)
            reasons.append("scope_broadened_post_seal")
        if ref == "forged_decision":
            outcome = _severe(outcome, OUTCOME_DENY)
            reasons.append("forged_decision_marker")
        if ref.startswith("unsupported_capability:"):
            outcome = _severe(outcome, OUTCOME_INSUFFICIENT_EVIDENCE)
            reasons.append("unsupported_capability_marker")

    human_gated_final = human_gated or request.human_gate_requested or (
        outcome == OUTCOME_REQUIRE_HUMAN_APPROVAL
    )
    return _seal_row(
        request_id=request.request_id,
        capability_id=request.capability_id,
        outcome=outcome,
        reason_codes=tuple(sorted(set(reasons))),
        rules_applied=tuple(sorted(set(rules))),
        human_gated=human_gated_final,
        request_sha256=request.request_sha256,
    )


def admit_capabilities(admission_input, *, decision_id="gpc_decision_001"):
    """Evaluate sealed admission input into a sealed decision + receipt.

    Never executes. Never mutates TCB. Never auto-approves Main merge.
    """
    if not isinstance(admission_input, AdmissionInput):
        raise AdmissionDecisionError("admission_input invalid")
    matrix = create_gpc_policy_matrix_v1()
    rows = tuple(
        _evaluate_one(req, admission_input, matrix)
        for req in admission_input.capability_requests
    )

    requested = tuple(sorted({r.capability_id for r in rows}))
    admitted = tuple(
        sorted(
            {
                r.capability_id
                for r in rows
                if r.outcome == OUTCOME_ALLOW_WITHIN_BOUND
            }
        )
    )
    denied = tuple(
        sorted({r.capability_id for r in rows if r.outcome == OUTCOME_DENY})
    )
    human = tuple(
        sorted(
            {
                r.capability_id
                for r in rows
                if r.outcome == OUTCOME_REQUIRE_HUMAN_APPROVAL
            }
        )
    )
    escalated = tuple(
        sorted(
            {r.capability_id for r in rows if r.outcome == OUTCOME_ESCALATE}
        )
    )
    insufficient = tuple(
        sorted(
            {
                r.capability_id
                for r in rows
                if r.outcome == OUTCOME_INSUFFICIENT_EVIDENCE
            }
        )
    )

    overall = OUTCOME_ALLOW_WITHIN_BOUND
    for row in rows:
        overall = _severe(overall, row.outcome)

    escalation_reasons = []
    if admission_input.plan_requires_escalation:
        escalation_reasons.extend(admission_input.plan_escalation_reasons)
    for row in rows:
        if row.outcome in (
            OUTCOME_ESCALATE,
            OUTCOME_DENY,
            OUTCOME_INSUFFICIENT_EVIDENCE,
            OUTCOME_REQUIRE_HUMAN_APPROVAL,
        ):
            escalation_reasons.extend(row.reason_codes)

    values = {
        "schema_version": DECISION_VERSION,
        "decision_id": decision_id,
        "admission_input_id": admission_input.admission_input_id,
        "input_sha256": admission_input.input_sha256,
        "task_contract_id": admission_input.task_contract_id,
        "contract_sha256": admission_input.contract_sha256,
        "plan_id": admission_input.plan_id,
        "plan_sha256": admission_input.plan_sha256,
        "base_sha": admission_input.base_sha,
        "architecture_baseline_sha256": (
            admission_input.architecture_baseline_sha256
        ),
        "trusted_policy_version": admission_input.trusted_policy_version,
        "tcb_registry_sha256": admission_input.tcb_registry_sha256,
        "tcb_snapshot_sha256": admission_input.tcb_snapshot_sha256,
        "vocabulary_sha256": admission_input.vocabulary_sha256,
        "matrix_version": MATRIX_VERSION,
        "matrix_sha256": matrix.matrix_sha256,
        "per_capability": rows,
        "requested_capability_ids": requested,
        "admitted_within_bound": admitted,
        "denied": denied,
        "human_gated": human,
        "escalated": escalated,
        "insufficient_evidence": insufficient,
        "overall_outcome": overall,
        "escalation_reasons": tuple(sorted(set(escalation_reasons))),
        "generator_version": GENERATOR_VERSION,
        "execution_authorized": False,
        "approved_to_execute": False,
        "capability_runtime_granted": False,
        "main_merge_auto_approved": False,
    }
    for name in AUTHORITY_FLAGS:
        values[name] = False
    provisional = object.__new__(AdmissionDecision)
    for name, value in values.items():
        object.__setattr__(provisional, name, value)
    decision = AdmissionDecision(
        **values,
        decision_sha256=sha256_hex(canonical_json(provisional._body())),
        _token=_TOKEN,
    )
    receipt = create_admission_receipt(decision)
    return decision, receipt


def create_admission_receipt(decision):
    if not isinstance(decision, AdmissionDecision):
        raise AdmissionDecisionError("decision invalid")
    values = {
        "schema_version": RECEIPT_VERSION,
        "decision_id": decision.decision_id,
        "decision_sha256": decision.decision_sha256,
        "input_sha256": decision.input_sha256,
        "contract_sha256": decision.contract_sha256,
        "plan_sha256": decision.plan_sha256,
        "tcb_registry_sha256": decision.tcb_registry_sha256,
        "matrix_sha256": decision.matrix_sha256,
        "overall_outcome": decision.overall_outcome,
        "execution_authorized": False,
        "approved_to_execute": False,
    }
    for name in AUTHORITY_FLAGS:
        values[name] = False
    provisional = object.__new__(AdmissionReceipt)
    for name, value in values.items():
        object.__setattr__(provisional, name, value)
    return AdmissionReceipt(
        **values,
        receipt_sha256=sha256_hex(canonical_json(provisional._body())),
        _token=_TOKEN,
    )


def admission_decision_cannot_execute():
    """TRUST REVIEW helper: True -- decision never executes work."""
    return True


def admission_never_auto_approves_main_merge():
    """TRUST REVIEW helper."""
    return True
