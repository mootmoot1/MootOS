"""GP-C5 -- Capability Budget / Constraint Checks (thin wrapper).

Authoritative budget checks live in ``gpc_trusted_admission_core``.
"""

from .gpc_trusted_admission_core import (
    BudgetConstraintResult,
    TrustedAdmissionError,
    evaluate_budget_constraints,
)

BudgetConstraintError = TrustedAdmissionError

__all__ = [
    "BudgetConstraintError",
    "BudgetConstraintResult",
    "evaluate_budget_constraints",
]
