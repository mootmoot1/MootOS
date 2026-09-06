"""GP-C4 -- Scope / Risk / TCB Interaction for Capability Admission.

Applies frozen-scope, System Model adjacency, TCB protected-path, taxonomy
risk indicators, required gates, and GP-B escalation interactions to a
capability request. TCB-adjacent paths are never treated as ordinary writes.

Queries ``trusted_policy.is_tcb_path`` / ``classify_tcb_path`` -- never
mutates the TCB registry. Descriptive risk never grants. Fail closed.
"""

from dataclasses import dataclass

from .gpa_eval_schema import GPAEvalSchemaError
from .gpc_capability_vocabulary import (
    OUTCOME_ALLOW_WITHIN_BOUND,
    OUTCOME_DENY,
    OUTCOME_ESCALATE,
    OUTCOME_INSUFFICIENT_EVIDENCE,
    OUTCOME_REQUIRE_HUMAN_APPROVAL,
)
from .trusted_policy import classify_tcb_path, is_tcb_path

# Risk indicators that force at least human approval when paired with writes.
_ELEVATED_RISK = frozenset(
    {
        "tcb_adjacent",
        "security_sensitive",
        "schema_migration",
        "irreversible_change",
        "policy_sensitive",
    }
)

# Capabilities that touch TCB / policy / Main / production -- always gated.
_TCB_POLICY_CAPS = frozenset(
    {
        "cb.trusted_policy.change",
        "cb.tcb.change",
        "cb.approval_rules.change",
        "cb.main.merge",
        "cb.main.advance",
        "cb.production.data",
        "cb.db.schema",
        "cb.deploy.staging",
        "cb.credentials",
        "cb.network",
    }
)

_WRITE_CAPS = frozenset(
    {
        "cb.file.write_bounded",
        "cb.trusted_policy.change",
        "cb.tcb.change",
        "cb.approval_rules.change",
        "cb.db.schema",
    }
)


class ScopeRiskTCBError(GPAEvalSchemaError):
    """Raised when scope/risk/TCB evaluation cannot proceed safely."""


@dataclass(frozen=True)
class ScopeRiskTCBResult:
    """Outcome adjustment from scope/risk/TCB rules. Not an authority grant."""

    outcome: str
    reason_codes: tuple
    tcb_paths_touched: tuple
    forbidden_paths_touched: tuple
    out_of_scope_paths: tuple
    escalated_from_gpb: bool


def _path_in_prefixes(path, prefixes):
    for prefix in prefixes:
        if path == prefix or path.startswith(prefix.rstrip("/") + "/"):
            return True
    return False


