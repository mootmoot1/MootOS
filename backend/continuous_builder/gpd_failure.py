"""GP-D failure taxonomy — small deterministic set.

Reuses Continuous Builder supervisor failure vocabulary where it already
fits; does not compete with GP-A / GP-C taxonomies.
"""

from __future__ import annotations

# Overlap with supervisor._FAILURE_CLASSES where meaningful.
FAILURE_CLASSES = frozenset({
    "failed",
    "crashed",
    "timed_out",
    "stalled",
    "cancelled",
    "termination_uncertain",
    "cleanup_uncertain",
    "containment_violation",
    "artifact_security_rejected",
    "unknown_failure",
    "admission_stale",
    "contract_stale",
    "checkpoint_tamper",
    "lease_owner_conflict",
    "sequence_violation",
    "duplicate_event",
    "malformed_event",
})

RETRYABLE_FAILURES = frozenset({
    "failed", "crashed", "timed_out", "stalled",
})

NON_RETRYABLE_WITHOUT_RECONCILE = frozenset({
    "termination_uncertain",
    "cleanup_uncertain",
    "unknown_failure",
})


class FailureClassificationError(ValueError):
    """Raised when a failure class is unsupported."""


def classify_failure(failure_class):
    if failure_class not in FAILURE_CLASSES:
        raise FailureClassificationError("failure class unsupported")
    return {
        "failure_class": failure_class,
        "retryable": failure_class in RETRYABLE_FAILURES,
        "requires_reconcile": failure_class in NON_RETRYABLE_WITHOUT_RECONCILE
        or failure_class.endswith("uncertain")
        or failure_class == "unknown_failure",
    }
