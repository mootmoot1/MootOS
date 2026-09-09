"""One-shot consumption: spend a single dispatch opportunity exactly once.

Authorization alone is never sufficient for dispatch. This module is the
boundary where an opportunity is spent: it revalidates fresh authoritative
sources, revalidates the exact readiness intent, re-decides that no
semantic blocker appeared, and only then atomically records that this
request's one dispatch opportunity is gone.

The record is a spent-marker, not a capability. It grants no launch,
dispatch, publication, merge or worker-result trust, and holding one is
not permission to invoke anything. No worker or provider is invoked here.

TrustedLaunchAuthorization does not exist yet, so the authorization is
carried as an opaque (id, digest) pair that is bound into the record but
NOT verified. Until a real authorization record exists, this module proves
one-shot-ness and currentness, not that an authorization was ever issued.
"""

import os
import secrets
from dataclasses import dataclass, fields
from datetime import datetime, timezone

from . import gpf_launch_candidate_binding as source
from .gpf_launch_dispatch_intent import (
    LaunchIntentError, TrustedLaunchDispatchIntent,
    load_launch_dispatch_intent,
)
from .gpf_launch_semantics import evaluate_launch_eligibility
from .gpf_launch_state_projection import project_launch_state

VERSION = "gpf-launch-authorization-consumption-v1"


class LaunchConsumptionError(ValueError):
    """Consumption refused; no opportunity was spent unless stated."""

    consumption_recorded = False


class LaunchAlreadyConsumed(LaunchConsumptionError):
    """This request's single dispatch opportunity is already spent."""


class LaunchConsumptionBlocked(LaunchConsumptionError):
    """A semantic blocker appeared; nothing was consumed and none may be."""

    def __init__(self, message, blocker_codes=()):
        super().__init__(message)
        self.blocker_codes = tuple(blocker_codes)


class LaunchConsumptionDrift(LaunchConsumptionError):
    """Sources moved around the write. The opportunity is spent and DEAD.

    The consumption record exists, so nothing may be dispatched for this
    request ever again, and no worker was invoked. A caller that sees this
    must not dispatch; it must open a new GP-D attempt instead.
    """

    consumption_recorded = True


def _check(condition, reason):
    if not condition:
        raise LaunchConsumptionError(reason)


def _hash(value):
    return source._digest(source._canonical(value))


@dataclass(frozen=True)
class LaunchAuthorizationConsumption:
    """Durable spent-marker for one dispatch opportunity. Zero authority."""

    schema_version: str
    authorization_id: str
    job_id: str
    attempt_id: str
    request_id: str
    request_sha256: str
    authorization_sha256: str
    dispatch_intent_sha256: str
    reservation_sha256: str
    source_tokens_sha256: str
    consumed_at: str
    consumption_sha256: str

    def __post_init__(self):
        _check(self.schema_version == VERSION,
               "unsupported consumption schema")
        for name in ("authorization_id", "job_id", "attempt_id",
                     "request_id"):
            source._id(getattr(self, name))
        for name in ("request_sha256", "authorization_sha256",
                     "dispatch_intent_sha256", "reservation_sha256",
                     "source_tokens_sha256", "consumption_sha256"):
            source._sha(getattr(self, name))
        _check(type(self.consumed_at) is str and
               0 < len(self.consumed_at) <= 128, "invalid consumption time")
        stamp = datetime.fromisoformat(
            self.consumed_at.replace("Z", "+00:00"))
        _check(stamp.utcoffset() is not None,
               "consumption time needs timezone")
        body = self.to_dict()
        body.pop("consumption_sha256")
        _check(self.consumption_sha256 == _hash(body),
               "consumption digest mismatch")

    def __getattr__(self, name):
        if name in source._FLAGS:
            return False
        raise AttributeError(name)

    def to_dict(self):
        body = {item.name: getattr(self, item.name) for item in fields(self)}
        body.update({flag: False for flag in source._FLAGS})
        return body


def _decode(raw):
    body = source._sealed(raw, "consumption_sha256")
    expected = {item.name for item in fields(LaunchAuthorizationConsumption)}
    _check(set(body) == expected | set(source._FLAGS),
           "consumption fields mismatch")
    _check(raw == source._canonical(body),
           "noncanonical persisted consumption")
    return LaunchAuthorizationConsumption(**{k: body[k] for k in expected})


def _spend_once(directory, name, raw):
    """Create-if-absent. An existing record always loses; never idempotent.

    This is the one-shot primitive: os.link into a fixed name is atomic on
    POSIX, so exactly one concurrent caller can win. A byte-identical
    replay is still a second attempt to spend a spent opportunity and is
    refused, unlike the write-once assignment store where replay is benign.
    """
    temporary = ".consumption-" + secrets.token_hex(16)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
    fd = os.open(temporary, flags, 0o600, dir_fd=directory)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, name, src_dir_fd=directory,
                    dst_dir_fd=directory, follow_symlinks=False)
        except FileExistsError:
            raise LaunchAlreadyConsumed(
                "this dispatch opportunity is already spent") from None
        # Make the spend durable before anything downstream observes it. A
        # crash between link and fsync could otherwise lose the marker and
        # let the same opportunity be spent twice after restart.
        os.fsync(directory)
    finally:
        os.unlink(temporary, dir_fd=directory)
        os.fsync(directory)


