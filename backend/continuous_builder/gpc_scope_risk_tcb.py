"""GP-C4 -- Scope / Risk / TCB Interaction (thin wrapper).

Authoritative rules live in ``gpc_trusted_admission_core``.
"""

from .gpc_trusted_admission_core import (
    ScopeRiskTCBResult,
    TrustedAdmissionError,
    evaluate_scope_risk_tcb,
)

ScopeRiskTCBError = TrustedAdmissionError

__all__ = [
    "ScopeRiskTCBError",
    "ScopeRiskTCBResult",
    "evaluate_scope_risk_tcb",
]
