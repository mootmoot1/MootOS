"""Trusted semantic referee: is this exact candidate eligible right now?

Answers one narrow question over trusted, current facts and returns
deterministic blocker codes. It is not a supervisor, scheduler, Context
Engine, System Model, provider or worker runtime, and it holds no launch
authority: every authority flag is structurally False and eligibility is
explicitly not authorization.

Every input is either a trusted-constructed record or original signed
proof bytes. No caller-supplied boolean, clock, ceiling or gate list is
ever believed. Authentication of a human signature can only ever *remove*
the missing-gate blocker; it never overrides any other blocker, and an
approved subject may narrow admitted scope/capabilities, never widen them.
"""

from dataclasses import dataclass, fields
from datetime import datetime, timezone

from . import gpf_approval_authority as approval
from . import gpf_launch_candidate_binding as source
from .gpf_launch_facts import TrustedLaunchFacts
from .gpf_launch_state_projection import TrustedLaunchStateProjection
from .trusted_policy import (
    POLICY_VERSION, create_mootos_tcb_registry_v1,
    create_trusted_policy_snapshot,
)

VERSION = "gpf-launch-eligibility-v1"
MAX_APPROVALS = 32

# Canonical deterministic ordering. Reported blockers are always emitted in
# exactly this order regardless of evaluation order or input ordering.
BLOCKER_CODES = (
    "facts_stale",
    "binding_missing",
    "binding_mismatch",
    "reservation_missing",
    "reservation_mismatch",
    "attempt_superseded",
    "cancellation_requested",
    "cancelled",
    "execution_unknown",
    "reconciliation_required",
    "reconciling",
    "stalled",
    "timed_out",
    "failed",
    "job_terminal",
    "lease_ambiguous",
    "product_correlation_unverified",
    "admission_incompatible",
    "required_gate_missing",
    "approval_invalid",
    "approval_expired",
    "approval_wrong_attempt",
    "approval_wrong_request",
    "scope_widening",
    "capability_widening",
)
_ORDER = {code: index for index, code in enumerate(BLOCKER_CODES)}
# Identity failures make every downstream lifecycle claim meaningless, so
# they are reported alone rather than mixed with facts we cannot trust.
_FATAL = ("facts_stale", "binding_missing", "binding_mismatch")


class LaunchSemanticsError(ValueError):
    """Inputs were not trusted records; no eligibility can be computed."""


def _check(condition, reason):
    if not condition:
        raise LaunchSemanticsError(reason)


def _hash(value):
    return source._digest(source._canonical(value))


