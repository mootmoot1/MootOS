"""GP-F4b -- Launch preparation / gate satisfaction evaluation.

Derives how close one launch candidate is to being launchable, and --
just as importantly -- records honestly *why it still is not*.

``evaluate_launch_preparation`` composes rather than duplicates: it runs
GP-F3's ``evaluate_supervisor_control`` (which already folds in GP-D's
derived job state, GP-F2 binding resolution, correlation verification,
dispatch reservation and lease evidence) and then adds exactly one new
question on top -- **are this job's required human gates satisfied for
this exact launch candidate?**

``launch_authorized`` is structurally always False
---------------------------------------------------

This module cannot set it True, and the dataclass refuses to be
constructed with it True. That is not a stub; it is the correct answer
today. Authorizing a launch requires proving the required human gates
were satisfied *by an authorized human*, and nothing in the current
architecture can prove that:

- A :class:`~gpf_human_approval_receipt.HumanApprovalReceipt` is
  digest-sealed, which proves its bytes were not edited. It does not
  prove who wrote them. Its ``supplied_approver_identity`` is
  caller-asserted and its ``approver_authenticated`` is structurally
  False.
- There is no authenticated human identity source, no trusted writer
  path for receipts, and no TCB component that owns approval for a GP-D
  launch. (``trusted_policy``'s ``cb_approval_authority`` covers
  *blueprint* approval evidence in ``chief_builder``, which is a
  different decision at a different layer, and carries the same
  ``approver_authenticated=False`` caveat.)

So the best state this module can ever reach is
``awaiting_trusted_approval_authority``: every required gate has a
structurally valid, correctly bound receipt, and launch is *still*
refused because structural validity is not authorization.
``missing_trusted_mechanism`` names what is absent. Closing that gap is a
trust-boundary change and is deliberately out of this module's reach.

Required gates come from the authoritative header
--------------------------------------------------

``required_gates`` is read from ``store.load_header(job_id)``, never from
``request.human_gates``. GP-E's ``validate_worker_request`` (run inside
GP-F2, inside GP-F3) already proves the two agree, so this is redundant
by construction -- but it is redundant in the safe direction: the gate
list this module fails closed against is the one nobody in the request
path supplied.

Presence of a required gate is the *opposite* of approval: an unmatched
required gate yields ``awaiting_human_gate``. A required gate is only
ever considered satisfied by an explicit receipt naming that gate and
binding this exact attempt and request digest.

Fail-closed receipt handling
-----------------------------

A supplied receipt that does not validate is never silently ignored --
its presence is itself an anomaly, so it blocks:

- a receipt bound to a superseded attempt or a different request packet,
  or an expired one, blocks (``human_approval_receipt_invalid``);
- a receipt naming a gate this job does not require blocks -- one gate's
  receipt must not quietly satisfy, or be filed against, another
  (``human_approval_receipt_invalid``);
- two differing receipts for the same gate block rather than letting a
  caller pick the permissive one (``human_approval_receipt_conflict``).

Zero authority: the standard false-flag vocabulary plus explicit
``launch_authorized``/``dispatch_authorized``/``worker_invoked``, all
structurally False. This module never launches a worker, never calls a
provider, never touches the network or credentials, never mutates GitHub
or Main, and never writes GP-D or product state.
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
    require_text,
    sha256_hex,
)
from .gpf_human_approval_receipt import (
    HumanApprovalReceipt,
    HumanApprovalReceiptError,
    validate_human_approval_receipt,
)
from .gpf_supervisor import (
    BLOCKED_REASONS as SUPERVISOR_BLOCKED_REASONS,
    evaluate_supervisor_control,
)
from .timestamps import parse_timestamp

LAUNCH_PREPARATION_VERSION = "gpf-launch-preparation-v1"
MAX_PREPARATION_BYTES = 8 * 1024
MAX_GATES = 32
_TOKEN = object()

# The only two GP-F3 control states from which a launch could even be
# contemplated. Everything else -- cancelled, execution_unknown,
# reconciling, stalled, timed_out, failed, cancellation_requested,
# blocked -- means "not a launch candidate right now".
_LAUNCH_READY_CONTROL_STATES = frozenset({
    "launch_pending", "dispatch_reserved",
})

# GP-F4-specific blocking reasons, unioned with GP-F3's own vocabulary so
# a supervisor-supplied reason propagates verbatim instead of being
# renamed into a synonym.
_F4_BLOCKED_REASONS = frozenset({
    "supervisor_control_not_launch_ready",
    "human_approval_receipt_invalid",
    "human_approval_receipt_conflict",
})
BLOCKED_REASONS = SUPERVISOR_BLOCKED_REASONS | _F4_BLOCKED_REASONS

LAUNCH_READINESS_STATES = frozenset({
    # GP-F3 (or GP-D beneath it) says this is not a launch candidate.
    "blocked",
    # At least one required human gate has no valid receipt.
    "awaiting_human_gate",
    # Every required gate has a structurally valid receipt, and launch is
    # still refused: structural validity is not authorization.
    "awaiting_trusted_approval_authority",
    # No human gates required and nothing blocking -- still unauthorized,
    # because minting launch authority is itself a boundary this module
    # does not hold.
    "prepared_pending_launch_authority",
})

# What is missing before launch_authorized could ever be True.
MISSING_AUTHENTICATED_HUMAN_APPROVAL = "authenticated_human_approval_source"
MISSING_TRUSTED_LAUNCH_AUTHORITY = "trusted_launch_authority"
MISSING_TRUSTED_MECHANISMS = frozenset({
    MISSING_AUTHENTICATED_HUMAN_APPROVAL,
    MISSING_TRUSTED_LAUNCH_AUTHORITY,
})


class LaunchPreparationError(GPAEvalSchemaError):
    """Raised when a launch preparation decision cannot be sealed safely."""


def _utcnow_iso():
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class LaunchPreparationDecision:
    """Evidence snapshot of launch readiness. Never launch authority."""

    schema_version: str
    job_id: str
    attempt_id: str
    request_id: str
    request_sha256: str
    launch_readiness: str
    blocked_reason: object
    control_state: str
    supervisor_decision_sha256: str
    required_gates: tuple
    satisfied_gates: tuple
    unsatisfied_gates: tuple
    receipt_digests: tuple
    missing_trusted_mechanism: object
    prepared_at: str
    preparation_sha256: str
    trusted_human_authority: bool = False
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
            raise LaunchPreparationError(
                "launch preparation decision requires trusted construction"
            )
        if self.schema_version != LAUNCH_PREPARATION_VERSION:
            raise LaunchPreparationError("schema_version is unsupported")
        for name in ("job_id", "attempt_id", "request_id"):
            require_id(getattr(self, name), name)
        for name in ("request_sha256", "supervisor_decision_sha256",
                     "preparation_sha256"):
            require_sha256(getattr(self, name), name)
        if self.launch_readiness not in LAUNCH_READINESS_STATES:
            raise LaunchPreparationError("launch_readiness is unsupported")
        if self.blocked_reason is not None:
            if self.launch_readiness != "blocked":
                raise LaunchPreparationError(
                    "blocked_reason may only be set when launch_readiness is "
                    "'blocked'"
                )
            if self.blocked_reason not in BLOCKED_REASONS:
                raise LaunchPreparationError("blocked_reason is unsupported")
        elif self.launch_readiness == "blocked":
            raise LaunchPreparationError("'blocked' requires a blocked_reason")
        require_text(self.control_state, "control_state", 64)
        for name in ("required_gates", "satisfied_gates", "unsatisfied_gates"):
            value = getattr(self, name)
            if type(value) is not tuple:
                raise LaunchPreparationError(f"{name} malformed")
            if len(value) > MAX_GATES:
                raise LaunchPreparationError(f"{name} exceeds bound")
            if value != tuple(sorted(set(value))):
                raise LaunchPreparationError(f"{name} must be sorted unique")
            for gate in value:
                require_text(gate, name, 64)
        satisfied, unsatisfied = set(self.satisfied_gates), set(
            self.unsatisfied_gates
        )
        if satisfied & unsatisfied:
            raise LaunchPreparationError(
                "a gate cannot be both satisfied and unsatisfied"
            )
        if satisfied | unsatisfied != set(self.required_gates):
            raise LaunchPreparationError(
                "satisfied and unsatisfied gates must partition required_gates"
            )
        if type(self.receipt_digests) is not tuple:
            raise LaunchPreparationError("receipt_digests malformed")
        if len(self.receipt_digests) > MAX_GATES:
            raise LaunchPreparationError("receipt_digests exceeds bound")
        if self.receipt_digests != tuple(sorted(set(self.receipt_digests))):
            raise LaunchPreparationError(
                "receipt_digests must be sorted unique"
            )
        for digest in self.receipt_digests:
            require_sha256(digest, "receipt_digests")
        if self.missing_trusted_mechanism is not None:
            if (
                self.missing_trusted_mechanism
                not in MISSING_TRUSTED_MECHANISMS
            ):
                raise LaunchPreparationError(
                    "missing_trusted_mechanism is unsupported"
                )
        parse_timestamp(
            self.prepared_at, "prepared_at", LaunchPreparationError,
        )
        if self.trusted_human_authority is not False:
            raise LaunchPreparationError(
                "no trusted human approval authority exists -- a preparation "
                "decision can never claim one"
            )
        for name in (
            "launch_authorized", "dispatch_authorized", "worker_invoked",
        ):
            if getattr(self, name) is not False:
                raise LaunchPreparationError(
                    "launch preparation can never authorize launch/dispatch "
                    "or claim a worker was invoked"
                )
        for name in AUTHORITY_FLAGS:
            if getattr(self, name, False) is not False:
                raise LaunchPreparationError(
                    "launch preparation decision cannot claim authority"
                )
        if self.preparation_sha256 != sha256_hex(canonical_json(self._body())):
            raise LaunchPreparationError("preparation_sha256 mismatch")
        if len(canonical_json(self.to_dict())) > MAX_PREPARATION_BYTES:
            raise LaunchPreparationError("preparation exceeds byte bound")

    def _body(self):
        return {
            "attempt_id": self.attempt_id,
            "blocked_reason": self.blocked_reason,
            "control_state": self.control_state,
            "dispatch_authorized": False,
            "github_authorized": False,
            "job_id": self.job_id,
            "launch_authorized": False,
            "launch_readiness": self.launch_readiness,
            "main_advancement_authorized": False,
            "merge_authorized": False,
            "missing_trusted_mechanism": self.missing_trusted_mechanism,
            "prepared_at": self.prepared_at,
            "publication_authorized": False,
            "queue_transition_authorized": False,
            "receipt_digests": list(self.receipt_digests),
            "request_id": self.request_id,
            "request_sha256": self.request_sha256,
            "required_gates": list(self.required_gates),
            "result_trusted": False,
            "satisfied_gates": list(self.satisfied_gates),
            "schema_version": self.schema_version,
            "supervisor_decision_sha256": self.supervisor_decision_sha256,
            "trusted_human_authority": False,
            "unsatisfied_gates": list(self.unsatisfied_gates),
            "worker_invoked": False,
            "worker_output_trusted": False,
        }

    def to_dict(self):
        body = dict(self._body())
        body["preparation_sha256"] = self.preparation_sha256
        return body


def _seal(values):
    for name in AUTHORITY_FLAGS:
        values[name] = False
    values["trusted_human_authority"] = False
    values["launch_authorized"] = False
    values["dispatch_authorized"] = False
    values["worker_invoked"] = False
    provisional = object.__new__(LaunchPreparationDecision)
    for name, value in values.items():
        object.__setattr__(provisional, name, value)
    return LaunchPreparationDecision(
        **values,
        preparation_sha256=sha256_hex(canonical_json(provisional._body())),
        _token=_TOKEN,
    )


def _classify_receipts(receipts, *, request, required_gates, at):
    """Return ``(satisfied_gates, receipt_digests, blocked_reason)``.

    Fail closed: any invalid, misfiled, or conflicting receipt blocks
    outright rather than being dropped from consideration.
    """
    by_gate = {}
    for receipt in receipts:
        if not isinstance(receipt, HumanApprovalReceipt):
            return (), (), "human_approval_receipt_invalid"
        if receipt.gate not in required_gates:
            # A receipt filed against a gate this job does not require is
            # never harmless -- it means the receipt and the authoritative
            # header disagree about what this launch candidate needs.
            return (), (), "human_approval_receipt_invalid"
        seen = by_gate.get(receipt.gate)
        if seen is not None and seen.receipt_sha256 != receipt.receipt_sha256:
            return (), (), "human_approval_receipt_conflict"
        by_gate[receipt.gate] = receipt

    satisfied = []
    digests = []
    for gate, receipt in by_gate.items():
        try:
            validate_human_approval_receipt(
                receipt, request=request, gate=gate, at=at,
            )
        except (HumanApprovalReceiptError, ValueError):
            return (), (), "human_approval_receipt_invalid"
        satisfied.append(gate)
        digests.append(receipt.receipt_sha256)
    return (
        tuple(sorted(set(satisfied))), tuple(sorted(set(digests))), None,
    )


def evaluate_launch_preparation(
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
    approval_receipts=(),
    correlation_verifier=None,
    require_verified_correlation=True,
    stall_heartbeats=(),
    prepared_at=None,
):
    """Derive one :class:`LaunchPreparationDecision` from current truth.

    Read-only. Composes GP-F3's supervisor control decision, then
    evaluates human gate satisfaction on top. Never returns
    ``launch_authorized=True`` -- see the module docstring for exactly
    which trusted mechanism is missing.
    """
    prepared_at = prepared_at or _utcnow_iso()
    decision = evaluate_supervisor_control(
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
        require_verified_correlation=require_verified_correlation,
        stall_heartbeats=stall_heartbeats,
        evaluated_at=prepared_at,
    )
    # Authoritative gate list -- reloaded from the durable header, never
    # taken from request.human_gates.
    header = store.load_header(job_id)
    required_gates = tuple(sorted(set(header.required_gates)))

    satisfied = ()
    receipt_digests = ()
    if decision.control_state not in _LAUNCH_READY_CONTROL_STATES:
        launch_readiness = "blocked"
        blocked_reason = (
            decision.blocked_reason
            if decision.blocked_reason is not None
            else "supervisor_control_not_launch_ready"
        )
    else:
        satisfied, receipt_digests, blocked_reason = _classify_receipts(
            approval_receipts,
            request=request,
            required_gates=required_gates,
            at=prepared_at,
        )
        if blocked_reason is not None:
            launch_readiness = "blocked"
            satisfied, receipt_digests = (), ()
        elif not required_gates:
            launch_readiness = "prepared_pending_launch_authority"
        elif set(satisfied) == set(required_gates):
            # Structurally complete, and still not authorized: a digest
            # proves integrity, not who approved.
            launch_readiness = "awaiting_trusted_approval_authority"
        else:
            launch_readiness = "awaiting_human_gate"

    unsatisfied = tuple(
        gate for gate in required_gates if gate not in set(satisfied)
    )
    if launch_readiness == "prepared_pending_launch_authority":
        missing = MISSING_TRUSTED_LAUNCH_AUTHORITY
    elif launch_readiness in (
        "awaiting_human_gate", "awaiting_trusted_approval_authority",
    ):
        missing = MISSING_AUTHENTICATED_HUMAN_APPROVAL
    else:
        missing = None

    values = {
        "schema_version": LAUNCH_PREPARATION_VERSION,
        "job_id": job_id,
        "attempt_id": attempt_id,
        "request_id": decision.request_id,
        "request_sha256": request.digest,
        "launch_readiness": launch_readiness,
        "blocked_reason": blocked_reason,
        "control_state": decision.control_state,
        "supervisor_decision_sha256": decision.decision_sha256,
        "required_gates": required_gates,
        "satisfied_gates": tuple(sorted(set(satisfied))),
        "unsatisfied_gates": unsatisfied,
        "receipt_digests": receipt_digests,
        "missing_trusted_mechanism": missing,
        "prepared_at": prepared_at,
    }
    return _seal(values)


def reseal_launch_preparation_from_storage(**values):
    """Reconstruct a decision from trusted, already digest-verified
    on-disk fields. NOT for minting one from untrusted input."""
    return _seal(dict(values))


def trusted_human_approval_authority_exists():
    """TRUST REVIEW helper: always False.

    No authenticated human identity source and no trusted writer path for
    approval receipts exist in this phase, so no amount of structurally
    valid evidence can establish that an authorized human satisfied a
    gate.
    """
    return False


def launch_preparation_grants_no_capability():
    """TRUST REVIEW helper: True -- preparation grants no capability."""
    return True