def evaluate_scope_risk_tcb(
    *,
    capability_id,
    requested_scope,
    allowed_scope,
    forbidden_scope,
    risk_ceiling_indicators,
    required_gates,
    plan_requires_escalation,
    plan_escalation_reasons,
    base_matrix_outcome,
):
    """Adjust a matrix outcome using scope / risk / TCB / GP-B escalation.

    Precedence (fail-closed, most severe wins among adjustments):
    1. unknown/insufficient from matrix stays
    2. forbidden / OOS / TCB write -> DENY or REQUIRE_HUMAN / ESCALATE
    3. GP-B escalation required -> ESCALATE (never silent broader admit)
    4. elevated descriptive risk on writes -> at least human approval
    5. otherwise keep base matrix outcome
    """
    if base_matrix_outcome == OUTCOME_INSUFFICIENT_EVIDENCE:
        return ScopeRiskTCBResult(
            outcome=OUTCOME_INSUFFICIENT_EVIDENCE,
            reason_codes=("matrix_insufficient_evidence",),
            tcb_paths_touched=(),
            forbidden_paths_touched=(),
            out_of_scope_paths=(),
            escalated_from_gpb=False,
        )

    reasons = []
    tcb_hit = []
    forbidden_hit = []
    oos = []
    allowed = tuple(allowed_scope)
    forbidden = tuple(forbidden_scope)
    scope = tuple(requested_scope)

    for path in scope:
        if path in forbidden or _path_in_prefixes(path, forbidden):
            forbidden_hit.append(path)
        if allowed and not _path_in_prefixes(path, allowed) and path not in allowed:
            # Exact-or-prefix: path must equal or live under an allowed path.
            if not any(
                path == a or path.startswith(a.rstrip("/") + "/") for a in allowed
            ):
                oos.append(path)
        if is_tcb_path(path):
            tcb_hit.append(path)

    tcb_hit = tuple(sorted(set(tcb_hit)))
    forbidden_hit = tuple(sorted(set(forbidden_hit)))
    oos = tuple(sorted(set(oos)))

    outcome = base_matrix_outcome

    if forbidden_hit:
        reasons.append("forbidden_scope_touch")
        outcome = OUTCOME_DENY

    if oos:
        reasons.append("out_of_scope_path")
        outcome = OUTCOME_DENY

    if tcb_hit:
        reasons.append("tcb_path_touch")
        # TCB-adjacent is never an ordinary bounded write.
        if capability_id in _WRITE_CAPS or capability_id in _TCB_POLICY_CAPS:
            reasons.append("tcb_write_requires_human")
            outcome = _severe(outcome, OUTCOME_REQUIRE_HUMAN_APPROVAL)
        else:
            outcome = _severe(outcome, OUTCOME_REQUIRE_HUMAN_APPROVAL)
        # Classification evidence (change_policy) further escalates human_only.
        for path in tcb_hit:
            classification = classify_tcb_path(path)
            if classification is not None and classification.change_policy in (
                "human_only",
                "protected_core_review",
            ):
                reasons.append(f"tcb_change_policy_{classification.change_policy}")
                outcome = _severe(outcome, OUTCOME_REQUIRE_HUMAN_APPROVAL)

    if capability_id in _TCB_POLICY_CAPS:
        reasons.append("tcb_or_policy_capability")
        outcome = _severe(outcome, OUTCOME_REQUIRE_HUMAN_APPROVAL)

    if capability_id == "cb.main.merge" or capability_id == "cb.main.advance":
        reasons.append("main_merge_or_advance_human_gated")
        outcome = _severe(outcome, OUTCOME_REQUIRE_HUMAN_APPROVAL)

    elevated = tuple(
        sorted(set(risk_ceiling_indicators) & _ELEVATED_RISK)
    )
    if elevated and capability_id in _WRITE_CAPS:
        reasons.append("elevated_descriptive_risk_on_write")
        outcome = _severe(outcome, OUTCOME_REQUIRE_HUMAN_APPROVAL)
        for code in elevated:
            reasons.append(f"risk_{code}")

    # Low descriptive risk must NEVER override forbidden / OOS / TCB deny.
    if (
        risk_ceiling_indicators == ("none",)
        or risk_ceiling_indicators == ("none",)
    ):
        if outcome == OUTCOME_DENY:
            reasons.append("low_risk_does_not_override_deny")

    if plan_requires_escalation:
        reasons.append("gpb_plan_requires_escalation")
        for code in plan_escalation_reasons:
            reasons.append(f"gpb_escalation:{code}")
        # Never silently admit broader capability when GP-B escalated.
        if outcome == OUTCOME_ALLOW_WITHIN_BOUND:
            outcome = OUTCOME_ESCALATE
            reasons.append("gpb_escalation_blocks_auto_allow")
        else:
            outcome = _severe(outcome, OUTCOME_ESCALATE)

    # Required gates still present -- removal is checked elsewhere (tamper).
    if not required_gates and capability_id in _WRITE_CAPS:
        reasons.append("missing_required_gates")
        outcome = _severe(outcome, OUTCOME_REQUIRE_HUMAN_APPROVAL)

    if not reasons:
        reasons = ("scope_risk_tcb_passthrough",)

    return ScopeRiskTCBResult(
        outcome=outcome,
        reason_codes=tuple(sorted(set(reasons))),
        tcb_paths_touched=tcb_hit,
        forbidden_paths_touched=forbidden_hit,
        out_of_scope_paths=oos,
        escalated_from_gpb=bool(plan_requires_escalation),
    )


_SEVERITY = {
    OUTCOME_ALLOW_WITHIN_BOUND: 0,
    OUTCOME_REQUIRE_HUMAN_APPROVAL: 1,
    OUTCOME_ESCALATE: 2,
    OUTCOME_INSUFFICIENT_EVIDENCE: 3,
    OUTCOME_DENY: 4,
}


def _severe(current, candidate):
    if _SEVERITY[candidate] >= _SEVERITY[current]:
        return candidate
    return current
