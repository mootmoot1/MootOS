"""Narrow trusted lifecycle projection of already-bound GP-D sources.

Reports normalized launch-critical facts for exactly one bound candidate.
It decides nothing: eligibility, gate satisfaction, admission compatibility
and launch authority all belong to the semantic referee that consumes this.

Lifecycle state is reduced by the authoritative GP-D reducer, never by a
private copy of the state machine. Only the fixed system-owned sources are
read; no caller supplies a root, store, connection, clock or boolean.
"""

from dataclasses import dataclass, fields
from datetime import datetime, timezone

from . import gpf_launch_candidate_binding as source
from . import gpf_launch_facts as facts_source
from .gpd_job_events import create_job_event
from .gpd_job_header import create_durable_job_header
from .gpd_job_state import TERMINAL_STATES, reduce_job_state

VERSION = "gpf-launch-state-projection-v1"
MAX_SOURCE_BYTES = 4 * 1024 * 1024
MAX_ROWS = 4096
_TUPLE_HEADER_FIELDS = (
    "approved_scope_ceiling", "forbidden_scope", "admitted_capability_ids",
    "required_gates",
)
# A reconciliation clears its attempt only when GP-D positively re-enabled
# retry and the verdict is not an unresolved conflict. Anything else keeps the
# job under human/reconciliation control and never becomes launch permission.
_UNRESOLVED_VERDICTS = frozenset({"side_effect_conflict"})


class LaunchStateProjectionError(ValueError):
    """Sources missing, inconsistent or unreadable; no eligibility asserted."""


def _check(condition, reason):
    if not condition:
        raise LaunchStateProjectionError(reason)


def _hash(value):
    return source._digest(source._canonical(value))


def _moment(value, label):
    _check(type(value) is str and 0 < len(value) <= 128, label)
    stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    _check(stamp.utcoffset() is not None, label)
    return stamp


def _rows(job, name, digest_field, required):
    try:
        raw = source._read(job, name, MAX_SOURCE_BYTES)
    except FileNotFoundError:
        _check(not required, "required GP-D source missing")
        return ()
    lines = raw.splitlines()
    _check(len(lines) <= MAX_ROWS, "GP-D source row bound")
    return tuple(source._sealed(line, digest_field) for line in lines)


def _header(job, job_id):
    body = source._sealed(source._read(job, "header.json"), "header_sha256")
    data = {key: tuple(value) if key in _TUPLE_HEADER_FIELDS and
            type(value) is list else value
            for key, value in body.items() if key != "header_sha256"}
    header = create_durable_job_header(**data)
    _check(header.header_sha256 == body["header_sha256"] and
           header.job_id == job_id, "header digest/identity drift")
    return header


def _events(job, header):
    events = []
    for row in _rows(job, "events.jsonl", "event_digest", True):
        data = {key: value for key, value in row.items()
                if key != "event_digest"}
        event = create_job_event(**data)
        _check(event.event_digest == row["event_digest"],
               "event digest drift on load")
        events.append(event)
    _check(bool(events), "empty required GP-D event source")
    return reduce_job_state(header, events)


def _attempts(job, job_id):
    rows = _rows(job, "attempts.jsonl", "attempt_sha256", True)
    _check(bool(rows), "empty required GP-D attempt source")
    for row in rows:
        _check(row.get("job_id") == job_id, "attempt belongs to another job")
    return source._id(rows[-1].get("attempt_id"))


def _leases(job, job_id, now):
    active = []
    for row in _rows(job, "leases.jsonl", "lease_sha256", False):
        _check(row.get("job_id") == job_id, "lease belongs to another job")
        if row.get("released_at") is None:
            source._id(row.get("attempt_id"))
            active.append((row["attempt_id"],
                           _moment(row.get("expires_at"), "lease expiry")))
    expired = tuple(attempt for attempt, expiry in active if expiry <= now)
    return tuple(attempt for attempt, _ in active), expired


