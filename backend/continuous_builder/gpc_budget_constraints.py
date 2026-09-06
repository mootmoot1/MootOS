"""GP-C5 -- Capability Budget / Constraint Checks.

Compares capability-request budgets against FrozenTaskContract ceilings.
Admission decides; runtime enforcement is deferred to GP-D/F.

Fail closed on increases beyond ceiling. Never grants execution authority.
"""

from dataclasses import dataclass

from .gpa_eval_schema import GPAEvalSchemaError
from .gpc_capability_vocabulary import (
    OUTCOME_ALLOW_WITHIN_BOUND,
    OUTCOME_DENY,
    OUTCOME_REQUIRE_HUMAN_APPROVAL,
)

_BUDGET_FIELDS = (
    ("budget_wall_clock_seconds", "budget_ceiling_wall_clock_seconds"),
    ("budget_input_tokens", "budget_ceiling_input_tokens"),
    ("budget_output_tokens", "budget_ceiling_output_tokens"),
)


class BudgetConstraintError(GPAEvalSchemaError):
    """Raised when budget constraint evaluation is malformed."""


@dataclass(frozen=True)
class BudgetConstraintResult:
    """Budget check outcome adjustment. Not an authority grant."""

    outcome: str
    reason_codes: tuple
    exceeded_fields: tuple


def evaluate_budget_constraints(
    *,
    request,
    budget_ceiling_wall_clock_seconds,
    budget_ceiling_input_tokens,
    budget_ceiling_output_tokens,
    budget_ceiling_cost_usd_cents,  # reserved; request has no cost field yet
    base_outcome,
):
    """Deny / human-gate when request budgets exceed contract ceilings.

    ``None`` ceilings mean "unbounded by contract" -- request values still
    must be well-formed (enforced at request seal time). A request that
    omits a budget while the contract has a ceiling is insufficient for
    auto-allow of write/exec-like capabilities.
    """
    del budget_ceiling_cost_usd_cents  # reserved for GP-D cost telemetry
    if base_outcome in (OUTCOME_DENY,):
        return BudgetConstraintResult(
            outcome=base_outcome,
            reason_codes=("budget_skipped_already_denied",),
            exceeded_fields=(),
        )

    ceilings = {
        "budget_wall_clock_seconds": budget_ceiling_wall_clock_seconds,
        "budget_input_tokens": budget_ceiling_input_tokens,
        "budget_output_tokens": budget_ceiling_output_tokens,
    }
    reasons = []
    exceeded = []
    outcome = base_outcome

    for req_field, ceiling_attr in _BUDGET_FIELDS:
        requested = getattr(request, req_field)
        ceiling = ceilings[req_field]
        if ceiling is None:
            continue
        if requested is None:
            reasons.append(f"missing_request_{req_field}")
            if outcome == OUTCOME_ALLOW_WITHIN_BOUND:
                outcome = OUTCOME_REQUIRE_HUMAN_APPROVAL
            continue
        if requested > ceiling:
            exceeded.append(req_field)
            reasons.append(f"exceeds_ceiling_{req_field}")
            outcome = OUTCOME_DENY

    # Explicit expansion markers on evidence refs (tamper corpus uses these).
    for ref in request.evidence_refs:
        if ref.startswith("budget_increase:"):
            exceeded.append(ref)
            reasons.append("explicit_budget_increase_request")
            outcome = OUTCOME_DENY

    if not reasons:
        reasons = ("budget_within_ceiling",)

    return BudgetConstraintResult(
        outcome=outcome,
        reason_codes=tuple(sorted(set(reasons))),
        exceeded_fields=tuple(sorted(set(exceeded))),
    )
