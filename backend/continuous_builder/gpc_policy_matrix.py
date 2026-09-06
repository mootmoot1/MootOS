"""GP-C3 -- Deterministic Capability Admission Policy Matrix (thin wrapper).

Authoritative matrix lives in ``gpc_trusted_admission_core``.
"""

from .gpc_trusted_admission_core import (
    MATRIX_VERSION,
    PolicyMatrix,
    PolicyRule,
    TrustedAdmissionError,
    create_gpc_policy_matrix_v1,
    lookup_matrix_outcome,
    policy_matrix_is_default_deny,
)

PolicyMatrixError = TrustedAdmissionError

__all__ = [
    "MATRIX_VERSION",
    "PolicyMatrix",
    "PolicyMatrixError",
    "PolicyRule",
    "create_gpc_policy_matrix_v1",
    "lookup_matrix_outcome",
    "policy_matrix_is_default_deny",
]