def _reconciliations(job, job_id):
    cleared = set()
    holding = False
    for row in _rows(job, "reconciliations.jsonl", "reconciliation_sha256",
                     False):
        _check(row.get("job_id") == job_id,
               "reconciliation belongs to another job")
        source._id(row.get("attempt_id"))
        verdict = row.get("verdict")
        _check(type(verdict) is str, "reconciliation verdict malformed")
        retryable = row.get("retry_eligible_after")
        _check(type(retryable) is bool, "reconciliation retry flag malformed")
        if retryable and verdict not in _UNRESOLVED_VERDICTS:
            cleared.add(row["attempt_id"])
        else:
            holding = True
    return cleared, holding


def _reservation(job, attempt_id):
    try:
        with source._child(job, "attempts") as attempts, \
                source._child(attempts, attempt_id) as attempt:
            raw = source._read(attempt, "dispatch_reservation.json")
    except FileNotFoundError:
        return None, None
    row = source._sealed(raw, "reservation_sha256")
    identity = tuple(row.get(name) for name in (
        "job_id", "attempt_id", "request_id", "request_sha256",
        "header_sha256"))
    return row["reservation_sha256"], identity


def _correlation(request, bound):
    """Product assignment evidence must be signed into the request itself."""
    correlation = request.get("correlation")
    if type(correlation) is not dict:
        return False
    try:
        source._sealed(source._canonical(correlation), "digest")
    except source.LaunchBindingError:
        return False
    return all(correlation.get(name) == expected for name, expected in (
        ("job_id", bound.job_id),
        ("header_sha256", bound.header_sha256),
        ("blueprint_id", bound.blueprint_id),
        ("blueprint_sha256", bound.blueprint_sha256),
        ("slice_id", bound.slice_id),
    ))


@dataclass(frozen=True)
class TrustedLaunchStateProjection:
    """Normalized launch-critical facts; asserts no eligibility."""

    schema_version: str
    job_id: str
    attempt_id: str
    request_id: str
    facts_sha256: str
    source_tokens_sha256: str
    binding_sha256: str
    request_sha256: str
    header_sha256: str
    derived_state: str
    current_attempt_id: str
    attempt_is_current: bool
    cancellation_requested: bool
    cancelled: bool
    execution_unknown: bool
    reconciliation_required: bool
    reconciling: bool
    stalled: bool
    timed_out: bool
    failed: bool
    lease_present: bool
    lease_expired: bool
    lease_reconciled: bool
    lease_ambiguous: bool
    job_terminal: bool
    reservation_present: bool
    reservation_sha256: object
    reservation_identity: object
    correlation_verified: bool
    admission_decision_id: str
    admission_decision_sha256: str
    trusted_policy_version: str
    tcb_registry_sha256: str
    tcb_snapshot_sha256: str
    required_gates: tuple
    allowed_scope: tuple
    forbidden_scope: tuple
    admitted_capability_ids: tuple
    projected_at: str
    projection_sha256: str

    def __getattr__(self, name):
        if name in source._FLAGS:
            return False
        raise AttributeError(name)

    def to_dict(self):
        body = {item.name: getattr(self, item.name) for item in fields(self)}
        for name in ("required_gates", "allowed_scope", "forbidden_scope",
                     "admitted_capability_ids"):
            body[name] = list(body[name])
        if body["reservation_identity"] is not None:
            body["reservation_identity"] = list(body["reservation_identity"])
        body.update({flag: False for flag in source._FLAGS})
        return body


