"""GP-D3 -- Derived job state machine reducer.

Cached status is allowed only when reconstructible from the append-only
event log. Invalid transitions fail closed. Worker success claims alone
never become terminal_success.
"""

from __future__ import annotations

from dataclasses import dataclass

from .gpd_job_events import EVENT_KINDS, JobEvent, JobEventError
from .gpd_job_header import DurableJobHeader, JobHeaderError
from .gpa_eval_schema import canonical_json, sha256_hex

JOB_STATES = frozenset({
    "created",
    "admitted",
    "ready",
    "leased",
    "running",
    "waiting",
    "checkpointed",
    "cancellation_requested",
    "cancelled",
    "stalled",
    "timed_out",
    "failed",
    "execution_unknown",
    "reconciling",
    "retryable",
    "terminal_success",
    "terminal_failure",
})

TERMINAL_STATES = frozenset({
    "cancelled", "terminal_success", "terminal_failure",
})

# Explicit validated transitions. Keep few meaningful edges.
TRANSITIONS = {
    None: frozenset({"created"}),
    "created": frozenset({"admitted", "cancelled", "terminal_failure"}),
    "admitted": frozenset({"ready", "cancelled", "terminal_failure"}),
    "ready": frozenset({
        "leased", "cancellation_requested", "cancelled", "retryable",
    }),
    "leased": frozenset({
        "running", "cancellation_requested", "stalled", "timed_out",
        "execution_unknown", "cancelled",
    }),
    "running": frozenset({
        "waiting", "checkpointed", "cancellation_requested", "stalled",
        "timed_out", "failed", "execution_unknown", "terminal_success",
        "terminal_failure", "cancelled",
    }),
    "waiting": frozenset({
        "running", "checkpointed", "cancellation_requested", "stalled",
        "timed_out", "execution_unknown", "cancelled",
    }),
    "checkpointed": frozenset({
        "running", "waiting", "cancellation_requested", "stalled",
        "timed_out", "failed", "execution_unknown", "terminal_success",
        "terminal_failure", "cancelled",
    }),
    "cancellation_requested": frozenset({
        "cancelled", "execution_unknown", "reconciling",
    }),
    "stalled": frozenset({
        "reconciling", "execution_unknown", "retryable", "cancelled",
        "terminal_failure",
    }),
    "timed_out": frozenset({
        "reconciling", "execution_unknown", "retryable", "cancelled",
        "terminal_failure",
    }),
    "failed": frozenset({
        "retryable", "reconciling", "execution_unknown", "terminal_failure",
        "cancelled",
    }),
    "execution_unknown": frozenset({
        "reconciling", "cancelled", "terminal_failure",
    }),
    "reconciling": frozenset({
        "retryable", "cancelled", "terminal_success", "terminal_failure",
        "execution_unknown", "ready",
    }),
    "retryable": frozenset({
        "ready", "leased", "cancelled", "terminal_failure",
    }),
    "cancelled": frozenset(),
    "terminal_success": frozenset(),
    "terminal_failure": frozenset(),
}

EVENT_KIND_TO_STATE = {
    "job_created": "created",
    "job_admitted": "admitted",
    "job_ready": "ready",
    "lease_acquired": "leased",
    "running_marked": "running",
    "waiting": "waiting",
    "checkpoint_recorded": "checkpointed",
    "cancellation_requested": "cancellation_requested",
    "cancelled": "cancelled",
    "stalled": "stalled",
    "timed_out": "timed_out",
    "failed": "failed",
    "execution_unknown_declared": "execution_unknown",
    "reconciliation_recorded": "reconciling",
    "retryable_marked": "retryable",
    "terminal_success": "terminal_success",
    "terminal_failure": "terminal_failure",
}

# Event kinds that do not change primary state by themselves.
NON_TRANSITION_KINDS = frozenset({
    "heartbeat",
    "progress_noted",
    "side_effect_recorded",
    "attempt_started",
    "lease_released",
})


class JobStateError(JobEventError):
    """Raised when derived state cannot be reduced safely."""


