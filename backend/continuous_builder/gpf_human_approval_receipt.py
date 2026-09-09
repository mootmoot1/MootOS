"""GP-F4a -- Sealed human approval / gate-satisfaction receipt.

Answers exactly one question, for exactly one launch candidate: **did
someone explicitly record that required gate X was satisfied for this
attempt and this exact GP-E ``WorkerRequest``?**

Why this is a separate record, not a GP-D event
------------------------------------------------

GP-D remains *execution truth*: what the system observed happening. Human
approval is a different authority input entirely -- it is an assertion
about what a person permitted, not about what executed. Minting it as a
generic GP-D event would make GP-D's own append path a source of human
authorization, so any actor that can append an event could manufacture
approval. This module therefore keeps approval in its own sealed record
that GP-F4 may *consume and bind*, and that GP-D never produces.

A digest proves integrity, not authorship
------------------------------------------

Sealing this receipt proves only that its bound fields have not been
edited since sealing. It proves **nothing** about who created it. There
is no authenticated human identity source in this phase, so
``supplied_approver_identity`` is exactly that -- *supplied*, unverified,
caller-asserted -- and ``approver_authenticated`` is structurally always
False (the same posture, and the same field name, as
``chief_builder.BlueprintApprovalEvidence``). Consumers must therefore
distinguish two different things:

- **structurally valid** -- :func:`validate_human_approval_receipt`
  passes: the receipt is well-formed, unexpired, and bound to this exact
  launch candidate and gate.
- **trusted human approval** -- an authorized human actually made this
  decision. Nothing in this module can establish that; see
  :func:`receipt_is_trusted_human_approval`, which is unconditionally
  False, and GP-F4b's ``missing_trusted_mechanism``.

Human approval is never *inferred*. Not from the presence of
``required_gates``/``human_gates`` (that states a gate is *required*, the
exact opposite of satisfied), not from worker or provider claims, not
from a GP-D terminal state, not from a dispatch reservation, not from
supervisor control state, and not from a correlation record. Only an
explicit receipt naming the gate counts, and even then only structurally.

Non-transferable, and bounded in what it can ever mean
-------------------------------------------------------

Every receipt binds ``job_id``, ``attempt_id``, ``request_id``, the full
``WorkerRequest`` digest, and the authoritative header digest, so it is
specific to one launch candidate. A retry is a new GP-D ``attempt_id``
with a new request digest, so an old receipt cannot be replayed onto it
-- it fails closed at :func:`validate_human_approval_receipt` rather
than silently carrying over. ``gate`` is bound too, so a receipt for one
gate can never satisfy an unrelated gate.

The approved subject is bound explicitly and narrowly: capability ids
must already be admitted for this request and scope must already be
inside the request's allowed scope, so a receipt can only ever *narrow*,
never expand, what was already admitted. Capabilities that would move
Main, publish to GitHub, deploy, reach credentials/network, or change
trusted policy/TCB are refused outright at mint time
(:data:`NON_APPROVABLE_CAPABILITY_IDS`) -- those need a trusted approval
authority that does not exist yet, and a receipt this module can mint
must never be mistakable for one.

Zero authority: the standard false-flag vocabulary plus explicit
``launch_authorized``/``dispatch_authorized``, all structurally False.
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
    require_sorted_unique_paths,
    require_text,
    sha256_hex,
)
from .gpc_trusted_admission_core import CAPABILITY_IDS
from .gpe_protocol import WorkerRequest
from .timestamps import parse_timestamp

RECEIPT_SCHEMA_VERSION = "gpf-human-approval-receipt-v1"
MAX_RECEIPT_BYTES = 8 * 1024
MAX_APPROVED_CAPABILITIES = 32
MAX_APPROVED_SCOPE = 64
_TOKEN = object()

# Capabilities a receipt minted here may never name. Each one is an
# authority this phase explicitly cannot grant (Main merge/advance,
# GitHub publication, deployment, production data, credentials, network,
# schema migration, or trusted-policy/TCB/approval-rule mutation).
# Refusing at mint time means a well-formed receipt can never even be
# *shaped* like authorization for them.
NON_APPROVABLE_CAPABILITY_IDS = frozenset({
    "cb.main.merge",
    "cb.main.advance",
    "cb.pr.create",
    "cb.github.metadata",
    "cb.deploy.staging",
    "cb.production.data",
    "cb.credentials",
    "cb.network",
    "cb.db.schema",
    "cb.trusted_policy.change",
    "cb.tcb.change",
    "cb.approval_rules.change",
})
assert NON_APPROVABLE_CAPABILITY_IDS <= CAPABILITY_IDS, (
    "every non-approvable capability must be a real GP-C capability id"
)


class HumanApprovalReceiptError(GPAEvalSchemaError):
    """Raised when an approval receipt cannot be sealed or bound safely."""


def _utcnow_iso():
    return datetime.now(timezone.utc).isoformat()


def _require_gate(value, label="gate"):
    return require_text(value, label, 64)


def _subject_digest(approved_capability_ids, approved_scope):
    return sha256_hex(canonical_json({
        "approved_capability_ids": list(approved_capability_ids),
        "approved_scope": list(approved_scope),
    }))


@dataclass(frozen=True)
class HumanApprovalReceipt:
    """One sealed, non-transferable gate-satisfaction assertion.

    Structural integrity only. Never proof of who approved, and never
    launch authority -- see the module docstring.
    """

    schema_version: str
    job_id: str
    attempt_id: str
    request_id: str
    request_sha256: str
    header_sha256: str
    gate: str
    approval_id: str
    supplied_approver_identity: str
    approved_capability_ids: tuple
    approved_scope: tuple
    subject_sha256: str
    created_at: str
    valid_until: object
    receipt_sha256: str
    approver_authenticated: bool = False
    launch_authorized: bool = False
    dispatch_authorized: bool = False
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
            raise HumanApprovalReceiptError(
                "approval receipt requires trusted construction"
            )
        if self.schema_version != RECEIPT_SCHEMA_VERSION:
            raise HumanApprovalReceiptError("schema_version is unsupported")
        for name in ("job_id", "attempt_id", "request_id", "approval_id"):
            require_id(getattr(self, name), name)
        for name in ("request_sha256", "header_sha256", "receipt_sha256",
                     "subject_sha256"):
            require_sha256(getattr(self, name), name)
        _require_gate(self.gate)
        require_text(
            self.supplied_approver_identity, "supplied_approver_identity", 256,
        )
        if type(self.approved_capability_ids) is not tuple:
            raise HumanApprovalReceiptError(
                "approved_capability_ids malformed"
            )
        if len(self.approved_capability_ids) > MAX_APPROVED_CAPABILITIES:
            raise HumanApprovalReceiptError(
                "approved_capability_ids exceeds bound"
            )
        if self.approved_capability_ids != tuple(
            sorted(set(self.approved_capability_ids))
        ):
            raise HumanApprovalReceiptError(
                "approved_capability_ids must be sorted unique"
            )
        if not set(self.approved_capability_ids) <= CAPABILITY_IDS:
            raise HumanApprovalReceiptError(
                "approved_capability_ids contains an unknown capability"
            )
        if set(self.approved_capability_ids) & NON_APPROVABLE_CAPABILITY_IDS:
            raise HumanApprovalReceiptError(
                "a receipt can never approve merge/publication/deploy/"
                "credentials/network/schema/trusted-policy capabilities"
            )
        require_sorted_unique_paths(
            self.approved_scope, "approved_scope", MAX_APPROVED_SCOPE,
        )
        if self.subject_sha256 != _subject_digest(
            self.approved_capability_ids, self.approved_scope
        ):
            raise HumanApprovalReceiptError("subject_sha256 mismatch")
        created = parse_timestamp(
            self.created_at, "created_at", HumanApprovalReceiptError,
        )
        if self.valid_until is not None:
            # Compare parsed datetimes, never raw strings -- two equal
            # instants can spell their offset differently, so lexical
            # ordering is not instant ordering (same idiom as
            # gpd_heartbeat_lease.LeaseRecord.is_expired).
            expires = parse_timestamp(
                self.valid_until, "valid_until", HumanApprovalReceiptError,
            )
            if expires <= created:
                raise HumanApprovalReceiptError(
                    "valid_until must be after created_at"
                )
        if self.approver_authenticated is not False:
            raise HumanApprovalReceiptError(
                "external approver authentication is absent -- a receipt "
                "can never claim its approver was authenticated"
            )
        for name in ("launch_authorized", "dispatch_authorized"):
            if getattr(self, name) is not False:
                raise HumanApprovalReceiptError(
                    "an approval receipt can never claim launch/dispatch "
                    "authority"
                )
        for name in AUTHORITY_FLAGS:
            if getattr(self, name, False) is not False:
                raise HumanApprovalReceiptError(
                    "approval receipt cannot claim authority"
                )
        if self.receipt_sha256 != sha256_hex(canonical_json(self._body())):
            raise HumanApprovalReceiptError("receipt_sha256 mismatch")
        if len(canonical_json(self.to_dict())) > MAX_RECEIPT_BYTES:
            raise HumanApprovalReceiptError("receipt exceeds byte bound")

    def _body(self):
        return {
            "approval_id": self.approval_id,
            "approved_capability_ids": list(self.approved_capability_ids),
            "approved_scope": list(self.approved_scope),
            "approver_authenticated": False,
            "attempt_id": self.attempt_id,
            "created_at": self.created_at,
            "dispatch_authorized": False,
            "gate": self.gate,
            "github_authorized": False,
            "header_sha256": self.header_sha256,
            "job_id": self.job_id,
            "launch_authorized": False,
            "main_advancement_authorized": False,
            "merge_authorized": False,
            "publication_authorized": False,
            "queue_transition_authorized": False,
            "request_id": self.request_id,
            "request_sha256": self.request_sha256,
            "result_trusted": False,
            "schema_version": self.schema_version,
            "subject_sha256": self.subject_sha256,
            "supplied_approver_identity": self.supplied_approver_identity,
            "valid_until": self.valid_until,
            "worker_output_trusted": False,
        }

    def to_dict(self):
        body = dict(self._body())
        body["receipt_sha256"] = self.receipt_sha256
        return body


def _seal(values):
    for name in AUTHORITY_FLAGS:
        values[name] = False
    values["approver_authenticated"] = False
    values["launch_authorized"] = False
    values["dispatch_authorized"] = False
    provisional = object.__new__(HumanApprovalReceipt)
    for name, value in values.items():
        object.__setattr__(provisional, name, value)
    return HumanApprovalReceipt(
        **values,
        receipt_sha256=sha256_hex(canonical_json(provisional._body())),
        _token=_TOKEN,
    )


def create_human_approval_receipt(
    *,
    request,
    gate,
    approval_id,
    supplied_approver_identity,
    approved_capability_ids=(),
    approved_scope=(),
    created_at=None,
    valid_until=None,
):
    """Seal one receipt against a validated GP-E ``WorkerRequest``.

    **This function is an authority boundary, and it does not currently
    sit behind one.** It cannot authenticate the caller, so what it
    produces is a *structurally valid assertion*, never trusted human
    approval. It is deliberately kept outside the TCB and deliberately
    incapable of naming any capability in
    :data:`NON_APPROVABLE_CAPABILITY_IDS`.

    Like ``create_dispatch_reservation``, this takes the whole
    already-validated request object rather than loose fields, so a
    caller cannot mint a receipt whose ids/digests disagree with the
    launch candidate it claims to approve.

    ``gate`` must already be one of the request's ``human_gates``. That
    is a *relevance* check -- a receipt for a gate this candidate does
    not require is meaningless -- and never an approval inference: a
    required gate with no receipt stays unsatisfied.

    ``valid_until`` is optional. The receipt is already non-transferable
    via ``attempt_id``/``request_sha256``, so expiry is a secondary
    bound: it limits how long a *pre*-approval recorded before a launch
    window stays usable. When absent, no time bound is claimed; when
    present, it is enforced fail-closed at validation.
    """
    if not isinstance(request, WorkerRequest):
        raise HumanApprovalReceiptError("request is invalid")
    _require_gate(gate)
    if gate not in request.human_gates:
        raise HumanApprovalReceiptError(
            "gate is not a required human gate for this launch candidate"
        )
    if type(approved_capability_ids) is not tuple:
        raise HumanApprovalReceiptError("approved_capability_ids malformed")
    capabilities = tuple(sorted(set(approved_capability_ids)))
    # Refuse the never-approvable set first, unconditionally. It must not
    # depend on what this particular request happens to have admitted --
    # otherwise the error a caller sees for "cb.main.merge" would be the
    # weaker, contingent "not admitted" rather than the categorical
    # "a receipt can never approve this".
    if set(capabilities) & NON_APPROVABLE_CAPABILITY_IDS:
        raise HumanApprovalReceiptError(
            "a receipt can never approve merge/publication/deploy/"
            "credentials/network/schema/trusted-policy capabilities"
        )
    if not set(capabilities) <= set(request.admitted_capability_ids):
        raise HumanApprovalReceiptError(
            "approved capabilities must already be admitted for this request"
        )
    scope = tuple(sorted(set(approved_scope)))
    if not set(scope) <= set(request.allowed_scope):
        raise HumanApprovalReceiptError(
            "approved scope must be inside the request's allowed scope -- a "
            "receipt can narrow, never expand, admitted scope"
        )
    if set(scope) & set(request.forbidden_scope):
        raise HumanApprovalReceiptError(
            "approved scope intersects the request's forbidden scope"
        )
    values = {
        "schema_version": RECEIPT_SCHEMA_VERSION,
        "job_id": request.job_id,
        "attempt_id": request.attempt_id,
        "request_id": request.request_id,
        "request_sha256": request.digest,
        "header_sha256": request.header_sha256,
        "gate": gate,
        "approval_id": approval_id,
        "supplied_approver_identity": supplied_approver_identity,
        "approved_capability_ids": capabilities,
        "approved_scope": scope,
        "subject_sha256": _subject_digest(capabilities, scope),
        "created_at": created_at or _utcnow_iso(),
        "valid_until": valid_until,
    }
    return _seal(values)


def reseal_human_approval_receipt_from_storage(**values):
    """Reconstruct a receipt from trusted, already digest-verified
    on-disk fields.

    NOT for minting a receipt from arbitrary/untrusted input -- used only
    by :meth:`gpd_job_store.JobLedgerStore.load_human_approval_receipts`
    to rebuild sealed objects from bytes this same process already wrote
    and is about to digest-check again.
    """
    restored = dict(values)
    # JSON has no tuple: sequence fields come back as lists, so coerce
    # them before sealing (same normalization gpd_job_header does for its
    # own tuple fields on load).
    for name in ("approved_capability_ids", "approved_scope"):
        if name in restored:
            restored[name] = tuple(restored[name])
    return _seal(restored)


def validate_human_approval_receipt(receipt, *, request, gate, at=None):
    """Fail closed unless ``receipt`` binds this exact launch candidate.

    Proves *structural* validity only. Passing this never means an
    authorized human approved anything -- see
    :func:`receipt_is_trusted_human_approval`.
    """
    if not isinstance(receipt, HumanApprovalReceipt):
        raise HumanApprovalReceiptError("approval receipt is invalid")
    # Re-verify the seal here, not just at construction: an in-memory
    # object can be built around __post_init__, so consumption must not
    # assume the instance it was handed was ever sealed honestly.
    if receipt.receipt_sha256 != sha256_hex(canonical_json(receipt._body())):
        raise HumanApprovalReceiptError("receipt_sha256 mismatch")
    if receipt.approver_authenticated is not False:
        raise HumanApprovalReceiptError(
            "external approver authentication is absent"
        )
    if not isinstance(request, WorkerRequest):
        raise HumanApprovalReceiptError("request is invalid")
    _require_gate(gate)
    if receipt.gate != gate:
        raise HumanApprovalReceiptError(
            "receipt approves a different gate -- one gate's receipt never "
            "satisfies another"
        )
    if gate not in request.human_gates:
        raise HumanApprovalReceiptError(
            "gate is not a required human gate for this launch candidate"
        )
    # Any one of these differing means the receipt belongs to a different
    # (older/superseded) attempt or request packet: fail closed, never
    # carry an approval forward onto a new launch candidate.
    for name, expected in (
        ("job_id", request.job_id),
        ("attempt_id", request.attempt_id),
        ("request_id", request.request_id),
        ("request_sha256", request.digest),
        ("header_sha256", request.header_sha256),
    ):
        if getattr(receipt, name) != expected:
            raise HumanApprovalReceiptError(
                f"receipt {name} does not bind this launch candidate"
            )
    # Re-check the subject against the request as it stands now, not just
    # as it stood at mint time, so a narrowed request can never be
    # launched under a wider earlier approval.
    if not set(receipt.approved_capability_ids) <= set(
        request.admitted_capability_ids
    ):
        raise HumanApprovalReceiptError(
            "receipt approves a capability this request no longer admits"
        )
    if not set(receipt.approved_scope) <= set(request.allowed_scope):
        raise HumanApprovalReceiptError(
            "receipt approves scope outside this request's allowed scope"
        )
    if receipt.valid_until is not None:
        observed = parse_timestamp(
            at or _utcnow_iso(), "at", HumanApprovalReceiptError,
        )
        expires = parse_timestamp(
            receipt.valid_until, "valid_until", HumanApprovalReceiptError,
        )
        if observed >= expires:
            raise HumanApprovalReceiptError("receipt has expired")
    return receipt


def receipt_matches_launch_candidate(receipt, *, request, gate, at=None):
    """Non-raising form of :func:`validate_human_approval_receipt`."""
    try:
        validate_human_approval_receipt(
            receipt, request=request, gate=gate, at=at,
        )
    except (HumanApprovalReceiptError, ValueError):
        return False
    return True


def receipt_is_trusted_human_approval(receipt):
    """TRUST REVIEW helper: always False.

    A sealed receipt proves its bytes were not edited. It proves nothing
    about who wrote them. Establishing that an *authorized human* created
    a receipt needs an authenticated identity source and a trusted writer
    path, neither of which exists in this phase -- so no receipt is ever
    trusted human approval, no matter how well-formed.
    """
    return False


def human_approval_receipt_grants_no_capability():
    """TRUST REVIEW helper: True -- a receipt grants no capability."""
    return True