def _project(bound, request, now):
    with source._directory(source._AUTHORITATIVE_ROOT) as root, \
            source._child(root, "jobs") as jobs, \
            source._child(jobs, bound.job_id) as job:
        header = _header(job, bound.job_id)
        state = _events(job, header)
        latest_attempt = _attempts(job, bound.job_id)
        held, expired = _leases(job, bound.job_id, now)
        cleared, holding = _reconciliations(job, bound.job_id)
        reservation_sha256, identity = _reservation(job, bound.attempt_id)
    lease_expired = bool(expired)
    lease_reconciled = bool(expired) and set(expired) <= cleared
    # An expired lease is never proof that nothing executed: it stays
    # ambiguous until an explicit reconciliation clears that exact attempt.
    lease_ambiguous = (len(held) > 1 or (lease_expired and
                                         not lease_reconciled))
    unknown = state.execution_unknown
    values = dict(
        schema_version=VERSION, job_id=bound.job_id,
        attempt_id=bound.attempt_id, request_id=bound.request_id,
        binding_sha256=bound.binding_sha256,
        request_sha256=bound.request_sha256,
        header_sha256=bound.header_sha256,
        derived_state=state.state, current_attempt_id=latest_attempt,
        attempt_is_current=(
            latest_attempt == bound.attempt_id and
            state.active_attempt_id in (None, bound.attempt_id)),
        cancellation_requested=(state.cancellation_requested or
                                state.state == "cancellation_requested"),
        cancelled=state.state == "cancelled",
        job_terminal=state.state in ("terminal_success", "terminal_failure"),
        execution_unknown=unknown,
        reconciliation_required=(
            holding or unknown or lease_ambiguous or
            state.state in ("stalled", "timed_out", "failed")),
        reconciling=state.state == "reconciling",
        stalled=state.state == "stalled",
        timed_out=state.state == "timed_out",
        failed=state.state == "failed",
        lease_present=bool(held), lease_expired=lease_expired,
        lease_reconciled=lease_reconciled, lease_ambiguous=lease_ambiguous,
        reservation_present=reservation_sha256 is not None,
        reservation_sha256=reservation_sha256, reservation_identity=identity,
        correlation_verified=_correlation(request, bound),
        admission_decision_id=header.admission_decision_id,
        admission_decision_sha256=header.admission_decision_sha256,
        trusted_policy_version=header.trusted_policy_version,
        tcb_registry_sha256=header.tcb_registry_sha256,
        tcb_snapshot_sha256=header.tcb_snapshot_sha256,
        required_gates=tuple(header.required_gates),
        allowed_scope=tuple(header.approved_scope_ceiling),
        forbidden_scope=tuple(header.forbidden_scope),
        admitted_capability_ids=tuple(header.admitted_capability_ids),
    )
    _check(state.state not in TERMINAL_STATES or values["cancelled"] or
           values["job_terminal"], "unrecognised terminal state")
    return values


def project_launch_state(*, facts, request_bytes):
    """Revalidate facts, read lifecycle, revalidate again; any drift fails.

    The lifecycle read is bracketed by fresh source-token passes so a
    projection can never describe a job that changed underneath it.

    Returns ``(fresh_facts, projection)``: the projection is bound to the
    freshly rebuilt facts, not to the possibly older record the caller
    passed in, so a consumer cannot pair it with a different snapshot.
    Both are evidence, never a bearer token and never permission to launch.
    """
    fresh = facts_source.revalidate_launch_facts(
        facts, request_bytes=request_bytes)
    try:
        bound = source.load_launch_candidate_binding(
            job_id=fresh.job_id, request_id=fresh.request_id)
        _check(bound.binding_sha256 == fresh.binding_sha256 and
               bound.attempt_id == fresh.attempt_id,
               "binding drifted from facts")
        request = source._json(request_bytes)
        _check(request.get("digest") == fresh.request_sha256,
               "request differs from bound facts")
        values = _project(bound, request, datetime.now(timezone.utc))
    except (OSError, ValueError, KeyError, TypeError):
        raise LaunchStateProjectionError(
            "launch state sources invalid or unavailable") from None
    after = facts_source.revalidate_launch_facts(
        fresh, request_bytes=request_bytes)
    if after.source_tokens != fresh.source_tokens:
        raise facts_source.LaunchFactsStale(
            "sources changed during projection")
    values.update(
        facts_sha256=after.facts_sha256,
        source_tokens_sha256=_hash(list(fresh.source_tokens)),
        projected_at=datetime.now(timezone.utc).isoformat(),
    )
    provisional = object.__new__(TrustedLaunchStateProjection)
    for name, value in dict(values, projection_sha256="").items():
        object.__setattr__(provisional, name, value)
    body = provisional.to_dict()
    body.pop("projection_sha256")
    return after, TrustedLaunchStateProjection(
        **values, projection_sha256=_hash(body))