@dataclass(frozen=True)
class DerivedJobState:
    job_id: str
    state: str
    sequence: int
    last_event_digest: object
    active_attempt_id: object
    cancellation_requested: bool
    execution_unknown: bool
    terminal: bool
    state_digest: str
    required_gates: tuple
    header_sha256: str

    def to_dict(self):
        return {
            "active_attempt_id": self.active_attempt_id,
            "cancellation_requested": self.cancellation_requested,
            "execution_unknown": self.execution_unknown,
            "header_sha256": self.header_sha256,
            "job_id": self.job_id,
            "last_event_digest": self.last_event_digest,
            "required_gates": list(self.required_gates),
            "sequence": self.sequence,
            "state": self.state,
            "state_digest": self.state_digest,
            "terminal": self.terminal,
        }


def _next_state(prior, event):
    if event.event_kind in NON_TRANSITION_KINDS:
        return prior
    target = EVENT_KIND_TO_STATE.get(event.event_kind)
    if target is None:
        raise JobStateError("event_kind has no state mapping")
    allowed = TRANSITIONS.get(prior, frozenset())
    if target not in allowed:
        raise JobStateError("invalid lifecycle transition")
    return target


def reduce_job_state(header, events):
    """Deterministically derive job state from header + events."""
    if not isinstance(header, DurableJobHeader):
        raise JobHeaderError("header invalid")
    if type(events) not in (list, tuple):
        raise JobStateError("events must be a sequence")
    state = None
    active_attempt = None
    cancellation_requested = False
    execution_unknown = False
    last_digest = None
    seq = 0
    for event in events:
        if not isinstance(event, JobEvent):
            raise JobStateError("event entry invalid")
        if event.job_id != header.job_id:
            raise JobStateError("event job binding mismatch")
        if event.sequence != seq + 1:
            raise JobStateError("sequence violation")
        if event.previous_event_digest != last_digest:
            raise JobStateError("event digest chain break")
        # Terminal states cannot silently reopen.
        if state in TERMINAL_STATES:
            raise JobStateError("terminal state cannot reopen")
        if event.event_kind == "attempt_started":
            if event.attempt_id is None:
                raise JobStateError("attempt_started requires attempt_id")
            active_attempt = event.attempt_id
        if event.event_kind == "cancellation_requested":
            cancellation_requested = True
        if event.event_kind == "execution_unknown_declared":
            execution_unknown = True
        if event.event_kind == "reconciliation_recorded":
            # Reconciliation may clear unknown only via explicit payload.
            if event.payload.get("clears_execution_unknown") is True:
                execution_unknown = False
        # Worker claim of success is evidence only — never terminal alone.
        if (
            event.event_kind == "terminal_success"
            and event.worker_claim
            and event.payload.get("system_proof") is not True
        ):
            raise JobStateError(
                "worker success alone cannot become terminal_success"
            )
        state = _next_state(state, event)
        last_digest = event.event_digest
        seq = event.sequence
    if state is None:
        raise JobStateError("empty history has no derived state")
    if state not in JOB_STATES:
        raise JobStateError("derived state unsupported")
    body = {
        "active_attempt_id": active_attempt,
        "cancellation_requested": cancellation_requested,
        "execution_unknown": execution_unknown or state == "execution_unknown",
        "header_sha256": header.header_sha256,
        "job_id": header.job_id,
        "last_event_digest": last_digest,
        "required_gates": list(header.required_gates),
        "sequence": seq,
        "state": state,
        "terminal": state in TERMINAL_STATES,
    }
    digest = sha256_hex(canonical_json(body))
    return DerivedJobState(
        job_id=header.job_id,
        state=state,
        sequence=seq,
        last_event_digest=last_digest,
        active_attempt_id=active_attempt,
        cancellation_requested=cancellation_requested,
        execution_unknown=body["execution_unknown"],
        terminal=body["terminal"],
        state_digest=digest,
        required_gates=header.required_gates,
        header_sha256=header.header_sha256,
    )


def assert_transition_allowed(prior_state, next_state):
    if next_state not in TRANSITIONS.get(prior_state, frozenset()):
        raise JobStateError("invalid lifecycle transition")
    return True