def _instant(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _identity_blockers(facts, projection):
    """Bind the projection to these exact facts and to the live binding."""
    blockers = set()
    if (projection.facts_sha256 != facts.facts_sha256 or
            projection.source_tokens_sha256 !=
            _hash(list(facts.source_tokens)) or
            (projection.job_id, projection.attempt_id, projection.request_id,
             projection.request_sha256, projection.header_sha256) !=
            (facts.job_id, facts.attempt_id, facts.request_id,
             facts.request_sha256, facts.header_sha256)):
        blockers.add("facts_stale")
        return blockers, None
    # Reload the authoritative assignment at the decision boundary; a record
    # the caller carried in is never accepted as proof it still exists.
    try:
        bound = source.load_launch_candidate_binding(
            job_id=facts.job_id, request_id=facts.request_id)
    except source.LaunchBindingError:
        blockers.add("binding_missing")
        return blockers, None
    if (bound.binding_sha256 != facts.binding_sha256 or
            bound.binding_sha256 != projection.binding_sha256 or
            (bound.attempt_id, bound.request_sha256, bound.header_sha256) !=
            (facts.attempt_id, facts.request_sha256, facts.header_sha256)):
        blockers.add("binding_mismatch")
        return blockers, None
    return blockers, bound


def _lifecycle_blockers(projection):
    blockers = set()
    for code in ("cancellation_requested", "cancelled", "execution_unknown",
                 "reconciliation_required", "reconciling", "stalled",
                 "timed_out", "failed", "job_terminal", "lease_ambiguous"):
        if getattr(projection, code) is True:
            blockers.add(code)
    if projection.attempt_is_current is not True:
        blockers.add("attempt_superseded")
    if projection.correlation_verified is not True:
        blockers.add("product_correlation_unverified")
    return blockers


def _reservation_blockers(facts, projection):
    if projection.reservation_present is not True:
        return {"reservation_missing"}
    expected = (facts.job_id, facts.attempt_id, facts.request_id,
                facts.request_sha256, facts.header_sha256)
    if tuple(projection.reservation_identity or ()) != expected:
        return {"reservation_mismatch"}
    return set()


def _admission_blockers(bound, projection):
    """Bound admission bytes plus live trusted-policy/TCB identity."""
    registry = create_mootos_tcb_registry_v1()
    if ((projection.admission_decision_id,
         projection.admission_decision_sha256) !=
            (bound.admission_decision_id, bound.admission_decision_sha256) or
            projection.trusted_policy_version != POLICY_VERSION or
            projection.tcb_registry_sha256 != registry.registry_sha256 or
            projection.tcb_snapshot_sha256 !=
            create_trusted_policy_snapshot().snapshot_sha256):
        return {"admission_incompatible"}
    return set()


def _approval_blockers(facts, projection, approvals, now):
    """Authenticate each proof, then interpret only what it may narrow."""
    blockers = set()
    satisfied = set()
    scope = set()
    capabilities = set()
    for item in approvals:
        _check(type(item) is tuple and len(item) == 3,
               "invalid approval proof")
        receipt_bytes, detached_signature, signer_key_id = item
        try:
            subject = approval.verify_human_approval_subject(
                receipt_bytes=receipt_bytes,
                detached_signature=detached_signature,
                signer_key_id=signer_key_id)
        except approval.ApprovalAuthorityError:
            blockers.add("approval_invalid")
            continue
        accepted = True
        if (subject.job_id, subject.attempt_id) != (facts.job_id,
                                                    facts.attempt_id):
            blockers.add("approval_wrong_attempt")
            accepted = False
        if ((subject.request_id, subject.request_sha256,
             subject.header_sha256) !=
                (facts.request_id, facts.request_sha256, facts.header_sha256)):
            blockers.add("approval_wrong_request")
            accepted = False
        if subject.valid_until is not None and _instant(
                subject.valid_until) <= now:
            blockers.add("approval_expired")
            accepted = False
        if not accepted:
            continue
        satisfied.add(subject.gate)
        scope.update(subject.approved_scope)
        capabilities.update(subject.approved_capability_ids)
    if not set(projection.required_gates) <= satisfied:
        blockers.add("required_gate_missing")
    # An approval may only narrow what admission already allowed.
    if not scope <= set(projection.allowed_scope) or scope & set(
            projection.forbidden_scope):
        blockers.add("scope_widening")
    if not capabilities <= set(projection.admitted_capability_ids):
        blockers.add("capability_widening")
    return blockers


@dataclass(frozen=True)
class TrustedLaunchEligibility:
    """Semantic verdict only. Eligibility is never launch authorization."""

    schema_version: str
    job_id: str
    attempt_id: str
    request_id: str
    eligible: bool
    blocker_codes: tuple
    eligibility_sha256: str

    def __getattr__(self, name):
        if name in source._FLAGS:
            return False
        raise AttributeError(name)

    def to_dict(self):
        body = {item.name: getattr(self, item.name) for item in fields(self)}
        body["blocker_codes"] = list(body["blocker_codes"])
        body.update({flag: False for flag in source._FLAGS})
        return body


def evaluate_launch_eligibility(*, facts, projection, approvals=()):
    """Decide eligibility of one bound candidate from trusted facts alone.

    ``approvals`` are original ``(receipt_bytes, detached_signature,
    signer_key_id)`` triples, reverified here; an evidence object a caller
    already holds is never accepted in their place. Expiry is judged against
    this process's clock, never a caller-supplied time.

    Returning ``eligible=True`` means only that no blocker applies at this
    instant. It grants nothing: no launch, dispatch, publication, merge or
    worker-result trust, and it must not be persisted as permission.
    """
    _check(type(facts) is TrustedLaunchFacts, "untrusted facts record")
    _check(type(projection) is TrustedLaunchStateProjection,
           "untrusted state projection")
    _check(type(approvals) is tuple and len(approvals) <= MAX_APPROVALS,
           "invalid approval collection")
    now = datetime.now(timezone.utc)
    blockers, bound = _identity_blockers(facts, projection)
    if bound is None:
        found = blockers & set(_FATAL)
    else:
        blockers |= _reservation_blockers(facts, projection)
        blockers |= _lifecycle_blockers(projection)
        blockers |= _admission_blockers(bound, projection)
        blockers |= _approval_blockers(facts, projection, approvals, now)
        found = blockers
    _check(found <= set(BLOCKER_CODES), "unknown blocker code")
    codes = tuple(sorted(found, key=_ORDER.__getitem__))
    values = dict(schema_version=VERSION, job_id=facts.job_id,
                  attempt_id=facts.attempt_id, request_id=facts.request_id,
                  eligible=not codes, blocker_codes=codes)
    provisional = object.__new__(TrustedLaunchEligibility)
    for name, value in dict(values, eligibility_sha256="").items():
        object.__setattr__(provisional, name, value)
    body = provisional.to_dict()
    body.pop("eligibility_sha256")
    return TrustedLaunchEligibility(**values, eligibility_sha256=_hash(body))


def launch_eligibility_grants_no_capability():
    """TRUST REVIEW helper: True -- eligibility is never authorization."""
    return True
