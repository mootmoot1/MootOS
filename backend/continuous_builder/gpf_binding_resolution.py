"""GP-F2 -- Authoritative Binding Resolution Before Launch.

Before anything is even *eligible* for launch (that gate is GP-F4), every
system-owned input the launch decision will depend on must be resolved
from **authoritative storage**, not accepted as whatever object a caller
happens to pass in. This module is a thin orchestration layer: it does
not reimplement GP-E's forgery-detecting comparison
(``gpe_protocol.validate_worker_request``) -- it makes sure that
comparison is run against a *freshly reloaded* ``DurableJobHeader``/
``AttemptRecord`` from the GP-D ledger, never against copies the caller
(or, transitively, a worker) could have supplied instead.

``resolve_launch_bindings`` additionally checks that the named attempt is
the job's **current** attempt (the latest ``attempt_number``) -- a stale
attempt superseded by a retry is rejected outright, before GP-F4 ever
has to reason about it. A finished/non-``"started"`` attempt is already
refused by ``validate_worker_request``'s own authoritative reconstruction
(``create_worker_request`` unconditionally requires ``"started"``), so
this module does not duplicate that check -- it only *records*
``attempt_status`` as evidence.

Slice/job correlation (ADR-044): a ``WorkerRequest.correlation`` names a
product blueprint/slice by ID. This module does **not** ship its own
queue/SQLite access -- doing so here would risk exactly the "builder
queue lifecycle merged into execution lifecycle" mistake ADR-044 warns
against, and would force a live database dependency onto every caller of
this narrow resolution step. Instead it accepts an optional
``correlation_verifier(correlation) -> bool`` callable; the caller (GP-F3
supervisor) is responsible for wiring that to real, read-only product
truth (e.g. ``queue_projection.replay_slice``) when it is available. When
no verifier is supplied, correlation is recorded as **not checked** --
never silently treated as verified. GP-D remains execution truth; queue/
builder state remains product truth; this module writes to neither.

Zero authority. ``ResolvedLaunchBindings`` is evidence for GP-F4 to
consult, never a launch decision itself -- it carries an explicit
``launch_authorized`` flag that is always False.
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
from .gpd_attempt_ledger import ATTEMPT_STATUSES
from .gpe_protocol import WorkerProtocolError, WorkerRequest, validate_worker_request
from .timestamps import parse_timestamp

BINDING_RESOLUTION_VERSION = "gpf-launch-bindings-v1"
MAX_BINDINGS_BYTES = 4 * 1024
_TOKEN = object()


class BindingResolutionError(GPAEvalSchemaError):
    """Raised when system-owned launch inputs cannot be resolved/bound."""


def _utcnow_iso():
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class ResolvedLaunchBindings:
    """Evidence that a WorkerRequest matches authoritative GP-D/GP-B/GP-C
    state as of the moment of resolution. Never launch authority.
    """

    schema_version: str
    job_id: str
    attempt_id: str
    request_id: str
    request_sha256: str
    header_sha256: str
    attempt_sha256: str
    attempt_is_current: bool
    attempt_status: str
    correlation_present: bool
    correlation_checked: bool
    correlation_verified: bool
    resolved_at: str
    bindings_sha256: str
    launch_authorized: bool = False
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
            raise BindingResolutionError(
                "resolved bindings require trusted construction"
            )
        if self.schema_version != BINDING_RESOLUTION_VERSION:
            raise BindingResolutionError("schema_version is unsupported")
        for name in ("job_id", "attempt_id", "request_id"):
            require_id(getattr(self, name), name)
        for name in (
            "request_sha256", "header_sha256", "attempt_sha256",
            "bindings_sha256",
        ):
            require_sha256(getattr(self, name), name)
        if self.attempt_status not in ATTEMPT_STATUSES:
            raise BindingResolutionError("attempt_status is unsupported")
        if type(self.attempt_is_current) is not bool:
            raise BindingResolutionError("attempt_is_current must be a bool")
        for name in ("correlation_present", "correlation_checked", "correlation_verified"):
            if type(getattr(self, name)) is not bool:
                raise BindingResolutionError(f"{name} must be a bool")
        if self.correlation_verified and not self.correlation_checked:
            raise BindingResolutionError(
                "correlation cannot be verified without being checked"
            )
        if self.correlation_checked and not self.correlation_present:
            raise BindingResolutionError(
                "correlation cannot be checked when absent"
            )
        parse_timestamp(self.resolved_at, "resolved_at", BindingResolutionError)
        if self.launch_authorized is not False:
            raise BindingResolutionError(
                "resolved bindings can never themselves authorize launch"
            )
        for name in AUTHORITY_FLAGS:
            if getattr(self, name, False) is not False:
                raise BindingResolutionError(
                    "resolved bindings cannot claim authority"
                )
        if self.bindings_sha256 != sha256_hex(canonical_json(self._body())):
            raise BindingResolutionError("bindings_sha256 mismatch")
        if len(canonical_json(self.to_dict())) > MAX_BINDINGS_BYTES:
            raise BindingResolutionError("resolved bindings exceed byte bound")

    def _body(self):
        return {
            "attempt_id": self.attempt_id,
            "attempt_is_current": self.attempt_is_current,
            "attempt_sha256": self.attempt_sha256,
            "attempt_status": self.attempt_status,
            "correlation_checked": self.correlation_checked,
            "correlation_present": self.correlation_present,
            "correlation_verified": self.correlation_verified,
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
            "resolved_at": self.resolved_at,
            "result_trusted": False,
            "schema_version": self.schema_version,
            "worker_output_trusted": False,
        }

    def to_dict(self):
        body = dict(self._body())
        body["bindings_sha256"] = self.bindings_sha256
        return body


def _seal(values):
    for name in AUTHORITY_FLAGS:
        values[name] = False
    values["launch_authorized"] = False
    provisional = object.__new__(ResolvedLaunchBindings)
    for name, value in values.items():
        object.__setattr__(provisional, name, value)
    return ResolvedLaunchBindings(
        **values,
        bindings_sha256=sha256_hex(canonical_json(provisional._body())),
        _token=_TOKEN,
    )


def resolve_launch_bindings(
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
    resolved_at=None,
):
    """Resolve and cross-validate every system-owned launch input.

    ``header``/``attempt`` are always reloaded from ``store`` by ID --
    never accepted from the caller directly, so a caller cannot smuggle
    in a self-consistent-but-forged copy. ``contract``/``plan``/
    ``admission``/``admission_input``/``package`` are still supplied by
    the caller (GP-B/GP-C/Context Engine have no durable store of their
    own in this phase; only their digests are anchored in the durable
    header) -- ``validate_worker_request`` proves those supplied objects
    match what the header/attempt/request actually bind to, so a mismatch
    (forged or stale) fails closed here rather than silently launching.
    """
    if not isinstance(request, WorkerRequest):
        raise BindingResolutionError("request is invalid")
    header = store.load_header(job_id)
    attempts = store.load_attempts(job_id)
    attempt = next((a for a in attempts if a.attempt_id == attempt_id), None)
    if attempt is None:
        raise BindingResolutionError(
            "attempt not found in the durable ledger for this job"
        )
    latest = max(attempts, key=lambda item: item.attempt_number)
    attempt_is_current = attempt.attempt_id == latest.attempt_id

    try:
        validate_worker_request(
            request,
            header=header,
            attempt=attempt,
            contract=contract,
            plan=plan,
            admission=admission,
            admission_input=admission_input,
            package=package,
            correlation=request.correlation,
        )
    except (WorkerProtocolError, ValueError) as error:
        raise BindingResolutionError(
            f"request does not match authoritative bindings: {error}"
        ) from error

    if not attempt_is_current:
        raise BindingResolutionError(
            "attempt is not the job's current (latest) attempt"
        )
    # No separate "attempt.status == started" check is needed here:
    # validate_worker_request above already reconstructs the expected
    # request from this exact authoritative attempt, and
    # create_worker_request unconditionally refuses to bind any attempt
    # whose status isn't "started" -- so reaching this line already
    # guarantees it. attempt.status is still recorded below as evidence.

    correlation_present = request.correlation is not None
    correlation_checked = False
    correlation_verified = False
    if correlation_present and correlation_verifier is not None:
        correlation_checked = True
        correlation_verified = bool(correlation_verifier(request.correlation))

    values = {
        "schema_version": BINDING_RESOLUTION_VERSION,
        "job_id": job_id,
        "attempt_id": attempt_id,
        "request_id": request.request_id,
        "request_sha256": request.digest,
        "header_sha256": header.header_sha256,
        "attempt_sha256": attempt.attempt_sha256,
        "attempt_is_current": attempt_is_current,
        "attempt_status": attempt.status,
        "correlation_present": correlation_present,
        "correlation_checked": correlation_checked,
        "correlation_verified": correlation_verified,
        "resolved_at": resolved_at or _utcnow_iso(),
    }
    return _seal(values)


def binding_resolution_grants_no_capability():
    """TRUST REVIEW helper: True -- resolved bindings grant no capability."""
    return True