def _current(facts, request_bytes, approvals):
    """Rebuild facts, projection and verdict from fresh sources."""
    fresh, projection = project_launch_state(
        facts=facts, request_bytes=request_bytes)
    verdict = evaluate_launch_eligibility(
        facts=fresh, projection=projection, approvals=approvals)
    return fresh, projection, verdict


def _matching_intent(fresh, projection, now):
    """Readiness must name this exact candidate and still be in window.

    Deliberately compares immutable candidate identity, not the source
    token the intent was issued against. Requiring token equality would
    collapse "a semantic blocker appeared" into "any byte moved", so a
    heartbeat would void readiness while a cancellation would report the
    same coarse error. Safety does not depend on that equality: step 3
    re-decides eligibility against the sources as they are now, and the
    narrow expiry bounds how stale a selection may be. The issuance token
    is retained on the record as evidence of what was selected against.
    """
    intent = load_launch_dispatch_intent(
        job_id=fresh.job_id, request_id=fresh.request_id)
    _check(type(intent) is TrustedLaunchDispatchIntent, "untrusted intent")
    _check((intent.job_id, intent.attempt_id, intent.request_id,
            intent.request_sha256, intent.binding_sha256,
            intent.reservation_sha256) ==
           (fresh.job_id, fresh.attempt_id, fresh.request_id,
            fresh.request_sha256, fresh.binding_sha256,
            projection.reservation_sha256),
           "readiness does not name this exact launch candidate")
    _check(not intent.is_expired(now), "readiness window has expired")
    return intent


def consume_launch_authorization(*, authorization_id, authorization_sha256,
                                 facts, request_bytes, approvals=()):
    """Spend this request's single dispatch opportunity, or refuse.

    Order matters and is the whole safety argument:

    1. rebuild facts and lifecycle from fresh authoritative sources;
    2. revalidate the exact readiness intent, including expiry;
    3. re-decide eligibility -- a cancellation, execution_unknown or
       reconciliation that appeared after authorization blocks here;
    4. atomically record consumption, create-if-absent;
    5. re-verify (1)-(3) after the write and refuse dispatch on drift.

    Only after this returns successfully may a future executor invoke the
    exact bound WorkerRequest, exactly once. This function invokes nothing.
    """
    source._id(authorization_id)
    source._sha(authorization_sha256)
    _check(type(approvals) is tuple, "invalid approval collection")
    now = datetime.now(timezone.utc)
    try:
        fresh, projection, verdict = _current(facts, request_bytes, approvals)
        intent = _matching_intent(fresh, projection, now)
    except LaunchIntentError as error:
        raise LaunchConsumptionError(str(error)) from None
    if verdict.eligible is not True:
        raise LaunchConsumptionBlocked(
            "a semantic blocker prevents consumption", verdict.blocker_codes)
    values = dict(
        schema_version=VERSION, authorization_id=authorization_id,
        job_id=fresh.job_id, attempt_id=fresh.attempt_id,
        request_id=fresh.request_id, request_sha256=fresh.request_sha256,
        authorization_sha256=authorization_sha256,
        dispatch_intent_sha256=intent.intent_sha256,
        reservation_sha256=projection.reservation_sha256,
        source_tokens_sha256=projection.source_tokens_sha256,
        consumed_at=datetime.now(timezone.utc).isoformat(),
    )
    body = dict(values, **{flag: False for flag in source._FLAGS})
    record = LaunchAuthorizationConsumption(
        **values, consumption_sha256=_hash(body))
    with source._directory(source._AUTHORITATIVE_ROOT) as root, \
            source._child(root, "launch_consumptions", True) as store, \
            source._child(store, fresh.job_id, True) as job:
        _spend_once(job, fresh.request_id + ".json",
                    source._canonical(record.to_dict()))
    # The opportunity is now spent no matter what follows. Re-verify, and on
    # any drift refuse dispatch: a burned opportunity with nothing executed
    # is safe; dispatching against moved sources is not.
    try:
        after, after_projection, after_verdict = _current(
            fresh, request_bytes, approvals)
        _matching_intent(after, after_projection,
                         datetime.now(timezone.utc))
        drifted = after_verdict.eligible is not True
    except (LaunchConsumptionError, LaunchIntentError, ValueError):
        drifted = True
    if drifted:
        raise LaunchConsumptionDrift(
            "sources moved around consumption; opportunity spent, "
            "dispatch refused")
    return record


def load_launch_consumption(*, job_id, request_id):
    """Read the spent-marker, if any, from the fixed authoritative store."""
    source._id(job_id)
    source._id(request_id)
    try:
        with source._directory(source._AUTHORITATIVE_ROOT) as root, \
                source._child(root, "launch_consumptions") as store, \
                source._child(store, job_id) as job:
            record = _decode(source._read(job, request_id + ".json"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError, KeyError, TypeError):
        raise LaunchConsumptionError(
            "consumption record unavailable or invalid") from None
    _check((record.job_id, record.request_id) == (job_id, request_id),
           "persisted path/identity mismatch")
    return record


def consumption_grants_no_capability():
    """TRUST REVIEW helper: True -- a spent-marker is never authority."""
    return True
