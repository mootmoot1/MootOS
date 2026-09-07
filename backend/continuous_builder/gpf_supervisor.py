"""GP-F3 -- Single-Worker Supervisor / Control Layer.

Coordinates control decisions around **existing** GP-D truth; it does not
replace or duplicate it. ``evaluate_supervisor_control`` is a pure
evidence-derivation function: it only reads through ``JobLedgerStore``
(authoritative GP-D header/events/attempts/leases) plus F1's
``DispatchReservation`` and F2's ``resolve_launch_bindings``, and seals a
:class:`SupervisorControlDecision` describing where things currently
stand. It never launches a worker, never calls a provider, never touches
the network or credentials, and never grants launch authority.

Dispatch reservation is not proof of launch
--------------------------------------------

A recorded :class:`~gpf_dispatch_reservation.DispatchReservation` proves
only that a GP-E ``WorkerRequest`` reserved the dispatch slot for one
GP-D attempt. It never proves a worker actually launched or executed.
This module keeps that boundary explicit by never producing a
post-launch control state (``running``, ``result_received``, ...) from
reservation evidence alone -- those states can only ever come from GP-D's
own derived job state (``running_marked`` and later events), which this
module has no way to fabricate. Two crash windows this design must not
collapse:

A. Reservation written, supervisor crashes, worker never launched.
   ``control_state`` stays ``"dispatch_reserved"`` (or ``"launch_pending"``
   before a reservation even exists) -- never advances to a post-launch
   state on its own.
B. Reservation written, launch begins, supervisor crashes before durable
   launch evidence is recorded. Once (a future) GP-D event marks
   uncertainty, ``reduce_job_state`` already derives ``execution_unknown``
   or ``reconciling`` -- this module reads and *respects* that derived
   state; it never overrides it with anything more optimistic.

State vocabulary -- reuse over invention
-----------------------------------------

Wherever the fact in question already has a GP-D job-state name
(``gpd_job_state.JOB_STATES``), this module reuses that exact name --
never a renamed synonym. The only genuinely new concepts, because GP-D's
job-level state machine has no notion of the *pre-launch* domain at all,
are:

- ``dispatch_reserved`` -- a matching, non-conflicting
  ``DispatchReservation`` exists for the current attempt, but GP-D's own
  derived state has not (yet) reached ``running``.
- ``launch_pending`` -- bindings resolved clean, no blocking condition
  found, but no dispatch reservation exists yet.
- ``blocked`` -- a GP-F-specific launch-readiness gate failed for a
  reason GP-D's own vocabulary has no name for (see
  :data:`BLOCKED_REASONS`): a superseded/mismatched binding, a dispatch
  reservation conflict, required product correlation left unverified, or
  an unreconciled expired lease. Note ``reduce_job_state``'s own
  ``"reconciling"`` state already covers what the caller's requirements
  called "reconciliation_required" -- deliberately not re-invented here.

``running``, ``launch_authorized``, ``result_received``,
``quarantine_pending``, ``verification_pending`` and ``proposed_success``
are reserved in :data:`CONTROL_STATES` for forward compatibility (GP-F4
launch, GP-F5 quarantine, GP-F6 result intake, GP-F7 verification) but
are never produced by this module -- there is no worker/result channel
into this function at all, so a worker's completion claim structurally
cannot move this module's decision past the pre-launch domain.

Correlation is evidence, never authority
------------------------------------------

By default (``require_verified_correlation=True``, the fail-closed
posture), a request whose slice/job correlation is not both *present*
and *independently verified* (GP-F2's ``correlation_verifier``) is
``blocked`` -- an unverified or absent correlation record is never
treated as authoritative product-plane confirmation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from .gpa_eval_schema import (
    AUTHORITY_FLAGS,
    GPAEvalSchemaError,
    canonical_json,
    require_id,
    require_sha256,
    sha256_hex,
)
from .gpd_heartbeat_lease import (
    HeartbeatLeaseError,
    assert_single_active_lease,
    heartbeat_without_progress_is_stall_evidence,
)
from .gpd_job_state import JOB_STATES, reduce_job_state
from .gpf_binding_resolution import BindingResolutionError, resolve_launch_bindings
from .timestamps import parse_timestamp

SUPERVISOR_DECISION_VERSION = "gpf-supervisor-decision-v1"
MAX_DECISION_BYTES = 4 * 1024
_TOKEN = object()

# GP-D-derived job states that unconditionally take precedence over any
# pre-launch evaluation below -- reused verbatim, never renamed.
_GPD_BLOCKING_STATES = frozenset({
    "timed_out", "stalled", "failed", "execution_unknown", "reconciling",
    "cancelled",
})

BLOCKED_REASONS = frozenset({
    "binding_resolution_failed",
    "correlation_required_but_unverified",
    "dispatch_reservation_conflict",
    "lease_conflict",
    "lease_expired_unreconciled",
})

# Reachable outcomes of evaluate_supervisor_control() today.
_REACHABLE_NOW = frozenset({
    "dispatch_reserved",
    "launch_pending",
    "blocked",
    "cancellation_requested",
    "cancelled",
    "stalled",
    "timed_out",
    "execution_unknown",
    "reconciling",
    "failed",
})

# Full intended vocabulary, including states only a future slice
# (GP-F4 launch / GP-F5 quarantine / GP-F6 result intake / GP-F7
# verification) can ever produce. Declared here so later slices reuse
# these exact names instead of inventing synonyms.
CONTROL_STATES = _REACHABLE_NOW | frozenset({
    "launch_authorized",
    "running",
    "result_received",
    "quarantine_pending",
    "verification_pending",
    "proposed_success",
})

# Names deliberately reused verbatim from gpd_job_state.JOB_STATES --
# never redefined with a different meaning here.
_REUSED_FROM_GPD_JOB_STATE = frozenset({
    "cancellation_requested", "cancelled", "stalled", "timed_out",
    "execution_unknown", "reconciling", "failed",
})
assert _REUSED_FROM_GPD_JOB_STATE <= JOB_STATES, (
    "every control state claimed as 'reused from GP-D' must be a real "
    "gpd_job_state.JOB_STATES member"
)


class SupervisorError(GPAEvalSchemaError):
    """Raised when a supervisor control decision cannot be sealed safely."""


def _utcnow_iso():
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class SupervisorControlDecision:
    """Evidence snapshot of pre-launch control state. Never launch authority.

    Always re-derivable from the same authoritative GP-D/GP-F evidence --
    treat this the same way ``gpd_job_state.DerivedJobState`` treats
    itself: a cache of a pure reduction, never a competing source of
    truth.
    """

    schema_version: str
    job_id: str
    attempt_id: str
    request_id: str
    control_state: str
    blocked_reason: object
    job_derived_state: str
    job_state_digest: str
    reservation_sha256: object
    bindings_sha256: object
    lease_conflict: bool
    stall_evidence: bool
    evaluated_at: str
    decision_sha256: str
    launch_authorized: bool = False
    dispatch_authorized: bool = False
    worker_invoked: bool = False
    publication_authorized: bool = False
    queue_transition_authorized: bool = False
    github_authorized: bool = False
    merge_authorized: bool = False
    main_advancement_authorized: bool = False
    result_trusted: bool = False
    worker_output_trusted: bool = False
    _token: object = field(default=None, repr=False, compare=False)

    def __post_init__(self):
        if self._token is not _TOKEN:
            raise SupervisorError(
                "supervisor control decision requires trusted construction"
            )
        if self.schema_version != SUPERVISOR_DECISION_VERSION:
            raise SupervisorError("schema_version is unsupported")
        for name in ("job_id", "attempt_id", "request_id"):
            require_id(getattr(self, name), name)
        if self.control_state not in CONTROL_STATES:
            raise SupervisorError("control_state is unsupported")
        if self.control_state not in _REACHABLE_NOW:
            raise SupervisorError(
                "this module can never produce a post-launch control_state"
            )
        if self.blocked_reason is not None:
            if self.control_state != "blocked":
                raise SupervisorError(
                    "blocked_reason may only be set when control_state is "
                    "'blocked'"
                )
            if self.blocked_reason not in BLOCKED_REASONS:
                raise SupervisorError("blocked_reason is unsupported")
        elif self.control_state == "blocked":
            raise SupervisorError("'blocked' requires a blocked_reason")
        if self.job_derived_state not in JOB_STATES:
            raise SupervisorError("job_derived_state is unsupported")
        require_sha256(self.job_state_digest, "job_state_digest")
        if self.reservation_sha256 is not None:
            require_sha256(self.reservation_sha256, "reservation_sha256")
        if self.bindings_sha256 is not None:
            require_sha256(self.bindings_sha256, "bindings_sha256")
        for name in ("lease_conflict", "stall_evidence"):
            if type(getattr(self, name)) is not bool:
                raise SupervisorError(f"{name} must be a bool")
        parse_timestamp(self.evaluated_at, "evaluated_at", SupervisorError)
        for name in (
            "launch_authorized", "dispatch_authorized", "worker_invoked",
        ):
            if getattr(self, name) is not False:
                raise SupervisorError(
                    "a supervisor control decision can never claim launch/"
                    "dispatch authority or having invoked a worker"
                )
        for name in AUTHORITY_FLAGS:
            if getattr(self, name, False) is not False:
                raise SupervisorError(
                    "supervisor control decision cannot claim authority"
                )
        require_sha256(self.decision_sha256, "decision_sha256")
        if self.decision_sha256 != sha256_hex(canonical_json(self._body())):
            raise SupervisorError("decision_sha256 mismatch")
        if len(canonical_json(self.to_dict())) > MAX_DECISION_BYTES:
            raise SupervisorError("decision exceeds byte bound")

    def _body(self):
        return {
            "attempt_id": self.attempt_id,
            "bindings_sha256": self.bindings_sha256,
            "blocked_reason": self.blocked_reason,
            "control_state": self.control_state,
            "dispatch_authorized": False,
            "evaluated_at": self.evaluated_at,
            "github_authorized": False,
            "job_derived_state": self.job_derived_state,
            "job_id": self.job_id,
            "job_state_digest": self.job_state_digest,
            "launch_authorized": False,
            "lease_conflict": self.lease_conflict,
            "main_advancement_authorized": False,
            "merge_authorized": False,
            "publication_authorized": False,
            "queue_transition_authorized": False,
            "request_id": self.request_id,
            "reservation_sha256": self.reservation_sha256,
            "result_trusted": False,
            "schema_version": self.schema_version,
            "stall_evidence": self.stall_evidence,
            "worker_invoked": False,
            "worker_output_trusted": False,
        }

    def to_dict(self):
        body = dict(self._body())
        body["decision_sha256"] = self.decision_sha256
        return body


def _seal(values):
    for name in AUTHORITY_FLAGS:
        values[name] = False
    values["launch_authorized"] = False
    values["dispatch_authorized"] = False
    values["worker_invoked"] = False
    provisional = object.__new__(SupervisorControlDecision)
    for name, value in values.items():
        object.__setattr__(provisional, name, value)
    return SupervisorControlDecision(
        **values,
        decision_sha256=sha256_hex(canonical_json(provisional._body())),
        _token=_TOKEN,
    )


def evaluate_supervisor_control(
    *,
    store,
    job_id,
    attempt_id,
    request,
    contract,
    plan,
    admission,
    admission_input,
    package,
    correlation_verifier=None,
    require_verified_correlation=True,
    stall_heartbeats=(),
    evaluated_at=None,
):
    """Derive one :class:`SupervisorControlDecision` from current truth.

    Reads only -- never launches a worker, never calls a provider, never
    touches the network or credentials, never mutates GitHub, never
    writes to GP-D or product state. Callers that want an audit trail of
    evaluations over time use
    :meth:`gpd_job_store.JobLedgerStore.append_supervisor_decision`
    explicitly; this function does not persist anything itself.
    """
    evaluated_at = evaluated_at or _utcnow_iso()
    header = store.load_header(job_id)
    events = store.load_events(job_id)
    derived = reduce_job_state(header, events)
    reservation = store.load_dispatch_reservation(job_id, attempt_id)

    request_id = getattr(request, "request_id", None) or attempt_id
    bindings = None

    if derived.cancellation_requested and derived.state != "cancelled":
        control_state, blocked_reason = "cancellation_requested", None
    elif derived.state in _GPD_BLOCKING_STATES:
        control_state, blocked_reason = derived.state, None
    else:
        try:
            bindings = resolve_launch_bindings(
                store=store,
                job_id=job_id,
                attempt_id=attempt_id,
                request=request,
                contract=contract,
                plan=plan,
                admission=admission,
                admission_input=admission_input,
                package=package,
                correlation_verifier=correlation_verifier,
                resolved_at=evaluated_at,
            )
        except BindingResolutionError:
            control_state, blocked_reason = "blocked", "binding_resolution_failed"
        else:
            correlation_ok = (
                bindings.correlation_present and bindings.correlation_verified
            )
            if require_verified_correlation and not correlation_ok:
                control_state = "blocked"
                blocked_reason = "correlation_required_but_unverified"
            elif reservation is None:
                control_state, blocked_reason = "launch_pending", None
            elif reservation.request_sha256 != request.digest:
                control_state = "blocked"
                blocked_reason = "dispatch_reservation_conflict"
            else:
                control_state, blocked_reason = "dispatch_reserved", None

    leases = store.load_leases(job_id)
    lease_conflict = False
    try:
        assert_single_active_lease(leases, job_id)
    except HeartbeatLeaseError:
        lease_conflict = True
    # An expired-but-not-released lease is never proof execution stopped
    # (or never happened) -- it stays ambiguous until explicit
    # reconciliation, so it blocks rather than clears the way to launch.
    expired_unreleased = any(
        lease.released_at is None and lease.is_expired(evaluated_at)
        for lease in leases
        if lease.job_id == job_id
    )
    stall_evidence = bool(
        stall_heartbeats
        and heartbeat_without_progress_is_stall_evidence(stall_heartbeats)
    )

    if control_state in ("dispatch_reserved", "launch_pending"):
        if lease_conflict:
            control_state, blocked_reason = "blocked", "lease_conflict"
        elif expired_unreleased:
            control_state, blocked_reason = "blocked", "lease_expired_unreconciled"
        elif stall_evidence:
            control_state, blocked_reason = "stalled", None

    values = {
        "schema_version": SUPERVISOR_DECISION_VERSION,
        "job_id": job_id,
        "attempt_id": attempt_id,
        "request_id": request_id,
        "control_state": control_state,
        "blocked_reason": blocked_reason,
        "job_derived_state": derived.state,
        "job_state_digest": derived.state_digest,
        "reservation_sha256": (
            reservation.reservation_sha256 if reservation is not None else None
        ),
        "bindings_sha256": (
            bindings.bindings_sha256 if bindings is not None else None
        ),
        "lease_conflict": lease_conflict,
        "stall_evidence": stall_evidence,
        "evaluated_at": evaluated_at,
    }
    return _seal(values)


def reseal_supervisor_decision_from_storage(**values):
    """Reconstruct a :class:`SupervisorControlDecision` from trusted,
    already digest-verified on-disk fields.

    NOT for minting a new decision from arbitrary/untrusted input -- used
    only by :meth:`gpd_job_store.JobLedgerStore.load_supervisor_decisions`
    to rebuild sealed objects from bytes this same process already wrote.
    """
    return _seal(dict(values))


def supervisor_grants_no_capability():
    """TRUST REVIEW helper: True -- a control decision grants no capability."""
    return True
